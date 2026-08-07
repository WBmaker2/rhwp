#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deploy/staging/staging-manifest.json"
Runner = Callable[..., subprocess.CompletedProcess[str]]

READ_ONLY_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("gcloud", "auth", "list"),
    ("gcloud", "config", "get-value"),
    ("gcloud", "projects", "describe"),
    ("gcloud", "billing", "projects", "describe"),
    ("gcloud", "services", "list"),
    ("gcloud", "run", "services", "list"),
    ("gcloud", "run", "services", "describe"),
    ("gcloud", "tasks", "queues", "list"),
    ("gcloud", "tasks", "queues", "describe"),
    ("gcloud", "secrets", "list"),
    ("gcloud", "secrets", "describe"),
    ("gcloud", "iam", "service-accounts", "list"),
    ("gcloud", "iam", "service-accounts", "describe"),
    ("gcloud", "projects", "get-iam-policy"),
    ("gcloud", "artifacts", "repositories", "list"),
    ("gcloud", "artifacts", "repositories", "describe"),
    ("firebase", "projects:list"),
)
MUTATING_TOKENS = {
    "add-iam-policy-binding",
    "create",
    "delete",
    "deploy",
    "disable",
    "enable",
    "remove-iam-policy-binding",
    "set-iam-policy",
    "update",
}
REQUIRED_APIS = {
    "artifactregistry.googleapis.com",
    "cloudtasks.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "firestore.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
}
DEPLOYMENT_STAGES = frozenset({"initial", "upgrade"})


class PreflightError(RuntimeError):
    pass


