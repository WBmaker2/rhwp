#!/usr/bin/env python3
"""Structured, dry-run-first executor for approved staging infrastructure actions."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from scripts.staging_infrastructure_apply_approval import MutationApprovalError, validate_apply_ready_package, validate_mutation_approval
from scripts.staging_infrastructure_apply_provenance import ProvenanceError, validate_checked_out_git_binding, validate_pre_auth_provenance
from scripts.staging_infrastructure_validation import canonical_json_bytes, read_bounded_json_file

ELIGIBLE_STAGES = ("api-baseline", "service-accounts", "artifact-registry", "secret-metadata")
KIND_BY_STAGE = {
    "api-baseline": "ensure-api-enabled", "service-accounts": "ensure-service-account",
    "artifact-registry": "ensure-artifact-repository", "secret-metadata": "ensure-secret-container",
}
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
API = re.compile(r"^[a-z][a-z0-9-]{1,61}\.googleapis\.com$")
SA = re.compile(r"^[a-z][a-z0-9-]{5,28}[a-z0-9]$")
REPOSITORY = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
LOCATION = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SECRET = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,254}$")


class ApplyExecutionError(RuntimeError):
    pass


def execute_approved_actions(
    package: dict[str, Any], approved: dict[str, Any], claims: dict[str, Any],
    plan_output: Path, post_output: Path, *, apply: bool = False,
    observer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    runner: Callable[[tuple[str, ...]], str] | None = None,
    git_binding_validator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create dry-run evidence, or explicitly apply every approved action once.

    ``runner`` receives an immutable argv tuple.  The default uses
    ``subprocess.run(..., shell=False)`` and intentionally never prints command
    stdout/stderr into evidence or stdout.
    """
    _validate_output_paths(plan_output, post_output)
    try:
        validate_pre_auth_provenance(package, approved, claims)
    except ProvenanceError as error:
        raise ApplyExecutionError("pre-auth provenance validation failed") from error
    try: review = validate_apply_ready_package(package)
    except MutationApprovalError as error: raise ApplyExecutionError("actual execution requires an apply-ready package") from error
    actions = _approved_actions(review, approved)
    plan_evidence = {
        "schemaVersion": "rhwp.staging-infrastructure-apply-plan-evidence/v1",
        "mode": "apply" if apply else "dry-run", "projectId": approved["projectId"],
        "approvedActionIds": approved["approvedActionIds"],
        "approvalBinding": {"applyReadyPackageSha256": approved["applyReadyPackageSha256"], "environmentAttestationSha256": approved["environmentAttestationSha256"], "runId": claims["runId"], "runAttempt": claims["runAttempt"], "approvalNonce": approved["approvalNonce"]},
        "actions": [{"actionId": item["actionId"], "stageId": item["stageId"], "resourceKind": item["resourceKind"], "planned": True} for item in actions],
        "containsCredentials": False, "containsSecretValues": False,
    }
    if not apply:
        _atomic_json(plan_output, plan_evidence)
        _atomic_json(post_output, {**plan_evidence, "schemaVersion": "rhwp.staging-infrastructure-apply-observed-evidence/v1", "observed": [], "status": "dry-run-complete"})
        return {"mode": "dry-run", "status": "dry-run-complete", "executedActionIds": []}
    if observer is None:
        raise ApplyExecutionError("actual apply requires a fixed read-only observer")
    try:
        (git_binding_validator or validate_checked_out_git_binding)(package, claims)
    except ProvenanceError as error:
        raise ApplyExecutionError("checked-out Git provenance validation failed") from error
    _atomic_json(plan_output, plan_evidence)
    observed: list[dict[str, Any]] = []
    invoke = runner or _run_fixed_argv
    for action in actions:
        try:
            before = _observation_state(action, observer(action))
        except Exception as error:
            _failure_evidence(post_output, observed, action, "precondition-observation")
            raise ApplyExecutionError(f"precondition observation failed for {action['actionId']}") from error
        if before == "incompatible":
            _failure_evidence(post_output, observed, action, "precondition-mismatch")
            raise ApplyExecutionError(f"precondition mismatch for {action['actionId']}")
        if before == "present":
            observed.append({"actionId": action["actionId"], "stageId": action["stageId"], "status": "already-present-noop"})
            continue
        argv = _fixed_argv(approved["projectId"], action)
        try:
            invoke(argv)
        except Exception as error:
            _failure_evidence(post_output, observed, action, "write")
            raise ApplyExecutionError(f"command failed for approved action {action['actionId']}") from error
        try:
            after = _observation_state(action, observer(action))
        except Exception as error:
            _failure_evidence(post_output, observed, action, "postcondition-observation", write_returned_success=True, postcondition_status="unknown")
            raise ApplyExecutionError(f"postcondition observation failed for {action['actionId']}") from error
        if after != "present":
            _failure_evidence(post_output, observed, action, "postcondition-mismatch", write_returned_success=True, postcondition_status=after)
            raise ApplyExecutionError(f"postcondition mismatch for {action['actionId']}")
        observed.append({"actionId": action["actionId"], "stageId": action["stageId"], "status": "observed-after-apply"})
    _atomic_json(post_output, {
        "schemaVersion": "rhwp.staging-infrastructure-apply-observed-evidence/v1", "mode": "apply",
        "status": "apply-complete", "executedActionIds": [item["actionId"] for item in observed],
        "observed": observed, "containsCredentials": False, "containsSecretValues": False,
    })
    return {"mode": "apply", "status": "apply-complete", "executedActionIds": [item["actionId"] for item in observed]}


