#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if __package__:
    from scripts.staging_preflight import validate_manifest
else:
    from staging_preflight import validate_manifest

VALUES_SCHEMA_VERSION = "rhwp.staging-bootstrap-values/v1"
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BILLING_ACCOUNT_PATTERN = re.compile(r"^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$")
PLACEHOLDER_PATTERN = re.compile(r"\$\{[A-Z0-9_]+\}")
SENSITIVE_KEY_MARKERS = (
    "accesstoken",
    "authorization",
    "clientsecret",
    "credential",
    "idtoken",
    "password",
    "privatekey",
    "refreshtoken",
    "secretvalue",
)

ROOT_KEYS = frozenset({"schemaVersion", "project", "firebase", "budget", "operations"})
PROJECT_KEYS = frozenset({"id", "billingAccount", "forbiddenProjectIds"})
FIREBASE_KEYS = frozenset({"storageBucket"})
BUDGET_KEYS = frozenset({"amountKrw", "notificationChannels"})
OPERATIONS_KEYS = frozenset({
    "dataRetentionDays",
    "approvalReference",
    "internalFlushSecurityDecision",
})
ALLOWED_INTERNAL_FLUSH_DECISIONS = frozenset({"mvp-staging-internal-token"})
MATERIALIZER_DEFERRED_PATHS = frozenset({
    "manifest.project.number",
    "manifest.firebase.webAppId",
    "manifest.firebase.apiKeyReference",
    "manifest.cloudRun.collaboration.image",
    "manifest.cloudRun.collaboration.digest",
    "manifest.cloudRun.documentApi.image",
    "manifest.cloudRun.documentApi.digest",
    "manifest.cloudRun.documentWorker.image",
    "manifest.cloudRun.documentWorker.digest",
    "manifest.tasks.parse.targetUrl",
    "manifest.tasks.export.targetUrl",
    "manifest.operations.rollbackRevisionIds[0]",
    "manifest.operations.rollbackRevisionIds[1]",
    "manifest.operations.rollbackRevisionIds[2]",
})
ENVIRONMENT_KEYS = (
    "STAGING_PROJECT_ID",
    "STAGING_BILLING_ACCOUNT",
    "STAGING_FORBIDDEN_PROJECT_IDS_JSON",
    "STAGING_STORAGE_BUCKET",
    "STAGING_MONTHLY_BUDGET_KRW",
    "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON",
    "STAGING_DATA_RETENTION_DAYS",
    "STAGING_APPROVAL_REFERENCE",
    "STAGING_INTERNAL_FLUSH_DECISION",
)


class BootstrapMaterializerError(RuntimeError):
    pass


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise BootstrapMaterializerError(f"{label} not found: {path}") from error
    except json.JSONDecodeError as error:
        raise BootstrapMaterializerError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise BootstrapMaterializerError(f"{label} root must be an object")
    return value


def load_values_from_environment(environ: Mapping[str, str]) -> dict[str, Any]:
    values = {key: _required_environment_value(environ, key) for key in ENVIRONMENT_KEYS}
    forbidden = _environment_string_array(
        values["STAGING_FORBIDDEN_PROJECT_IDS_JSON"],
        "STAGING_FORBIDDEN_PROJECT_IDS_JSON",
    )
    channels = _environment_string_array(
        values["STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON"],
        "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON",
    )
    amount = _environment_positive_integer(
        values["STAGING_MONTHLY_BUDGET_KRW"],
        "STAGING_MONTHLY_BUDGET_KRW",
    )
    retention = _environment_positive_integer(
        values["STAGING_DATA_RETENTION_DAYS"],
        "STAGING_DATA_RETENTION_DAYS",
    )
    result: dict[str, Any] = {
        "schemaVersion": VALUES_SCHEMA_VERSION,
        "project": {
            "id": values["STAGING_PROJECT_ID"],
            "billingAccount": values["STAGING_BILLING_ACCOUNT"],
            "forbiddenProjectIds": forbidden,
        },
        "firebase": {
            "storageBucket": values["STAGING_STORAGE_BUCKET"],
        },
        "budget": {
            "amountKrw": amount,
            "notificationChannels": channels,
        },
        "operations": {
            "dataRetentionDays": retention,
            "approvalReference": values["STAGING_APPROVAL_REFERENCE"],
            "internalFlushSecurityDecision": values["STAGING_INTERNAL_FLUSH_DECISION"],
        },
    }
    validate_bootstrap_values(result)
    return result