def is_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"\$\{[A-Z0-9_]+\}", value))


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise PreflightError(f"staging manifest not found: {path}") from error
    except json.JSONDecodeError as error:
        raise PreflightError(f"staging manifest is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise PreflightError("staging manifest root must be an object")
    validate_manifest(value)
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != "rhwp.staging/v1":
        raise PreflightError("schemaVersion must be rhwp.staging/v1")
    if manifest.get("environment") != "staging":
        raise PreflightError("environment must be staging")

    project = _mapping(manifest, "project")
    project_id = _string(project, "id")
    forbidden = _string_list(project, "forbiddenProjectIds")
    concrete_forbidden = {value for value in forbidden if not is_placeholder(value)}
    if not is_placeholder(project_id):
        lowered = project_id.lower()
        if "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
            raise PreflightError("production-like project ID is forbidden")
        if project_id in concrete_forbidden:
            raise PreflightError("project ID is listed in forbiddenProjectIds")
    if _string(project, "region") != "asia-northeast3":
        raise PreflightError("project.region must be asia-northeast3")
    _string(project, "number")
    _string(project, "billingAccount")

    firebase = _mapping(manifest, "firebase")
    for field in (
        "webAppId",
        "apiKeyReference",
        "authDomain",
        "storageBucket",
        "hostingSite",
    ):
        _string(firebase, field)
    _string_list(firebase, "authorizedDomains")
    if firebase.get("firestoreLocation") != project["region"]:
        raise PreflightError("firebase.firestoreLocation must match project.region")
    if firebase.get("storageLocation") != project["region"]:
        raise PreflightError("firebase.storageLocation must match project.region")

    artifact = _mapping(manifest, "artifactRegistry")
    if _string(artifact, "repository") != "rhwp-staging":
        raise PreflightError("artifactRegistry.repository must be rhwp-staging")
    if _string(artifact, "location") != project["region"]:
        raise PreflightError("artifactRegistry.location must match project.region")

    expected_services: dict[str, dict[str, Any]] = {
        "collaboration": {
            "name": "rhwp-collaboration-staging",
            "ingress": "all",
            "runtime": {
                "containerConcurrency": 80,
                "timeoutSeconds": 3600,
                "cpu": "1",
                "memory": "1Gi",
                "minScale": 0,
                "maxScale": 10,
            },
        },
        "documentApi": {
            "name": "rhwp-document-api-staging",
            "ingress": "all",
            "runtime": {
                "containerConcurrency": 80,
                "timeoutSeconds": 300,
                "cpu": "1",
                "memory": "512Mi",
                "minScale": 0,
                "maxScale": 20,
            },
        },
        "documentWorker": {
            "name": "rhwp-document-worker-staging",
            "ingress": "internal",
            "runtime": {
                "containerConcurrency": 1,
                "timeoutSeconds": 900,
                "cpu": "2",
                "memory": "2Gi",
                "minScale": 0,
                "maxScale": 10,
            },
        },
    }
    cloud_run = _mapping(manifest, "cloudRun")
    for key, expected in expected_services.items():
        service = _mapping(cloud_run, key)
        if service.get("name") != expected["name"]:
            raise PreflightError(f"cloudRun.{key}.name is invalid")
        if service.get("ingress") != expected["ingress"]:
            raise PreflightError(f"cloudRun.{key}.ingress is invalid")
        image = _string(service, "image")
        digest = _string(service, "digest")
        _string(service, "serviceAccount")
        if ":latest" in image:
            raise PreflightError(f"cloudRun.{key}.image must not use latest")
        if not is_placeholder(digest) and not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise PreflightError(f"cloudRun.{key}.digest must be a placeholder or SHA-256")
        if _mapping(service, "runtime") != expected["runtime"]:
            raise PreflightError(f"cloudRun.{key}.runtime does not match the design")

    tasks = _mapping(manifest, "tasks")
    _string(tasks, "callerServiceAccount")
    for key, name, suffix in (
        ("parse", "rhwp-parse-staging", "/run/parse"),
        ("export", "rhwp-export-staging", "/run/export"),
    ):
        queue = _mapping(tasks, key)
        if queue.get("name") != name:
            raise PreflightError(f"tasks.{key}.name must be {name}")
        if queue.get("location") != project["region"]:
            raise PreflightError(f"tasks.{key}.location must match project.region")
        target_url = _string(queue, "targetUrl")
        if not target_url.startswith("https://") or not target_url.endswith(suffix):
            raise PreflightError(f"tasks.{key}.targetUrl is invalid")
        if queue.get("dispatchDeadlineSeconds") != 900:
            raise PreflightError(f"tasks.{key}.dispatchDeadlineSeconds must be 900")
        if _mapping(queue, "retry") != {
            "maxAttempts": 5,
            "minBackoffSeconds": 10,
            "maxBackoffSeconds": 300,
            "maxDoublings": 5,
        }:
            raise PreflightError(f"tasks.{key}.retry does not match the design")
        if _mapping(queue, "rateLimits") != {
            "maxConcurrentDispatches": 1,
            "maxDispatchesPerSecond": 1,
        }:
            raise PreflightError(f"tasks.{key}.rateLimits does not match the design")

    internal = _mapping(_mapping(manifest, "secrets"), "collaborationInternal")
    if "value" in internal:
        raise PreflightError("secret value must never be stored in the manifest")
    if internal.get("name") != "rhwp-collaboration-internal-token-staging":
        raise PreflightError("collaboration internal secret name is invalid")
    _string(internal, "version")

    iam = _mapping(manifest, "iam")
    platform_accounts = iam.get("platformServiceAccounts")
    if platform_accounts is not None:
        if not isinstance(platform_accounts, list) or not platform_accounts:
            raise PreflightError("iam.platformServiceAccounts must be a non-empty string array")
        if any(not isinstance(item, str) or not item.strip() for item in platform_accounts):
            raise PreflightError("iam.platformServiceAccounts must contain non-empty strings")
        if len(set(platform_accounts)) != len(platform_accounts):
            raise PreflightError("iam.platformServiceAccounts must not contain duplicates")

    bindings = iam.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise PreflightError("iam.bindings must be a non-empty array")
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            raise PreflightError(f"iam.bindings[{index}] must be an object")
        role = _string(binding, "role")
        _string(binding, "principal")
        _string(binding, "resource")
        if role in {"roles/owner", "roles/editor"}:
            raise PreflightError(f"broad role {role} is forbidden")

    budget = _mapping(manifest, "budget")
    if budget.get("currency") != "KRW":
        raise PreflightError("budget.currency must be KRW")
    if budget.get("thresholds") != [0.5, 0.8, 1.0]:
        raise PreflightError("budget.thresholds must be [0.5, 0.8, 1.0]")
    amount = budget.get("amount")
    if not is_placeholder(amount) and not (
        isinstance(amount, int) and not isinstance(amount, bool) and amount > 0
    ):
        raise PreflightError("budget.amount must be a positive KRW integer or placeholder")
    _string_list(budget, "notificationChannels")

    operations = _mapping(manifest, "operations")
    _string(operations, "approvalReference")
    rollback_ids = operations.get("rollbackRevisionIds")
    if not isinstance(rollback_ids, list) or len(rollback_ids) != 3:
        raise PreflightError("operations.rollbackRevisionIds must contain three entries")
    deployment_stage = operations.get("deploymentStage")
    if deployment_stage is not None:
        if deployment_stage not in DEPLOYMENT_STAGES:
            raise PreflightError("operations.deploymentStage must be initial or upgrade")
        if deployment_stage == "initial" and rollback_ids != [None, None, None]:
            raise PreflightError(
                "initial deploymentStage requires three null rollbackRevisionIds"
            )
        if deployment_stage == "upgrade" and not all(
            isinstance(item, str) and item.strip() and not is_placeholder(item)
            for item in rollback_ids
        ):
            raise PreflightError(
                "upgrade deploymentStage requires three concrete rollbackRevisionIds"
            )
    if operations.get("cloudMutationApproved") is not False:
        raise PreflightError("operations.cloudMutationApproved must remain false")


def validate_repository_contract(manifest: dict[str, Any], root: Path = ROOT) -> list[str]:
    document_api = (root / "deploy/cloudrun/document-api.service.yaml").read_text()
    staging_env = (root / "firebase/staging.env.example").read_text()
    worker = (root / "deploy/cloudrun/document-worker.service.yaml").read_text()

    for marker in (
        "name: TASK_DISPATCH_DEADLINE_SECONDS",
        'value: "900"',
        "value: rhwp-parse-staging",
        "value: rhwp-export-staging",
    ):
        if marker not in document_api:
            raise PreflightError(f"document API template is missing: {marker}")
    if "TASK_DISPATCH_DEADLINE_SECONDS=900" not in staging_env:
        raise PreflightError("staging.env.example must set TASK_DISPATCH_DEADLINE_SECONDS=900")
    if "timeoutSeconds: 900" not in worker or "containerConcurrency: 1" not in worker:
        raise PreflightError("document worker template must match the 900-second single-task contract")

    cloud_run = _mapping(manifest, "cloudRun")
    names = [
        _string(_mapping(cloud_run, key), "name")
        for key in ("collaboration", "documentApi", "documentWorker")
    ]
    paths = (
        root / "deploy/cloudrun/collaboration-server.service.yaml",
        root / "deploy/cloudrun/document-api.service.yaml",
        root / "deploy/cloudrun/document-worker.service.yaml",
    )
    for service_name, path in zip(names, paths, strict=True):
        if f"name: {service_name}" not in path.read_text():
            raise PreflightError(f"{path.name} does not match manifest service name {service_name}")

    return [
        "manifest schema and safety constraints",
        "Cloud Run service names and runtime contract",
        "Cloud Tasks dispatch deadline 900 seconds",
        "staging environment deadline configuration",
        "worker timeout and concurrency contract",
    ]


def run_read_only(
    command: list[str],
    *,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    allowed = bool(command) and any(
        tuple(command[: len(prefix)]) == prefix for prefix in READ_ONLY_PREFIXES
    )
    if not allowed:
        raise PreflightError(f"command is not on the read-only allowlist: {_command_text(command)}")
    if {part.lower() for part in command} & MUTATING_TOKENS:
        raise PreflightError(f"command is not read-only: {_command_text(command)}")
    if any(
        any(marker in part for marker in (";", "&&", "||", "|", ">", "<"))
        for part in command
    ):
        raise PreflightError("shell control characters are forbidden in read-only commands")

    result = runner(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()[:500]
        raise PreflightError(f"read-only command failed: {_command_text(command)}: {message}")
    return result


def build_preflight_report(
    manifest_path: Path,
    *,
    live: bool,
    report_path: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    report: dict[str, Any] = {
        "schemaVersion": "rhwp.preflight-report/v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "live" if live else "static",
        "status": "pass",
        "manifest": str(manifest_path),
        "environment": manifest["environment"],
        "projectId": manifest["project"]["id"],
        "repositoryChecks": validate_repository_contract(manifest),
        "cloudQueries": [],
        "mutationCommands": [],
        "plannedChanges": {},
        "warnings": [],
    }
    if live:
        report.update(_collect_live(manifest, runner))
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def _collect_live(manifest: dict[str, Any], runner: Runner) -> dict[str, Any]:
    project = _mapping(manifest, "project")
    project_id = _string(project, "id")
    if is_placeholder(project_id):
        raise PreflightError("live preflight requires a concrete staging project ID, not a placeholder")
    forbidden = {
        value
        for value in _string_list(project, "forbiddenProjectIds")
        if not is_placeholder(value)
    }
    if project_id in forbidden:
        raise PreflightError("live preflight refuses a forbidden project ID")

    region = _string(project, "region")
    commands: list[tuple[str, list[str]]] = [
        ("activeAccounts", ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=json"]),
        ("activeProject", ["gcloud", "config", "get-value", "project"]),
        ("project", ["gcloud", "projects", "describe", project_id, "--format=json"]),
        ("billing", ["gcloud", "billing", "projects", "describe", project_id, "--format=json"]),
        ("enabledApis", ["gcloud", "services", "list", "--enabled", f"--project={project_id}", "--format=json"]),
        ("cloudRun", ["gcloud", "run", "services", "list", f"--project={project_id}", f"--region={region}", "--format=json"]),
        ("tasks", ["gcloud", "tasks", "queues", "list", f"--project={project_id}", f"--location={region}", "--format=json"]),
        ("secrets", ["gcloud", "secrets", "list", f"--project={project_id}", "--format=json"]),
        ("serviceAccounts", ["gcloud", "iam", "service-accounts", "list", f"--project={project_id}", "--format=json"]),
        ("iamPolicy", ["gcloud", "projects", "get-iam-policy", project_id, "--format=json"]),
        ("artifactRegistry", ["gcloud", "artifacts", "repositories", "list", f"--project={project_id}", f"--location={region}", "--format=json"]),
        ("firebaseProjects", ["firebase", "projects:list", "--json"]),
    ]

    outputs: dict[str, Any] = {}
    queries: list[str] = []
    for name, command in commands:
        result = run_read_only(command, runner=runner)
        queries.append(_command_text(command))
        outputs[name] = _safe_parse_output(result.stdout)

    active_project = str(outputs.get("activeProject", "")).strip()
    if active_project != project_id:
        raise PreflightError(
            f"active gcloud project {active_project!r} does not match manifest project {project_id!r}"
        )
    described = outputs.get("project")
    if isinstance(described, dict) and described.get("projectId") != project_id:
        raise PreflightError("gcloud projects describe returned a different project ID")

    expected = _expected_resource_names(manifest)
    actual = {
        "cloudRun": _collect_resource_names(outputs.get("cloudRun")),
        "tasks": _collect_resource_names(outputs.get("tasks")),
        "secrets": _collect_resource_names(outputs.get("secrets")),
        "serviceAccounts": _collect_resource_names(outputs.get("serviceAccounts")),
        "artifactRegistry": _collect_resource_names(outputs.get("artifactRegistry")),
    }
    planned: dict[str, list[str]] = {}
    existing: dict[str, list[str]] = {}
    unexpected: dict[str, list[str]] = {}
    for category, expected_names in expected.items():
        actual_names = actual.get(category, set())
        planned[category] = sorted(expected_names - actual_names)
        existing[category] = sorted(expected_names & actual_names)
        unexpected[category] = sorted(
            name for name in actual_names - expected_names if "rhwp" in name.lower()
        )

    enabled_apis = _collect_api_names(outputs.get("enabledApis"))
    planned["apis"] = sorted(REQUIRED_APIS - enabled_apis)
    existing["apis"] = sorted(REQUIRED_APIS & enabled_apis)
    warnings: list[str] = []
    if any(unexpected.values()):
        warnings.append("unexpected rhwp-prefixed resources require explicit review")

    return {
        "cloudQueries": queries,
        "cloudState": _sanitize(outputs),
        "plannedChanges": {
            "createOrEnable": planned,
            "alreadyPresent": existing,
            "unexpectedManagedResources": unexpected,
        },
        "warnings": warnings,
        "status": "review" if warnings else "pass",
    }


def _expected_resource_names(manifest: dict[str, Any]) -> dict[str, set[str]]:
    cloud_run = _mapping(manifest, "cloudRun")
    tasks = _mapping(manifest, "tasks")
    secrets = _mapping(manifest, "secrets")
    iam = _mapping(manifest, "iam")
    platform_accounts = iam.get("platformServiceAccounts", [])
    if not isinstance(platform_accounts, list):
        platform_accounts = []
    return {
        "cloudRun": {
            _string(_mapping(cloud_run, key), "name")
            for key in ("collaboration", "documentApi", "documentWorker")
        },
        "tasks": {
            _string(_mapping(tasks, "parse"), "name"),
            _string(_mapping(tasks, "export"), "name"),
        },
        "secrets": {_string(_mapping(secrets, "collaborationInternal"), "name")},
        "serviceAccounts": {
            _string(_mapping(cloud_run, key), "serviceAccount")
            for key in ("collaboration", "documentApi", "documentWorker")
        }
        | {_string(tasks, "callerServiceAccount")}
        | {item for item in platform_accounts if isinstance(item, str) and item.strip()},
        "artifactRegistry": {_string(_mapping(manifest, "artifactRegistry"), "repository")},
    }


def _collect_resource_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        candidates: list[object] = [
            item.get("name"),
            item.get("email"),
            item.get("repository"),
        ]
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            candidates.append(metadata.get("name"))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                names.add(candidate.split("/")[-1])
    return names


def _collect_api_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        config = item.get("config")
        if isinstance(config, dict) and isinstance(config.get("name"), str):
            names.add(config["name"])
        elif isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _safe_parse_output(value: str) -> Any:
    text = value.strip()
    if not text:
        return None
    try:
        return _sanitize(json.loads(text))
    except json.JSONDecodeError:
        return _sanitize(text)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = key.lower().replace("_", "")
            if any(marker in normalized for marker in (
                "accesstoken",
                "authorization",
                "credential",
                "idtoken",
                "privatekey",
                "secretvalue",
            )):
                result[key] = "[REDACTED]"
            else:
                result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and "-----BEGIN PRIVATE KEY-----" in value:
        return "[REDACTED]"
    return value


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise PreflightError(f"{key} must be an object")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise PreflightError(f"{key} must be a non-empty string")
    return item


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not item or not all(
        isinstance(entry, str) and entry.strip() for entry in item
    ):
        raise PreflightError(f"{key} must be a non-empty string array")
    return item


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _write_failure_report(path: Path, manifest_path: Path, live: bool, error: str) -> None:
    report = {
        "schemaVersion": "rhwp.preflight-report/v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "mode": "live" if live else "static",
        "status": "fail",
        "manifest": str(manifest_path),
        "error": error,
        "cloudQueries": [],
        "mutationCommands": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate rhwp staging configuration without mutation"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    manifest_path = args.manifest.resolve()
    report_path = args.report.resolve() if args.report else None
    try:
        report = build_preflight_report(
            manifest_path,
            live=args.live,
            report_path=report_path,
        )
    except PreflightError as error:
        if report_path is not None:
            _write_failure_report(report_path, manifest_path, args.live, str(error))
        print(f"staging preflight failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": report["status"],
        "mode": report["mode"],
        "manifest": report["manifest"],
        "mutationCommands": report["mutationCommands"],
    }, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