def _observation_state(action: dict[str, Any], observation: Any) -> str:
    if not isinstance(observation, dict) or set(observation) != {"state", "resourceKind", "matchesDesired"}:
        raise ApplyExecutionError("observer result must use the exact structured contract")
    state = observation["state"]
    if state not in ("missing", "present", "incompatible") or observation["resourceKind"] != action["resourceKind"]:
        raise ApplyExecutionError("observer result is incompatible with the approved action")
    if not isinstance(observation["matchesDesired"], bool):
        raise ApplyExecutionError("observer desired-state result is invalid")
    if state == "present" and observation["matchesDesired"] is not True:
        return "incompatible"
    if state == "missing" and observation["matchesDesired"] is not False:
        raise ApplyExecutionError("missing observer result cannot assert desired state")
    return state


def _failure_evidence(post_output: Path, observed: list[dict[str, Any]], action: dict[str, Any], phase: str, *, write_returned_success: bool = False, postcondition_status: str | None = None) -> None:
    evidence = {
        "schemaVersion": "rhwp.staging-infrastructure-apply-observed-evidence/v1", "mode": "apply",
        "status": "failed-first-error", "failurePhase": phase,
        "executedActionIds": [item["actionId"] for item in observed], "failedActionId": action["actionId"],
        "containsCredentials": False, "containsSecretValues": False,
    }
    if write_returned_success:
        evidence.update({"writeAttemptedActionId": action["actionId"], "writeReturnedSuccess": True, "postconditionStatus": postcondition_status})
    _atomic_json(post_output, evidence)


def _approved_actions(package: dict[str, Any], approved: dict[str, Any]) -> list[dict[str, Any]]:
    if approved.get("cloudMutationApproved") is not True or approved.get("deploymentApproved") is not False:
        raise ApplyExecutionError("approved record does not authorize infrastructure mutation only")
    candidates = package.get("canonicalMutationSubset")
    if not isinstance(candidates, list): raise ApplyExecutionError("package action subset is invalid")
    ids = approved.get("approvedActionIds")
    if not isinstance(ids, list) or [item.get("actionId") if isinstance(item, dict) else None for item in candidates] != ids:
        raise ApplyExecutionError("package actions do not exactly match approved ordered actions")
    stages: list[str] = []
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict): raise ApplyExecutionError("package action is invalid")
        stage, kind = candidate.get("stageId"), candidate.get("resourceKind")
        if stage not in ELIGIBLE_STAGES or kind != KIND_BY_STAGE[stage]:
            raise ApplyExecutionError("unsafe stage or action kind")
        if stage not in stages: stages.append(stage)
        if stages != list(ELIGIBLE_STAGES[:len(stages)]): raise ApplyExecutionError("action stages are out of canonical order")
        _fixed_argv(approved["projectId"], candidate)  # validation is shared with execution
        result.append(candidate)
    if stages != list(ELIGIBLE_STAGES) or len({item["actionId"] for item in result}) != len(result):
        raise ApplyExecutionError("approved action set is incomplete or duplicated")
    return result