def validate_bootstrap_values(values: dict[str, Any]) -> None:
    sensitive_paths = _find_sensitive_key_paths(values, "values")
    if sensitive_paths:
        raise BootstrapMaterializerError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )

    _require_exact_keys(values, ROOT_KEYS, "values")
    if values.get("schemaVersion") != VALUES_SCHEMA_VERSION:
        raise BootstrapMaterializerError(
            f"values.schemaVersion must be {VALUES_SCHEMA_VERSION}"
        )

    project = _mapping(values, "project", "values")
    firebase = _mapping(values, "firebase", "values")
    budget = _mapping(values, "budget", "values")
    operations = _mapping(values, "operations", "values")
    _require_exact_keys(project, PROJECT_KEYS, "values.project")
    _require_exact_keys(firebase, FIREBASE_KEYS, "values.firebase")
    _require_exact_keys(budget, BUDGET_KEYS, "values.budget")
    _require_exact_keys(operations, OPERATIONS_KEYS, "values.operations")

    project_id = _non_empty_string(project, "id", "values.project")
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise BootstrapMaterializerError("values.project.id is not a valid GCP project ID")
    lowered = project_id.lower()
    if "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
        raise BootstrapMaterializerError("values.project.id must not be production-like")

    billing = _non_empty_string(project, "billingAccount", "values.project")
    if not BILLING_ACCOUNT_PATTERN.fullmatch(billing):
        raise BootstrapMaterializerError(
            "values.project.billingAccount must use XXXXXX-XXXXXX-XXXXXX format"
        )

    forbidden = _non_empty_string_list(
        project,
        "forbiddenProjectIds",
        "values.project",
    )
    if len(forbidden) != len(set(forbidden)):
        raise BootstrapMaterializerError(
            "values.project.forbiddenProjectIds must not contain duplicates"
        )
    if project_id in forbidden:
        raise BootstrapMaterializerError(
            "values.project.id must not appear in forbiddenProjectIds"
        )
    for index, forbidden_id in enumerate(forbidden):
        if PLACEHOLDER_PATTERN.search(forbidden_id):
            raise BootstrapMaterializerError(
                f"values.project.forbiddenProjectIds[{index}] must be concrete"
            )

    bucket = _non_empty_string(firebase, "storageBucket", "values.firebase")
    if not bucket.startswith(project_id + ".") or not bucket.endswith(
        (".firebasestorage.app", ".appspot.com")
    ):
        raise BootstrapMaterializerError(
            "values.firebase.storageBucket must belong to values.project.id"
        )

    _positive_integer(budget, "amountKrw", "values.budget")
    _non_empty_string_list(budget, "notificationChannels", "values.budget")
    _positive_integer(operations, "dataRetentionDays", "values.operations")
    _non_empty_string(operations, "approvalReference", "values.operations")
    decision = _non_empty_string(
        operations,
        "internalFlushSecurityDecision",
        "values.operations",
    )
    if decision not in ALLOWED_INTERNAL_FLUSH_DECISIONS:
        raise BootstrapMaterializerError(
            "values.operations.internalFlushSecurityDecision is not approved"
        )


