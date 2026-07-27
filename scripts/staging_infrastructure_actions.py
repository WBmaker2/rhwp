#!/usr/bin/env python3
"""Build a deterministic, non-executable staging infrastructure action manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.staging_infrastructure_approval import (
        InfrastructureApprovalError,
        load_json_with_bytes,
        validate_infrastructure_approval,
    )
except ImportError:  # pragma: no cover - direct script execution
    from staging_infrastructure_approval import (  # type: ignore[no-redef]
        InfrastructureApprovalError, load_json_with_bytes, validate_infrastructure_approval,
    )

PLAN_SCHEMA = "rhwp.staging-infrastructure-plan/v1"
EXECUTION_SCHEMA = "rhwp.staging-infrastructure-execution/v1"
APPROVAL_RESULT_SCHEMA = "rhwp.staging-infrastructure-approval-result/v1"
STAGES = (
    ("project-billing", "observation-only"),
    ("api-baseline", "eligible-mutation"),
    ("firebase-foundation", "irreversible-manual-decision"),
    ("service-accounts", "eligible-mutation"),
    ("artifact-registry", "eligible-mutation"),
    ("secret-metadata", "eligible-mutation"),
    ("iam-bindings", "deferred-resource-specific"),
    ("budget-guardrails", "irreversible-manual-decision"),
    ("cloud-run-prerequisites", "blocked-deferred"),
    ("cloud-tasks-prerequisites", "blocked-deferred"),
    ("post-bootstrap-evidence", "observation-only"),
)
SENSITIVE = ("accesstoken", "authorization", "clientsecret", "credential", "idtoken", "token", "secret", "apikey",
             "password", "privatekey", "refreshtoken", "secretvalue", "firebaseapikey",
             "internalflushtoken")
EXECUTABLE = ("command", "argv", "shell")


class InfrastructureActionsError(RuntimeError):
    pass


def build_execution_manifest(
    plan: dict[str, Any], approval_result: dict[str, Any], *, plan_bytes: bytes | None = None
) -> dict[str, Any]:
    """Translate only the canonical plan structure into safe structured actions."""
    digest = _require_exact_plan_bytes(plan, plan_bytes)
    _reject_unsafe(plan, "plan")
    _reject_unsafe(approval_result, "approval")
    stages = _validate_plan(plan)
    _validate_approval_result(plan, approval_result, digest)
    actions: list[dict[str, Any]] = []
    final_action_by_stage: dict[str, str] = {}
    for stage in stages:
        stage_id = stage["id"]
        classification = dict(STAGES)[stage_id]
        dependencies = [final_action_by_stage[item] for item in stage["dependsOn"]]
        stage_actions = _stage_actions(stage, classification, dependencies)
        if not stage_actions:
            raise InfrastructureActionsError(f"stage {stage_id} must produce actions")
        previous = None
        for action in stage_actions:
            if previous is not None:
                action["dependencies"] = [*action["dependencies"], previous]
            actions.append(action)
            previous = action["id"]
        final_action_by_stage[stage_id] = previous  # type: ignore[assignment]
    _validate_actions(actions)
    source = plan["sourceEvidence"]
    return {
        "schemaVersion": EXECUTION_SCHEMA,
        "status": approval_result["status"],
        "projectId": plan["projectId"],
        "billingAccount": plan["billingAccount"],
        "sourceEvidence": {
            "commitSha": source["commitSha"],
            "planSha256": approval_result["planSha256"],
            "approvalResultSchema": approval_result["schemaVersion"],
        },
        "actions": actions,
        "security": {
            "secretValuesIncluded": False,
            "productionResourcesAllowed": False,
            "deploymentAuthorized": False,
            "containsMutationCommands": False,
            "mutationCommands": [],
        },
    }


def _stage_actions(stage: dict[str, Any], classification: str, dependencies: list[str]) -> list[dict[str, Any]]:
    stage_id, resources, rollback = stage["id"], stage["resources"], stage["rollbackBoundary"]
    def action(kind: str, suffix: str, resource: Any, desired: Any, evidence: Any) -> dict[str, Any]:
        return {"id": f"{stage_id}.{suffix}", "stageId": stage_id,
                "classification": classification, "kind": kind, "resource": resource,
                "dependencies": list(dependencies), "desiredState": desired,
                "rollbackBoundary": rollback, "evidenceQuery": evidence}
    if stage_id == "project-billing":
        _require_keys(resources, {"projectId", "billingAccount", "region", "forbiddenProjectIds"}, stage_id)
        for field in ("projectId", "billingAccount", "region"):
            _nonempty(resources[field], f"project-billing {field}")
        _nonempty_strings(resources["forbiddenProjectIds"], "project-billing forbiddenProjectIds")
        return [
            action("verify-project", "verify-project", {"projectId": resources["projectId"], "region": resources["region"]}, {"exists": True, "environment": "staging"}, {"type": "project-metadata", "fields": ["projectId", "region"]}),
            action("verify-billing-link", "verify-billing-link", {"projectId": resources["projectId"], "billingAccount": resources["billingAccount"]}, {"linked": True}, {"type": "billing-link", "fields": ["projectId", "billingAccount"]}),
            action("verify-production-separation", "verify-production-separation", {"projectId": resources["projectId"], "forbiddenProjectIds": resources["forbiddenProjectIds"]}, {"forbiddenProjectIdsExcluded": True}, {"type": "project-separation", "fields": ["projectId", "forbiddenProjectIds"]}),
        ]
    if stage_id == "api-baseline":
        if not isinstance(resources, list) or not resources or not all(isinstance(item, str) and item for item in resources):
            raise InfrastructureActionsError("api-baseline resources must be a non-empty API list")
        return [action("ensure-api-enabled", f"ensure-api-{index + 1:02d}", {"api": api}, {"enabled": True, "operation": "enable-only"}, {"type": "enabled-service-list", "api": api}) for index, api in enumerate(resources)]
    if stage_id == "firebase-foundation":
        _require_keys(resources, {"projectId", "authDomain", "authorizedDomains", "firestoreLocation", "storageBucket", "storageLocation", "hostingSite"}, stage_id)
        for field in ("projectId", "authDomain", "firestoreLocation", "storageBucket", "storageLocation", "hostingSite"):
            _nonempty(resources[field], f"firebase-foundation {field}")
        _nonempty_strings(resources["authorizedDomains"], "firebase-foundation authorizedDomains")
        entries = (("verify-firebase-project", "firebase-project", {"projectId": resources["projectId"]}, {"linked": True}, ["projectId"]),
                   ("verify-firestore-location", "firestore-location", {"location": resources["firestoreLocation"]}, {"matchesPlan": True}, ["location"]),
                   ("verify-storage-bucket", "storage-bucket", {"bucket": resources["storageBucket"], "location": resources["storageLocation"]}, {"matchesPlan": True}, ["bucket", "location"]),
                   ("verify-hosting-site", "hosting-site", {"site": resources["hostingSite"]}, {"matchesPlan": True}, ["site"]))
        return [action(kind, suffix, resource, desired, {"type": "firebase-resource", "fields": fields}) for kind, suffix, resource, desired, fields in entries]
    if stage_id == "service-accounts":
        _require_keys(resources, {"collaboration", "documentApi", "documentWorker", "tasksCaller"}, stage_id)
        for name in ("collaboration", "documentApi", "documentWorker", "tasksCaller"):
            _nonempty(resources[name], f"service-account {name}")
        return [action("ensure-service-account", f"ensure-{name}", {"identity": resources[name], "workload": name}, {"exists": True, "operation": "create-if-missing", "keysAllowed": False}, {"type": "service-account", "identity": resources[name]}) for name in ("collaboration", "documentApi", "documentWorker", "tasksCaller")]
    if stage_id == "artifact-registry":
        _require_keys(resources, {"repository", "location"}, stage_id)
        _nonempty(resources["repository"], "artifact repository")
        _nonempty(resources["location"], "artifact location")
        return [action("ensure-artifact-repository", "ensure-repository", resources, {"exists": True, "operation": "create-if-missing", "deletionAllowed": False}, {"type": "artifact-repository", "fields": ["repository", "location"]})]
    if stage_id == "secret-metadata":
        if not isinstance(resources, dict) or not resources:
            raise InfrastructureActionsError("secret-metadata resources must be a non-empty object")
        result = []
        for name in sorted(resources):
            secret = resources[name]
            _require_keys(secret, {"name", "versionReference", "valueIncluded"}, f"secret {name}")
            if secret["valueIncluded"] is not False:
                raise InfrastructureActionsError("secret metadata valueIncluded must be false")
            _nonempty(secret["name"], f"secret {name} name")
            _nonempty(secret["versionReference"], f"secret {name} versionReference")
            result.append(action("ensure-secret-container", f"ensure-{name}", {"name": secret["name"], "valueIncluded": False}, {"exists": True, "operation": "create-if-missing", "versionsAllowed": False}, {"type": "secret-container", "name": secret["name"]}))
        return result
    if stage_id == "iam-bindings":
        if not isinstance(resources, list) or not resources:
            raise InfrastructureActionsError("iam-bindings resources must be a non-empty array")
        result = []
        for index, binding in enumerate(resources):
            _require_keys(binding, {"principal", "role", "resource"}, f"iam binding {index}")
            for field in ("principal", "role", "resource"):
                _nonempty(binding[field], f"iam binding {index} {field}")
            result.append(action("review-iam-binding", f"review-{index + 1:02d}", binding, {"approvedForMutation": False, "beforeAfterDiffRequired": True}, {"type": "iam-binding-diff", "fields": ["principal", "role", "resource"]}))
        return result
    if stage_id == "budget-guardrails":
        _require_keys(resources, {"currency", "amount", "thresholds", "notificationChannels"}, stage_id)
        _nonempty(resources["currency"], "budget currency")
        _positive_number(resources["amount"], "budget amount")
        if not isinstance(resources["thresholds"], list) or not resources["thresholds"]:
            raise InfrastructureActionsError("budget thresholds must be a non-empty array")
        for threshold in resources["thresholds"]:
            _positive_number(threshold, "budget threshold")
        _nonempty_strings(resources["notificationChannels"], "budget notificationChannels")
        return [action("verify-budget", "verify-budget", {"currency": resources["currency"], "amount": resources["amount"]}, {"exists": True, "mutationAuthorized": False}, {"type": "budget", "fields": ["currency", "amount"]}), action("verify-notification-channel", "verify-notification-channel", {"notificationChannels": resources["notificationChannels"]}, {"exists": True, "mutationAuthorized": False}, {"type": "notification-channel", "fields": ["notificationChannels"]})]
    if stage_id == "cloud-run-prerequisites":
        _require_keys(resources, {"collaboration", "documentApi", "documentWorker"}, stage_id)
        for name in ("collaboration", "documentApi", "documentWorker"):
            _validate_cloud_run_service(resources[name], name)
        return [action("record-cloud-run-prerequisite", f"record-{name}", {"service": resources[name]["name"], "state": resources[name].get("state")}, {"state": "blocked-pending-image-digest", "mutationAuthorized": False}, {"type": "cloud-run-prerequisite", "service": resources[name]["name"]}) for name in ("collaboration", "documentApi", "documentWorker")]
    if stage_id == "cloud-tasks-prerequisites":
        _require_keys(resources, {"callerServiceAccount", "parse", "export", "state"}, stage_id)
        if resources["state"] != "blocked-pending-worker-url":
            raise InfrastructureActionsError("cloud-tasks prerequisite state must be blocked-pending-worker-url")
        _nonempty(resources["callerServiceAccount"], "cloud-tasks callerServiceAccount")
        for name in ("parse", "export"):
            _validate_cloud_task_queue(resources[name], name)
        return [action("record-cloud-tasks-prerequisite", f"record-{name}", {"queue": resources[name], "state": resources["state"]}, {"state": "blocked-pending-worker-url", "mutationAuthorized": False}, {"type": "cloud-tasks-prerequisite", "queue": name}) for name in ("parse", "export")]
    if stage_id == "post-bootstrap-evidence":
        if not isinstance(resources, list) or not resources:
            raise InfrastructureActionsError("post-bootstrap-evidence resources must be a non-empty array")
        paths: list[str] = []
        for index, entry in enumerate(resources):
            _require_keys(entry, {"path", "resolutionPhase", "reason"}, f"post-bootstrap evidence {index}")
            for field in ("path", "resolutionPhase", "reason"):
                _nonempty(entry[field], f"post-bootstrap evidence {field}")
            paths.append(entry["path"])
        if len(paths) != len(set(paths)):
            raise InfrastructureActionsError("post-bootstrap evidence paths must not contain duplicates")
        return [action("collect-resource-evidence", f"collect-{index + 1:02d}", {"path": entry["path"]}, {"readOnly": True}, {"type": "resource-evidence", "path": entry["path"]}) for index, entry in enumerate(resources)]
    raise InfrastructureActionsError(f"unknown stage {stage_id}")


def _validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("schemaVersion") != PLAN_SCHEMA or plan.get("status") != "ready-for-infrastructure-approval":
        raise InfrastructureActionsError("plan schema or status is not supported")
    for field in ("projectId", "billingAccount", "region", "approvalReference"):
        _nonempty(plan.get(field), f"plan {field}")
    if _production_like(plan["projectId"]):
        raise InfrastructureActionsError("plan projectId must be staging-only")
    source = plan.get("sourceEvidence")
    if not isinstance(source, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commitSha"))):
        raise InfrastructureActionsError("plan sourceEvidence commitSha is invalid")
    stages = plan.get("stages")
    if not isinstance(stages, list) or len(stages) != len(STAGES):
        raise InfrastructureActionsError("plan must contain all canonical stages")
    expected = [item[0] for item in STAGES]
    ids = [stage.get("id") if isinstance(stage, dict) else None for stage in stages]
    if ids != expected or len(ids) != len(set(ids)):
        raise InfrastructureActionsError("plan stages are missing, duplicate, unknown, or out of order")
    prior: set[str] = set()
    for stage in stages:
        _require_keys(stage, {"id", "title", "intent", "dependsOn", "resources", "acceptanceEvidence", "rollbackBoundary", "mutationApprovalRequired"}, f"stage {stage.get('id')}")
        if stage["mutationApprovalRequired"] is not True:
            raise InfrastructureActionsError(f"stage {stage['id']} mutationApprovalRequired must be true")
        dependencies = stage["dependsOn"]
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            raise InfrastructureActionsError(f"stage {stage['id']} dependencies are invalid")
        if any(item not in prior for item in dependencies):
            raise InfrastructureActionsError(f"stage {stage['id']} depends on a missing or later stage")
        _reject_production_resources(stage["resources"], f"stage {stage['id']}.resources")
        _stage_actions(stage, dict(STAGES)[stage["id"]], [])
        prior.add(stage["id"])
    project_resources = stages[0]["resources"]
    if project_resources["projectId"] != plan["projectId"] or project_resources["billingAccount"] != plan["billingAccount"]:
        raise InfrastructureActionsError("project-billing resources do not match plan project or billing")
    forbidden = project_resources["forbiddenProjectIds"]
    if not isinstance(forbidden, list) or not forbidden or any(not isinstance(item, str) or not item.strip() for item in forbidden) or len(forbidden) != len(set(forbidden)) or plan["projectId"] in forbidden:
        raise InfrastructureActionsError("project-billing forbiddenProjectIds are invalid")
    firebase_resources = stages[2]["resources"]
    if firebase_resources["projectId"] != plan["projectId"]:
        raise InfrastructureActionsError("firebase-foundation projectId does not match approved project")
    evidence = stages[-1]["resources"]
    if plan.get("postBootstrapRequiredValues") != evidence:
        raise InfrastructureActionsError("post-bootstrap evidence does not match required values")
    return stages


def _validate_approval_result(plan: dict[str, Any], result: dict[str, Any], digest: str) -> None:
    required = {"schemaVersion", "status", "planSha256", "commitSha", "projectId", "billingAccount", "approvedStageIds", "maximumMonthlyBudgetKrw", "cloudMutationApproved", "requireCloudMutation", "deploymentApproved", "rollbackReviewed", "mutationCommands"}
    _require_keys(result, required, "approval result")
    if result["schemaVersion"] != APPROVAL_RESULT_SCHEMA or result["status"] not in {"awaiting-cloud-mutation-approval", "cloud-mutation-approved", "ready-for-cloud-mutation"}:
        raise InfrastructureActionsError("approval result status is not supported")
    if not re.fullmatch(r"[0-9a-f]{64}", str(result["planSha256"])) or result["planSha256"] != digest:
        raise InfrastructureActionsError("approval result plan digest is invalid")
    source = plan["sourceEvidence"]
    if result["commitSha"] != source["commitSha"] or result["projectId"] != plan["projectId"] or result["billingAccount"] != plan["billingAccount"]:
        raise InfrastructureActionsError("approval result does not match plan evidence")
    budget = next(stage["resources"]["amount"] for stage in plan["stages"] if stage["id"] == "budget-guardrails")
    status_is_ready = result["status"] in {"cloud-mutation-approved", "ready-for-cloud-mutation"}
    if result["cloudMutationApproved"] is not status_is_ready:
        raise InfrastructureActionsError("approval result status does not match cloud mutation approval")
    if not isinstance(result["requireCloudMutation"], bool) or (result["requireCloudMutation"] and not status_is_ready):
        raise InfrastructureActionsError("approval result cloud mutation requirement is invalid")
    if result["approvedStageIds"] != [item[0] for item in STAGES] or result["maximumMonthlyBudgetKrw"] != budget or result["rollbackReviewed"] is not True or result["deploymentApproved"] is not False or result["mutationCommands"] != []:
        raise InfrastructureActionsError("approval result does not preserve approval boundaries")


def _validate_actions(actions: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for action in actions:
        if action["id"] in ids:
            raise InfrastructureActionsError("duplicate action ID")
        if action["classification"] != dict(STAGES).get(action["stageId"]):
            raise InfrastructureActionsError("stage/action classification mismatch")
        if action["classification"] in {"observation-only", "blocked-deferred", "irreversible-manual-decision", "deferred-resource-specific"} and action["desiredState"].get("mutationAuthorized") is True:
            raise InfrastructureActionsError("action disposition implies forbidden mutation")
        if any(dependency not in ids for dependency in action["dependencies"]):
            raise InfrastructureActionsError("action dependency references a missing or later action")
        ids.add(action["id"])


def render_markdown(execution: dict[str, Any]) -> str:
    _reject_unsafe(execution, "execution")
    if execution.get("schemaVersion") != EXECUTION_SCHEMA:
        raise InfrastructureActionsError("execution schema is not supported")
    lines = ["# rhwp Staging Infrastructure Execution Manifest", "", "> This manifest does not authorize deployment and contains no executable commands.", "", f"- Status: `{_md(execution.get('status'))}`", f"- Project ID: `{_md(execution.get('projectId'))}`", "- Deployment authorized: `False`", "", "## Ordered actions", "", "| ID | Classification | Kind |", "|---|---|---|"]
    for action in execution.get("actions", []):
        lines.append(f"| `{_md(action.get('id'))}` | `{_md(action.get('classification'))}` | `{_md(action.get('kind'))}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate safe structured staging infrastructure actions")
    parser.add_argument("--plan", type=Path, required=True); parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True); parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    json_temp, markdown_temp = (args.json_output.with_name(args.json_output.name + ".tmp"), args.markdown_output.with_name(args.markdown_output.name + ".tmp"))
    backups: dict[Path, bytes | None] = {}; published: list[Path] = []; temp_written: list[Path] = []
    try:
        _validate_output_paths(args.plan, args.approval, args.json_output, args.markdown_output)
        plan, plan_bytes = load_json_with_bytes(args.plan, "infrastructure plan")
        approval, _ = load_json_with_bytes(args.approval, "infrastructure approval")
        if approval.get("schemaVersion") == "rhwp.staging-infrastructure-approval/v1":
            approval = validate_infrastructure_approval(plan, plan_bytes, approval, require_cloud_mutation=False)
        execution = build_execution_manifest(plan, approval, plan_bytes=plan_bytes); markdown = render_markdown(execution)
        for path in (args.json_output, args.markdown_output): path.parent.mkdir(parents=True, exist_ok=True)
        backups = {path: path.read_bytes() if path.exists() else None for path in (args.json_output, args.markdown_output)}
        json_temp.write_text(json.dumps(execution, ensure_ascii=False, indent=2) + "\n"); temp_written.append(json_temp)
        markdown_temp.write_text(markdown); temp_written.append(markdown_temp)
        json_temp.replace(args.json_output); published.append(args.json_output); markdown_temp.replace(args.markdown_output); published.append(args.markdown_output)
    except (InfrastructureActionsError, InfrastructureApprovalError, OSError) as error:
        for path in temp_written:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        for path in published:
            try:
                if backups[path] is None: path.unlink(missing_ok=True)
                else: path.write_bytes(backups[path])
            except OSError: pass
        print(f"staging infrastructure actions failed: {error}", file=sys.stderr); return 1
    print(json.dumps({"status": execution["status"], "projectId": execution["projectId"], "jsonOutput": str(args.json_output), "markdownOutput": str(args.markdown_output), "mutationCommands": []})); return 0


def _validate_output_paths(plan: Path, approval: Path, json_output: Path, markdown_output: Path) -> None:
    temp_paths = (json_output.with_name(json_output.name + ".tmp"), markdown_output.with_name(markdown_output.name + ".tmp"))
    all_paths = (plan, approval, json_output, markdown_output, *temp_paths)
    paths = [item.resolve(strict=False) for item in all_paths]
    if any(item.is_symlink() for item in all_paths) or len(set(paths)) != len(paths):
        raise InfrastructureActionsError("input and output paths must not overlap or alias")
    for index, left in enumerate(paths):
        if any(left in right.parents or right in left.parents for right in paths[index + 1:]):
            raise InfrastructureActionsError("input, output, and temporary paths must not overlap")
    if any(path.exists() for path in temp_paths):
        raise InfrastructureActionsError("temporary output path already exists")
    if any(path.exists() and path.is_dir() for path in (json_output, markdown_output)):
        raise InfrastructureActionsError("output path must not be a directory")


def _reject_unsafe(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child = f"{path}.{key}"
            if any(marker in normalized for marker in SENSITIVE) and not (
                normalized == "secretvaluesincluded" and item is False
            ):
                raise InfrastructureActionsError(f"sensitive key is not allowed at {child}")
            if normalized in EXECUTABLE: raise InfrastructureActionsError(f"executable field is not allowed at {child}")
            _reject_unsafe(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value): _reject_unsafe(item, f"{path}[{index}]")


def _require_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict): raise InfrastructureActionsError(f"{label} must be an object")
    if set(value) != expected: raise InfrastructureActionsError(f"{label} has missing or unknown required fields")


def _nonempty(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip(): raise InfrastructureActionsError(f"{label} must be a non-empty string")


def _production_like(value: str) -> bool:
    lowered = value.lower()
    return "production" in lowered or bool(re.search(r"(^|[-_])prod($|[-_])", lowered)) or "staging" not in lowered


def _reject_production_resources(value: Any, path: str, *, forbidden: bool = False) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_production_resources(item, f"{path}.{key}", forbidden=key == "forbiddenProjectIds")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_production_resources(item, f"{path}[{index}]", forbidden=forbidden)
    elif isinstance(value, str) and not forbidden and _production_resource_like(value):
        raise InfrastructureActionsError(f"production-like resource is not allowed at {path}")


def _production_resource_like(value: str) -> bool:
    lowered = value.lower()
    return "production" in lowered or bool(re.search(r"(^|[-_])prod($|[-_])", lowered))


def _require_exact_plan_bytes(plan: dict[str, Any], plan_bytes: bytes | None) -> str:
    if not isinstance(plan_bytes, bytes):
        raise InfrastructureActionsError("trusted exact plan bytes are required")
    try:
        parsed = json.loads(plan_bytes.decode("utf-8"), object_pairs_hook=_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise InfrastructureActionsError("plan bytes must be strict UTF-8 JSON") from error
    if not _same_json_structure(plan, parsed):
        raise InfrastructureActionsError("plan object does not match exact plan bytes")
    return hashlib.sha256(plan_bytes).hexdigest()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _same_json_structure(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_same_json_structure(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json_structure(value, right[index]) for index, value in enumerate(left))
    return left == right


def _validate_cloud_run_service(value: Any, name: str) -> None:
    _require_keys(value, {"name", "serviceAccount", "ingress", "runtime", "state"}, f"cloud-run {name}")
    for field in ("name", "serviceAccount", "ingress"):
        _nonempty(value[field], f"cloud-run {name}.{field}")
    if value["state"] != "blocked-pending-image-digest":
        raise InfrastructureActionsError("cloud-run prerequisite state must be blocked-pending-image-digest")
    _require_keys(value["runtime"], {"containerConcurrency", "timeoutSeconds", "cpu", "memory", "minScale", "maxScale"}, f"cloud-run {name}.runtime")
    for field in ("containerConcurrency", "timeoutSeconds", "minScale", "maxScale"):
        _positive_number(value["runtime"][field], f"cloud-run {name}.runtime.{field}", allow_zero=field == "minScale")
    for field in ("cpu", "memory"):
        _nonempty(value["runtime"][field], f"cloud-run {name}.runtime.{field}")


def _validate_cloud_task_queue(value: Any, name: str) -> None:
    _require_keys(value, {"name", "location", "targetUrl", "dispatchDeadlineSeconds", "retry", "rateLimits"}, f"cloud-tasks {name}")
    for field in ("name", "location", "targetUrl"):
        _nonempty(value[field], f"cloud-tasks {name}.{field}")
    if isinstance(value["dispatchDeadlineSeconds"], bool) or not isinstance(value["dispatchDeadlineSeconds"], int) or value["dispatchDeadlineSeconds"] <= 0:
        raise InfrastructureActionsError("cloud-tasks dispatch deadline must be a positive integer")
    _require_keys(value["retry"], {"maxAttempts", "minBackoffSeconds", "maxBackoffSeconds", "maxDoublings"}, f"cloud-tasks {name}.retry")
    _require_keys(value["rateLimits"], {"maxConcurrentDispatches", "maxDispatchesPerSecond"}, f"cloud-tasks {name}.rateLimits")
    for field, item in value["retry"].items():
        _positive_number(item, f"cloud-tasks {name}.retry.{field}")
    for field, item in value["rateLimits"].items():
        _positive_number(item, f"cloud-tasks {name}.rateLimits.{field}")


def _positive_number(value: Any, label: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < (0 if allow_zero else 0) or (not allow_zero and value == 0):
        raise InfrastructureActionsError(f"{label} must be a positive number")


def _nonempty_strings(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise InfrastructureActionsError(f"{label} must be a non-empty array of strings")
    if len(value) != len(set(value)):
        raise InfrastructureActionsError(f"{label} must not contain duplicates")


def _md(value: Any) -> str:
    return re.sub(r"[\x00-\x1f\x7f\x85\u2028\u2029]", " ", "" if value is None else str(value)).replace("|", "\\|").replace("`", "'")


if __name__ == "__main__":
    raise SystemExit(main())