def _fixed_argv(project_id: Any, action: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(project_id, str) or not PROJECT.fullmatch(project_id) or "staging" not in project_id or "prod" in project_id:
        raise ApplyExecutionError("project identifier is not staging-only")
    resource, kind = action.get("resourceIdentifier"), action.get("resourceKind")
    if not isinstance(resource, dict): raise ApplyExecutionError("resource identifier is invalid")
    if kind == "ensure-api-enabled":
        api = resource.get("api")
        if not isinstance(api, str) or not API.fullmatch(api): raise ApplyExecutionError("API identifier is unsafe")
        return ("gcloud", "services", "enable", api, "--project", project_id, "--quiet")
    if kind == "ensure-service-account":
        identity = resource.get("identity")
        local = identity.split("@", 1)[0] if isinstance(identity, str) else ""
        if not SA.fullmatch(local) or not identity.endswith(f"@{project_id}.iam.gserviceaccount.com"):
            raise ApplyExecutionError("service account identifier is unsafe")
        return ("gcloud", "iam", "service-accounts", "create", local, "--project", project_id, "--quiet")
    if kind == "ensure-artifact-repository":
        name, location = resource.get("repository"), resource.get("location")
        if not isinstance(name, str) or not REPOSITORY.fullmatch(name) or not isinstance(location, str) or not LOCATION.fullmatch(location):
            raise ApplyExecutionError("artifact repository identifier is unsafe")
        if resource.get("format") != "DOCKER": raise ApplyExecutionError("artifact repository format is unsafe")
        return ("gcloud", "artifacts", "repositories", "create", name, "--repository-format=docker", "--location", location, "--project", project_id, "--quiet")
    if kind == "ensure-secret-container":
        name = resource.get("name")
        if not isinstance(name, str) or not SECRET.fullmatch(name) or resource.get("replication") != "automatic" or resource.get("valueIncluded") is not False: raise ApplyExecutionError("secret metadata identifier is unsafe")
        return ("gcloud", "secrets", "create", name, "--replication-policy=automatic", "--project", project_id, "--quiet")
    raise ApplyExecutionError("action kind is not allowlisted")


def _run_fixed_argv(argv: tuple[str, ...]) -> str:
    completed = subprocess.run(list(argv), shell=False, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0: raise ApplyExecutionError("fixed executable returned non-zero")
    return "completed"


def _observe_fixed(project_id: str, action: dict[str, Any]) -> dict[str, Any]:
    """Use only successful fixed list queries; errors never mean ``missing``."""
    resource, kind = action["resourceIdentifier"], action["resourceKind"]
    if kind == "ensure-api-enabled":
        argv = ("gcloud", "services", "list", "--enabled", "--project", project_id, "--filter", f"config.name={resource['api']}", "--format=json")
    elif kind == "ensure-service-account":
        argv = ("gcloud", "iam", "service-accounts", "list", "--project", project_id, "--filter", f"email={resource['identity']}", "--format=json")
    elif kind == "ensure-artifact-repository":
        argv = ("gcloud", "artifacts", "repositories", "list", "--location", resource["location"], "--project", project_id, "--filter", f"name~/{resource['repository']}$", "--format=json")
    else:
        argv = ("gcloud", "secrets", "list", "--project", project_id, "--filter", f"name~/{resource['name']}$", "--format=json")
    completed = subprocess.run(list(argv), shell=False, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise ApplyExecutionError("fixed read-only observation command failed")
    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ApplyExecutionError("fixed read-only observation result is not structured JSON") from error
    result = _observe_records(kind, project_id, resource, values)
    if kind == "ensure-service-account" and result["state"] == "present":
        key_argv = ("gcloud", "iam", "service-accounts", "keys", "list", "--iam-account", resource["identity"], "--managed-by=user", "--project", project_id, "--format=json")
        keys = subprocess.run(list(key_argv), shell=False, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if keys.returncode != 0: raise ApplyExecutionError("service-account key observation command failed")
        try: key_values = json.loads(keys.stdout)
        except json.JSONDecodeError as error: raise ApplyExecutionError("service-account key observation result is not structured JSON") from error
        if not isinstance(key_values, list): raise ApplyExecutionError("service-account key observation result must be a JSON array")
        if key_values: return {"state": "incompatible", "resourceKind": kind, "matchesDesired": False}
    return result


def _observe_records(kind: str, project_id: str, resource: dict[str, Any], values: Any) -> dict[str, Any]:
    if not isinstance(values, list): raise ApplyExecutionError("fixed read-only observation result must be a JSON array")
    if not values: return {"state": "missing", "resourceKind": kind, "matchesDesired": False}
    if len(values) != 1 or not isinstance(values[0], dict): return {"state": "incompatible", "resourceKind": kind, "matchesDesired": False}
    value = values[0]
    if kind == "ensure-api-enabled":
        match = value.get("config", {}).get("name") == resource["api"]
    elif kind == "ensure-service-account":
        match = value.get("email") == resource["identity"] and resource["identity"].endswith(f"@{project_id}.iam.gserviceaccount.com")
    elif kind == "ensure-artifact-repository":
        match = value.get("name") == f"projects/{project_id}/locations/{resource['location']}/repositories/{resource['repository']}" and value.get("format") == "DOCKER"
    else:
        replication = value.get("replication")
        match = value.get("name") == f"projects/{project_id}/secrets/{resource['name']}" and isinstance(replication, dict) and set(replication) == {"automatic"} and isinstance(replication["automatic"], dict) and not replication["automatic"]
    return {"state": "present" if match else "incompatible", "resourceKind": kind, "matchesDesired": match}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _validate_file_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(value, indent=2)); stream.flush(); os.fsync(stream.fileno())
        if temporary.is_symlink() or path.is_symlink(): raise ApplyExecutionError("output path cannot be a symlink")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ApplyExecutionError("could not publish atomic evidence") from error


def _validate_output_paths(plan: Path, post: Path) -> None:
    if plan.resolve(strict=False) == post.resolve(strict=False) or plan in post.parents or post in plan.parents:
        raise ApplyExecutionError("plan and observed evidence outputs must be separate")
    if plan.exists() and post.exists() and plan.samefile(post):
        raise ApplyExecutionError("plan and observed evidence outputs cannot be hardlink aliases")
    for path in (plan, post): _validate_file_target(path)


def _validate_file_target(path: Path) -> None:
    # macOS exposes /var and /tmp as system compatibility symlinks.  They do
    # not make a caller-controlled alias; reject every other component.
    system_aliases = {Path("/var"), Path("/tmp")}
    if any(component.is_symlink() and component not in system_aliases for component in (path, *path.parents)):
        raise ApplyExecutionError("evidence paths cannot use symlinks")
    if path.exists() and (not path.is_file() or stat.S_ISLNK(path.stat().st_mode)):
        raise ApplyExecutionError("evidence output must be a regular file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run approved staging infrastructure actions; dry-run is the default")
    parser.add_argument("--package", type=Path, required=True); parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True); parser.add_argument("--plan-evidence", type=Path, required=True); parser.add_argument("--post-evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        package, raw = read_bounded_json_file(args.package, "review package")
        approval, _ = read_bounded_json_file(args.approval, "mutation approval")
        claims, _ = read_bounded_json_file(args.provenance, "provenance")
        if not all(isinstance(value, dict) for value in (package, approval, claims)): raise ApplyExecutionError("executor inputs must be JSON objects")
        approved = validate_mutation_approval(package, raw, approval)
        observer = (lambda action: _observe_fixed(approved["projectId"], action)) if args.apply else None
        result = execute_approved_actions(package, approved, claims, args.plan_evidence, args.post_evidence, apply=args.apply, observer=observer)
    except (ApplyExecutionError, MutationApprovalError, OSError) as error:
        print(f"staging infrastructure apply failed: {error}", file=sys.stderr); return 1
    print(json.dumps({"mode": result["mode"], "status": result["status"], "executedActionIds": result["executedActionIds"]})); return 0


if __name__ == "__main__": raise SystemExit(main())