def materialize_bootstrap_manifest(
    manifest: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    validate_bootstrap_values(values)
    if manifest.get("schemaVersion") != "rhwp.staging/v1":
        raise BootstrapMaterializerError("manifest schemaVersion must be rhwp.staging/v1")
    if manifest.get("environment") != "staging":
        raise BootstrapMaterializerError("manifest environment must be staging")

    result = copy.deepcopy(manifest)
    project_values = _mapping(values, "project", "values")
    firebase_values = _mapping(values, "firebase", "values")
    budget_values = _mapping(values, "budget", "values")
    operation_values = _mapping(values, "operations", "values")

    project_id = str(project_values["id"])
    billing = str(project_values["billingAccount"])
    bucket = str(firebase_values["storageBucket"])
    hosting_domain = f"{project_id}.web.app"
    accounts = {
        "COLLABORATION_SERVICE_ACCOUNT": (
            f"rhwp-collaboration-staging@{project_id}.iam.gserviceaccount.com"
        ),
        "DOCUMENT_API_SERVICE_ACCOUNT": (
            f"rhwp-document-api-staging@{project_id}.iam.gserviceaccount.com"
        ),
        "DOCUMENT_WORKER_SERVICE_ACCOUNT": (
            f"rhwp-document-worker-staging@{project_id}.iam.gserviceaccount.com"
        ),
        "TASKS_SERVICE_ACCOUNT_EMAIL": (
            f"rhwp-tasks-staging@{project_id}.iam.gserviceaccount.com"
        ),
    }
    replacements = {
        "FIREBASE_STAGING_PROJECT_ID": project_id,
        "GCP_BILLING_ACCOUNT_ID": billing,
        "FIREBASE_HOSTING_DOMAIN": hosting_domain,
        "FIREBASE_STORAGE_BUCKET": bucket,
        **accounts,
    }
    result = _replace_placeholders(result, replacements)

    project = _mapping(result, "project", "manifest")
    project["id"] = project_id
    project["billingAccount"] = billing
    project["forbiddenProjectIds"] = copy.deepcopy(
        project_values["forbiddenProjectIds"]
    )

    firebase = _mapping(result, "firebase", "manifest")
    firebase["authDomain"] = f"{project_id}.firebaseapp.com"
    firebase["authorizedDomains"] = [
        f"{project_id}.firebaseapp.com",
        hosting_domain,
    ]
    firebase["storageBucket"] = bucket
    firebase["hostingSite"] = project_id

    cloud_run = _mapping(result, "cloudRun", "manifest")
    cloud_run["collaboration"]["serviceAccount"] = accounts[
        "COLLABORATION_SERVICE_ACCOUNT"
    ]
    cloud_run["documentApi"]["serviceAccount"] = accounts[
        "DOCUMENT_API_SERVICE_ACCOUNT"
    ]
    cloud_run["documentWorker"]["serviceAccount"] = accounts[
        "DOCUMENT_WORKER_SERVICE_ACCOUNT"
    ]
    tasks = _mapping(result, "tasks", "manifest")
    tasks["callerServiceAccount"] = accounts["TASKS_SERVICE_ACCOUNT_EMAIL"]

    budget = _mapping(result, "budget", "manifest")
    budget["amount"] = budget_values["amountKrw"]
    budget["notificationChannels"] = copy.deepcopy(
        budget_values["notificationChannels"]
    )

    operations = _mapping(result, "operations", "manifest")
    operations["dataRetentionDays"] = operation_values["dataRetentionDays"]
    operations["approvalReference"] = operation_values["approvalReference"]
    operations["internalFlushSecurityDecision"] = operation_values[
        "internalFlushSecurityDecision"
    ]
    if operations.get("cloudMutationApproved") is not False:
        raise BootstrapMaterializerError(
            "manifest.operations.cloudMutationApproved must remain false"
        )

    try:
        validate_manifest(result)
    except Exception as error:
        raise BootstrapMaterializerError(
            f"materialized manifest failed staging validation: {error}"
        ) from error

    remaining = set(_find_placeholder_paths(result))
    blocking = sorted(remaining - MATERIALIZER_DEFERRED_PATHS)
    if blocking:
        raise BootstrapMaterializerError(
            "materialized manifest has unresolved placeholder at "
            + ", ".join(blocking)
        )
    return result


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize a non-mutating rhwp staging bootstrap manifest"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--values", type=Path)
    source.add_argument("--from-environment", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    temporary = args.output.with_name(args.output.name + ".tmp")
    try:
        manifest = load_json_object(args.manifest, "staging manifest")
        if args.from_environment:
            values = load_values_from_environment(
                os.environ if environ is None else environ
            )
        else:
            assert args.values is not None
            values = load_json_object(args.values, "staging bootstrap values")
        materialized = materialize_bootstrap_manifest(manifest, values)
        content = json.dumps(materialized, ensure_ascii=False, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(content)
        temporary.replace(args.output)
    except (BootstrapMaterializerError, OSError) as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"staging bootstrap materializer failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "materialized",
        "projectId": materialized["project"]["id"],
        "output": str(args.output),
        "deferredPaths": sorted(_find_placeholder_paths(materialized)),
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def _required_environment_value(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BootstrapMaterializerError(f"required environment variable is missing: {key}")
    return value.strip()


def _environment_string_array(raw: str, key: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BootstrapMaterializerError(f"{key} must be a JSON string array") from error
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise BootstrapMaterializerError(f"{key} must be a non-empty JSON string array")
    return [item.strip() for item in value]


def _environment_positive_integer(raw: str, key: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", raw):
        raise BootstrapMaterializerError(f"{key} must be a positive decimal integer")
    return int(raw)


def _find_sensitive_key_paths(value: Any, path: str) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child_path = f"{path}.{key}"
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                result.append(child_path)
            result.extend(_find_sensitive_key_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_find_sensitive_key_paths(item, f"{path}[{index}]"))
    return result


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], path: str) -> None:
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise BootstrapMaterializerError(
            f"unknown or not allowed key at {path}: " + ", ".join(unknown)
        )
    if missing:
        raise BootstrapMaterializerError(
            f"missing required key at {path}: " + ", ".join(missing)
        )


def _mapping(value: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise BootstrapMaterializerError(f"{path}.{key} must be an object")
    return item


def _non_empty_string(value: dict[str, Any], key: str, path: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise BootstrapMaterializerError(f"{path}.{key} must be a non-empty string")
    return item.strip()


def _non_empty_string_list(value: dict[str, Any], key: str, path: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not item:
        raise BootstrapMaterializerError(f"{path}.{key} must be a non-empty string array")
    if not all(isinstance(entry, str) and entry.strip() for entry in item):
        raise BootstrapMaterializerError(f"{path}.{key} must contain non-empty strings")
    return [entry.strip() for entry in item]


def _positive_integer(value: dict[str, Any], key: str, path: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise BootstrapMaterializerError(f"{path}.{key} must be a positive integer")
    return item


def _replace_placeholders(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_placeholders(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, str):
        result = value
        for key, replacement in replacements.items():
            result = result.replace("${" + key + "}", replacement)
        return result
    return value


def _find_placeholder_paths(value: Any, path: str = "manifest") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            result.extend(_find_placeholder_paths(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_find_placeholder_paths(item, f"{path}[{index}]"))
    elif isinstance(value, str) and PLACEHOLDER_PATTERN.search(value):
        result.append(path)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
