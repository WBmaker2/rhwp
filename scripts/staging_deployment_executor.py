#!/usr/bin/env python3
"""Execute an approved staging deployment through a bounded action contract.

The executor is deliberately independent from GitHub and Cloud credentials.  It
re-validates the same-run prepared bundle, derives a canonical list of actions,
and defaults to a cloud-free plan.  The optional apply path accepts only an
injected observer/runner in tests; the production workflow must add OIDC and
read-before/write/read-after wiring only after its provider and IAM diff have
been read back exactly.
"""
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

from scripts.staging_deployment_approval_record import load_json_with_bytes
from scripts.staging_deployment_prepare import prepare_bundle
from scripts.staging_deployment_runtime_contract import (
    RuntimeContractError,
    cloud_run_deploy_argv,
)


class DeploymentExecutionError(RuntimeError):
    """Raised when the bounded deployment contract cannot be satisfied."""


PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SA_RE = re.compile(r"^[a-z][a-z0-9-]{5,28}[a-z0-9]@([a-z][a-z0-9-]{4,28}[a-z0-9])\.iam\.gserviceaccount\.com$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
SECRET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,254}$")
QUEUE_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
IMAGE_RE = re.compile(
    r"^([a-z0-9-]+)-docker\.pkg\.dev/([a-z][a-z0-9-]{4,28}[a-z0-9])/"
    r"rhwp-staging/(collaboration|document-api|document-worker)$"
)
RAW_FIREBASE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
REGION = "asia-northeast3"
RUNTIME_KEYS = frozenset({"containerConcurrency", "cpu", "maxScale", "memory", "minScale", "timeoutSeconds"})
RUN_KEYS = ("collaboration", "documentApi", "documentWorker")
RUN_NAMES = {
    "collaboration": "rhwp-collaboration-staging",
    "documentApi": "rhwp-document-api-staging",
    "documentWorker": "rhwp-document-worker-staging",
}
RUN_REPOSITORIES = {
    "collaboration": "collaboration",
    "documentApi": "document-api",
    "documentWorker": "document-worker",
}
RUN_SERVICE_ACCOUNTS = {
    "collaboration": "rhwp-collaboration-staging",
    "documentApi": "rhwp-document-api-staging",
    "documentWorker": "rhwp-document-worker-staging",
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentExecutionError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentExecutionError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DeploymentExecutionError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeploymentExecutionError(f"{label} must be a non-negative integer")
    return value


def _reject_sensitive_values(value: Any, path: str = "bundle") -> None:
    """Reject credential-shaped values even when a key name looks harmless."""
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"apikey", "accesskey", "secret", "token"} or any(marker in normalized for marker in ("accesstoken", "idtoken", "authorization", "privatekey", "password", "credential", "internalflushtoken")):
                raise DeploymentExecutionError(f"sensitive key is not allowed at {child}")
            _reject_sensitive_values(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_values(item, f"{path}[{index}]")
    elif isinstance(value, str) and (RAW_FIREBASE_KEY_RE.fullmatch(value) or value.startswith("Bearer ") or "-----BEGIN PRIVATE KEY-----" in value):
        raise DeploymentExecutionError(f"sensitive value is not allowed at {path}")


def _validate_project(prepared: dict[str, Any]) -> str:
    project = _mapping(prepared.get("project"), "prepared project")
    project_id = _string(project.get("id"), "prepared project.id")
    if not PROJECT_RE.fullmatch(project_id) or "staging" not in project_id or "prod" in project_id:
        raise DeploymentExecutionError("deployment executor is restricted to a staging project")
    if _string(project.get("region"), "prepared project.region") != REGION:
        raise DeploymentExecutionError("deployment executor region is not the staging region")
    return project_id


def _validate_run(prepared: dict[str, Any], project_id: str) -> dict[str, dict[str, Any]]:
    cloud_run = _mapping(prepared.get("cloudRun"), "prepared cloudRun")
    if tuple(cloud_run) != RUN_KEYS:
        raise DeploymentExecutionError("cloudRun keys are not in canonical order")
    for key in RUN_KEYS:
        item = _mapping(cloud_run.get(key), f"cloudRun.{key}")
        if set(item) != {"digest", "image", "ingress", "name", "reachability", "runtime", "serviceAccount"}:
            raise DeploymentExecutionError(f"cloudRun.{key} keys are not exact")
        if item["name"] != RUN_NAMES[key] or item["ingress"] not in {"all", "internal"}:
            raise DeploymentExecutionError(f"cloudRun.{key} service identity is invalid")
        expected_repo = f"{REGION}-docker.pkg.dev/{project_id}/rhwp-staging/{RUN_REPOSITORIES[key]}"
        if item["image"] != expected_repo or not SHA_RE.fullmatch(str(item["digest"])):
            raise DeploymentExecutionError(f"cloudRun.{key} must use the canonical immutable digest")
        match = IMAGE_RE.fullmatch(item["image"])
        if not match or match.group(1) != REGION or match.group(2) != project_id or match.group(3) != RUN_REPOSITORIES[key]:
            raise DeploymentExecutionError(f"cloudRun.{key} image repository is invalid")
        sa = _string(item["serviceAccount"], f"cloudRun.{key}.serviceAccount")
        expected_sa = f"{RUN_SERVICE_ACCOUNTS[key]}@{project_id}.iam.gserviceaccount.com"
        if not SA_RE.fullmatch(sa) or sa != expected_sa:
            raise DeploymentExecutionError(f"cloudRun.{key}.serviceAccount is not canonical")
        runtime = _mapping(item["runtime"], f"cloudRun.{key}.runtime")
        if set(runtime) != RUNTIME_KEYS:
            raise DeploymentExecutionError(f"cloudRun.{key}.runtime keys are not exact")
        _positive_int(runtime["containerConcurrency"], f"cloudRun.{key}.runtime.containerConcurrency")
        _positive_int(runtime["timeoutSeconds"], f"cloudRun.{key}.runtime.timeoutSeconds")
        _nonnegative_int(runtime["maxScale"], f"cloudRun.{key}.runtime.maxScale")
        _nonnegative_int(runtime["minScale"], f"cloudRun.{key}.runtime.minScale")
        if runtime["minScale"] > runtime["maxScale"] or runtime["maxScale"] > 100:
            raise DeploymentExecutionError(f"cloudRun.{key}.runtime scaling bounds are invalid")
        if not re.fullmatch(r"[0-9]+", str(runtime["cpu"])) or not re.fullmatch(r"[0-9]+(?:Mi|Gi)", str(runtime["memory"])):
            raise DeploymentExecutionError(f"cloudRun.{key}.runtime resources are invalid")
    return cloud_run


def _validate_tasks(prepared: dict[str, Any], project_id: str) -> dict[str, Any]:
    tasks = _mapping(prepared.get("cloudTasks"), "prepared cloudTasks")
    if set(tasks) != {"callerServiceAccount", "export", "parse"}:
        raise DeploymentExecutionError("cloudTasks keys are not exact")
    caller = _string(tasks["callerServiceAccount"], "cloudTasks.callerServiceAccount")
    if not caller.endswith(f"@{project_id}.iam.gserviceaccount.com"):
        raise DeploymentExecutionError("cloudTasks caller service account is cross-project")
    for key, suffix in (("parse", "/run/parse"), ("export", "/run/export")):
        queue = _mapping(tasks[key], f"cloudTasks.{key}")
        expected_keys = {"dispatchDeadlineSeconds", "location", "name", "rateLimits", "retry", "targetUrl"}
        if set(queue) != expected_keys:
            raise DeploymentExecutionError(f"cloudTasks.{key} keys are not exact")
        if queue["location"] != REGION or not QUEUE_RE.fullmatch(str(queue["name"])):
            raise DeploymentExecutionError(f"cloudTasks.{key} queue identity is invalid")
        target = _string(queue["targetUrl"], f"cloudTasks.{key}.targetUrl")
        if not target.startswith("https://") or not target.endswith(suffix):
            raise DeploymentExecutionError(f"cloudTasks.{key}.targetUrl is invalid")
        if _positive_int(queue["dispatchDeadlineSeconds"], f"cloudTasks.{key}.dispatchDeadlineSeconds") != 900:
            raise DeploymentExecutionError("Cloud Tasks dispatch deadline must be 900 seconds")
        limits = _mapping(queue["rateLimits"], f"cloudTasks.{key}.rateLimits")
        if limits != {"maxConcurrentDispatches": 1, "maxDispatchesPerSecond": 1}:
            raise DeploymentExecutionError(f"cloudTasks.{key}.rateLimits are not the approved contract")
        retry = _mapping(queue["retry"], f"cloudTasks.{key}.retry")
        if retry != {"maxAttempts": 5, "maxBackoffSeconds": 300, "maxDoublings": 5, "minBackoffSeconds": 10}:
            raise DeploymentExecutionError(f"cloudTasks.{key}.retry is not the approved contract")
    return tasks


def _expected_iam(prepared: dict[str, Any], packet: dict[str, Any], project_id: str) -> list[tuple[str, str, str, str, str]]:
    bucket = _string(_mapping(prepared.get("firebase"), "prepared firebase").get("storageBucket"), "firebase.storageBucket")
    if not BUCKET_RE.fullmatch(bucket):
        raise DeploymentExecutionError("storage bucket identifier is invalid")
    secret = _string(_mapping(packet.get("secrets"), "packet secrets")["collaborationInternal"]["name"], "secret name")
    if not SECRET_RE.fullmatch(secret):
        raise DeploymentExecutionError("secret identifier is invalid")
    cloud_run = _mapping(prepared["cloudRun"], "prepared cloudRun")
    tasks = _mapping(prepared["cloudTasks"], "prepared cloudTasks")
    collab = cloud_run["collaboration"]["serviceAccount"]
    api = cloud_run["documentApi"]["serviceAccount"]
    worker = cloud_run["documentWorker"]["serviceAccount"]
    task_sa = tasks["callerServiceAccount"]
    return [
        (f"serviceAccount:{collab}", "roles/datastore.user", "project", "missing", "grant-after-approval"),
        (f"serviceAccount:{collab}", "roles/storage.objectAdmin", f"bucket:{bucket}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{collab}", "roles/secretmanager.secretAccessor", f"secret:{secret}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{api}", "roles/datastore.user", "project", "missing", "grant-after-approval"),
        (f"serviceAccount:{api}", "roles/storage.objectViewer", f"bucket:{bucket}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{api}", "roles/cloudtasks.enqueuer", f"queues:{tasks['parse']['name']},{tasks['export']['name']}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{api}", "roles/iam.serviceAccountUser", f"serviceAccount:{task_sa}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{api}", "roles/secretmanager.secretAccessor", f"secret:{secret}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{worker}", "roles/datastore.user", "project", "missing", "grant-after-approval"),
        (f"serviceAccount:{worker}", "roles/storage.objectAdmin", f"bucket:{bucket}", "not-observed", "verify-before-grant"),
        ("allUsers", "roles/run.invoker", f"cloudRun:{cloud_run['collaboration']['name']}", "not-observed", "verify-before-grant"),
        ("allUsers", "roles/run.invoker", f"cloudRun:{cloud_run['documentApi']['name']}", "not-observed", "verify-before-grant"),
        (f"serviceAccount:{task_sa}", "roles/run.invoker", f"cloudRun:{cloud_run['documentWorker']['name']}", "not-observed", "verify-before-grant"),
    ]


def _validate_iam(prepared: dict[str, Any], packet: dict[str, Any], project_id: str) -> list[dict[str, str]]:
    values = prepared.get("iamDiff")
    if not isinstance(values, list):
        raise DeploymentExecutionError("prepared iamDiff must be an array")
    expected = _expected_iam(prepared, packet, project_id)
    if len(values) != len(expected):
        raise DeploymentExecutionError("prepared iamDiff length is not the approved canonical length")
    result: list[dict[str, str]] = []
    for index, (entry, want) in enumerate(zip(values, expected, strict=True), 1):
        item = _mapping(entry, f"iamDiff[{index}]")
        if set(item) != {"plannedAction", "principal", "resource", "role", "state"}:
            raise DeploymentExecutionError(f"iamDiff[{index}] keys are not exact")
        actual = tuple(_string(item[key], f"iamDiff[{index}].{key}") for key in ("principal", "role", "resource", "state", "plannedAction"))
        if actual != want:
            raise DeploymentExecutionError(f"iamDiff[{index}] is outside the canonical deployment subset")
        result.append({"principal": actual[0], "role": actual[1], "resource": actual[2], "state": actual[3], "plannedAction": actual[4]})
    return result


def validate_prepared_bundle(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Revalidate the same-run artifact and return safe metadata plus actions."""
    prepared, _ = load_json_with_bytes(root / "deployment-input.json", "deployment input")
    packet, packet_raw = load_json_with_bytes(root / "staging-approval-packet.json", "deployment packet")
    review, review_raw = load_json_with_bytes(root / "deployment-review.approved.json", "deployment review")
    acceptance, acceptance_raw = load_json_with_bytes(root / "acceptance-evidence.json", "acceptance evidence")
    rollback, rollback_raw = load_json_with_bytes(root / "rollback-evidence.json", "rollback evidence")
    record, record_raw = load_json_with_bytes(root / "staging-deployment-approval-record.json", "deployment approval record")
    for label, value in (("deployment input", prepared), ("packet", packet), ("review", review), ("acceptance", acceptance), ("rollback", rollback), ("record", record)):
        _reject_sensitive_values(value, label)
    project_id = _validate_project(prepared)
    _validate_run(prepared, project_id)
    _validate_tasks(prepared, project_id)
    iam = _validate_iam(prepared, packet, project_id)
    packet_secret = _mapping(packet.get("secrets"), "packet secrets").get("collaborationInternal")
    packet_secret_name = _string(_mapping(packet_secret, "collaborationInternal secret").get("name"), "packet secret name")
    if prepared.get("secretName") != packet_secret_name:
        raise DeploymentExecutionError("prepared Secret Manager name does not match the packet")
    if prepared.get("mutationCommands") != [] or record.get("mutationCommands") != []:
        raise DeploymentExecutionError("deployment approval contains mutation commands")
    if prepared.get("approval", {}).get("deploymentApproved") is not True or prepared.get("approval", {}).get("cloudMutationApproved") is not True:
        raise DeploymentExecutionError("deployment approval flags are not true")
    recomputed, exact = prepare_bundle(
        packet_path=root / "staging-approval-packet.json",
        review_path=root / "deployment-review.approved.json",
        acceptance_path=root / "acceptance-evidence.json",
        rollback_path=root / "rollback-evidence.json",
        record_path=root / "staging-deployment-approval-record.json",
        expected_source_commit=_string(prepared.get("sourceCommitSha"), "deployment input.sourceCommitSha"),
        expected_workflow_run_id=_positive_int(prepared.get("packetWorkflowRunId"), "deployment input.packetWorkflowRunId"),
        expected_workflow_run_attempt=_positive_int(prepared.get("packetWorkflowRunAttempt"), "deployment input.packetWorkflowRunAttempt"),
        expected_artifact_name=_string(prepared.get("packetArtifactName"), "deployment input.packetArtifactName"),
        expected_artifact_digest=_string(prepared.get("packetArtifactDigest"), "deployment input.packetArtifactDigest"),
        expected_packet_sha256=_string(prepared.get("packetSha256"), "deployment input.packetSha256"),
    )
    if recomputed != prepared:
        raise DeploymentExecutionError("same-run deployment input does not match recomputed approval metadata")
    raw_files = {
        "staging-approval-packet.json": packet_raw,
        "deployment-review.approved.json": review_raw,
        "acceptance-evidence.json": acceptance_raw,
        "rollback-evidence.json": rollback_raw,
        "staging-deployment-approval-record.json": record_raw,
    }
    if any(exact[name] != raw for name, raw in raw_files.items()):
        raise DeploymentExecutionError("same-run approval bytes changed during validation")
    actions: list[dict[str, Any]] = []
    cloud_run = prepared["cloudRun"]
    for key in RUN_KEYS:
        actions.append({"actionId": f"cloud-run-{key}", "resourceKind": "cloud-run-service", "operation": "ensure-service", "resource": cloud_run[key]})
    for key in ("parse", "export"):
        actions.append({"actionId": f"cloud-tasks-{key}", "resourceKind": "cloud-tasks-queue", "operation": "ensure-queue", "resource": prepared["cloudTasks"][key]})
    for index, item in enumerate(iam, 1):
        target = item["resource"]
        if target.startswith("queues:"):
            for queue in target[7:].split(","):
                split_item = {**item, "resource": f"queue:{queue}"}
                actions.append({"actionId": f"iam-binding-{index:02d}-{queue}", "resourceKind": "iam-binding", "operation": "ensure-binding", "resource": split_item})
        else:
            actions.append({"actionId": f"iam-binding-{index:02d}", "resourceKind": "iam-binding", "operation": "ensure-binding", "resource": item})
    return prepared, actions


def _validate_observation(action: dict[str, Any], value: Any) -> tuple[str, str | None]:
    required = {"state", "resourceKind", "matchesDesired"}
    allowed = required | ({"url"} if action["resourceKind"] == "cloud-run-service" else set())
    if not isinstance(value, dict) or not required.issubset(value) or not set(value).issubset(allowed):
        raise DeploymentExecutionError("observer result must use the exact structured contract")
    if value["resourceKind"] != action["resourceKind"] or value["state"] not in {"missing", "present", "incompatible"} or not isinstance(value["matchesDesired"], bool):
        raise DeploymentExecutionError("observer result is incompatible with the action")
    url = value.get("url")
    if url is not None and (not isinstance(url, str) or not url.startswith("https://") or any(char in url for char in ("\n", "\r", " "))):
        raise DeploymentExecutionError("observer result contains an invalid service URL")
    if value["state"] == "present" and value["matchesDesired"] is not True:
        return "incompatible", url
    if value["state"] == "missing" and value["matchesDesired"] is not False:
        raise DeploymentExecutionError("missing observer result cannot assert desired state")
    return value["state"], url


def _fixed_argv(
    project_id: str,
    action: dict[str, Any],
    prepared: dict[str, Any] | None = None,
    observed_urls: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Build an allowlisted argv tuple; never use a shell or free-form command."""
    if not PROJECT_RE.fullmatch(project_id):
        raise DeploymentExecutionError("invalid project id for executor argv")
    kind = action["resourceKind"]
    resource = _mapping(action.get("resource"), f"{action.get('actionId')}.resource")
    if kind == "cloud-run-service":
        if prepared is None:
            raise DeploymentExecutionError("Cloud Run argv requires the prepared runtime contract")
        try:
            return cloud_run_deploy_argv(project_id, resource, prepared, observed_urls or {}, region=REGION)
        except RuntimeContractError as error:
            raise DeploymentExecutionError(str(error)) from error
    if kind == "cloud-tasks-queue":
        return (
            "gcloud", "tasks", "queues", "create", resource["name"], f"--location={REGION}", f"--project={project_id}",
            "--max-dispatches-per-second=1", "--max-concurrent-dispatches=1", "--max-attempts=5",
            "--max-backoff=300s", "--max-doublings=5", "--min-backoff=10s", "--quiet",
        )
    if kind == "iam-binding":
        principal, role, target = resource["principal"], resource["role"], resource["resource"]
        if target == "project":
            return ("gcloud", "projects", "add-iam-policy-binding", project_id, f"--member={principal}", f"--role={role}", "--quiet")
        if target.startswith("bucket:"):
            return ("gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{target[7:]}", f"--member={principal}", f"--role={role}", "--quiet")
        if target.startswith("secret:"):
            return ("gcloud", "secrets", "add-iam-policy-binding", target[7:], f"--member={principal}", f"--role={role}", f"--project={project_id}", "--quiet")
        if target.startswith("serviceAccount:"):
            return ("gcloud", "iam", "service-accounts", "add-iam-policy-binding", target[14:], f"--member={principal}", f"--role={role}", f"--project={project_id}", "--quiet")
        if target.startswith("cloudRun:"):
            return ("gcloud", "run", "services", "add-iam-policy-binding", target[9:], f"--member={principal}", f"--role={role}", f"--region={REGION}", f"--project={project_id}", "--quiet")
        if target.startswith("queue:"):
            queue = target[6:]
            return ("gcloud", "tasks", "queues", "add-iam-policy-binding", queue, f"--member={principal}", f"--role={role}", f"--location={REGION}", f"--project={project_id}", "--quiet")
    raise DeploymentExecutionError(f"unsupported action kind or target: {kind}")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    system_aliases = {Path("/var"), Path("/tmp")}
    if any(component.is_symlink() and component not in system_aliases for component in (path, *path.parents)):
        raise DeploymentExecutionError("evidence path cannot use symlinks")
    if path.exists() and (not path.is_file() or stat.S_ISLNK(path.stat().st_mode)):
        raise DeploymentExecutionError("evidence path must be a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise DeploymentExecutionError("could not publish deployment evidence") from error


def execute_deployment(
    prepared: dict[str, Any], actions: list[dict[str, Any]], plan_output: Path, post_output: Path, *,
    apply: bool = False, observer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    runner: Callable[[tuple[str, ...]], str] | None = None,
    observer_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    if plan_output.resolve(strict=False) == post_output.resolve(strict=False):
        raise DeploymentExecutionError("plan and post evidence must be separate files")
    project_id = _validate_project(prepared)
    plan = {
        "schemaVersion": "rhwp.staging-deployment-plan-evidence/v1",
        "mode": "apply" if apply else "dry-run",
        "status": "planned",
        "approvalReference": prepared["approvalReference"],
        "sourceCommitSha": prepared["sourceCommitSha"],
        "packetWorkflowRunId": prepared["packetWorkflowRunId"],
        "packetWorkflowRunAttempt": prepared["packetWorkflowRunAttempt"],
        "packetSha256": prepared["packetSha256"],
        "projectId": project_id,
        "actions": [{"actionId": item["actionId"], "resourceKind": item["resourceKind"], "operation": item["operation"]} for item in actions],
        "containsCredentials": False,
        "containsSecretValues": False,
        "mutationCommands": [],
    }
    if not apply:
        _atomic_json(plan_output, plan)
        _atomic_json(post_output, {**plan, "schemaVersion": "rhwp.staging-deployment-observed-evidence/v1", "status": "dry-run-complete", "observed": []})
        return {"mode": "dry-run", "status": "dry-run-complete", "executedActionIds": []}
    if observer is None:
        raise DeploymentExecutionError("apply requires a fixed read-only observer")
    invoke = runner or _run_fixed_argv
    observed_urls = observer_context if observer_context is not None else {}
    _atomic_json(plan_output, plan)
    observed: list[dict[str, str]] = []
    for action in actions:
        try:
            before, before_url = _validate_observation(action, observer(action))
            if before_url:
                observed_urls[action["actionId"]] = before_url
        except Exception as error:
            _failure(post_output, observed, action, "precondition-observation")
            raise DeploymentExecutionError(f"precondition observation failed for {action['actionId']}") from error
        if before == "incompatible":
            _failure(post_output, observed, action, "precondition-mismatch")
            raise DeploymentExecutionError(f"precondition mismatch for {action['actionId']}")
        if before == "present":
            observed.append({"actionId": action["actionId"], "status": "already-present-noop"})
            continue
        try:
            invoke(_fixed_argv(project_id, action, prepared, observed_urls))
        except Exception as error:
            _failure(post_output, observed, action, "write")
            raise DeploymentExecutionError(f"approved command failed for {action['actionId']}") from error
        try:
            after, after_url = _validate_observation(action, observer(action))
            if after_url:
                observed_urls[action["actionId"]] = after_url
        except Exception as error:
            _failure(post_output, observed, action, "postcondition-observation", write_returned_success=True)
            raise DeploymentExecutionError(f"postcondition observation failed for {action['actionId']}") from error
        if after != "present":
            _failure(post_output, observed, action, "postcondition-mismatch", write_returned_success=True)
            raise DeploymentExecutionError(f"postcondition mismatch for {action['actionId']}")
        observed.append({"actionId": action["actionId"], "status": "observed-after-apply"})
    _atomic_json(post_output, {**plan, "schemaVersion": "rhwp.staging-deployment-observed-evidence/v1", "status": "apply-complete", "observed": observed})
    return {"mode": "apply", "status": "apply-complete", "executedActionIds": [item["actionId"] for item in observed if item["status"] == "observed-after-apply"]}


def _failure(path: Path, observed: list[dict[str, str]], action: dict[str, Any], phase: str, *, write_returned_success: bool = False) -> None:
    _atomic_json(path, {
        "schemaVersion": "rhwp.staging-deployment-observed-evidence/v1",
        "mode": "apply",
        "status": "failed-first-error",
        "failurePhase": phase,
        "failedActionId": action["actionId"],
        "executedActionIds": [item["actionId"] for item in observed],
        "writeReturnedSuccess": write_returned_success,
        "containsCredentials": False,
        "containsSecretValues": False,
        "mutationCommands": [],
    })


def _run_fixed_argv(argv: tuple[str, ...]) -> str:
    completed = subprocess.run(list(argv), shell=False, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise DeploymentExecutionError("fixed executable returned non-zero")
    return "completed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and execute an approved staging deployment bundle")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--plan-evidence", type=Path, required=True)
    parser.add_argument("--post-evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        prepared, actions = validate_prepared_bundle(args.input_dir)
        from scripts.staging_deployment_observer import observe_fixed
        observed_urls: dict[str, str] = {}
        observer = (lambda action: observe_fixed(_validate_project(prepared), action, prepared=prepared, observed_urls=observed_urls)) if args.apply else None
        result = execute_deployment(prepared, actions, args.plan_evidence, args.post_evidence, apply=args.apply, observer=observer, observer_context=observed_urls)
    except (DeploymentExecutionError, OSError) as error:
        print(f"staging deployment executor failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"mode": result["mode"], "status": result["status"], "executedActionIds": result["executedActionIds"], "mutationCommands": []}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
