#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.staging_bootstrap_materializer import (
        BootstrapMaterializerError,
        validate_bootstrap_values,
    )
else:
    from staging_bootstrap_materializer import (
        BootstrapMaterializerError,
        validate_bootstrap_values,
    )

INPUT_SCHEMA = "rhwp.staging-bootstrap-readiness-input/v1"
REPORT_SCHEMA = "rhwp.staging-bootstrap-readiness/v1"
VALUES_SCHEMA = "rhwp.staging-bootstrap-values/v1"
EXPECTED_REPOSITORY = "WBmaker2/rhwp"
EXPECTED_BRANCH = "feat/firebase-collaboration-mvp-v1"
EXPECTED_PR_NUMBER = 1
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_WORKFLOWS = (
    "CI",
    "CodeQL",
    "Render Diff",
    "Staging configuration",
)
REQUIRED_ENVIRONMENT_VARIABLES = frozenset({
    "STAGING_PROJECT_ID",
    "STAGING_BILLING_ACCOUNT",
    "STAGING_FORBIDDEN_PROJECT_IDS_JSON",
    "STAGING_STORAGE_BUCKET",
    "STAGING_MONTHLY_BUDGET_KRW",
    "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON",
    "STAGING_DATA_RETENTION_DAYS",
    "STAGING_APPROVAL_REFERENCE",
    "STAGING_INTERNAL_FLUSH_DECISION",
})

ROOT_KEYS = frozenset({
    "schemaVersion",
    "repository",
    "workflows",
    "governance",
    "protectedEnvironment",
    "values",
})
REPOSITORY_KEYS = frozenset({"fullName", "branch", "prNumber", "commitSha"})
WORKFLOW_KEYS = frozenset({"name", "runNumber", "commitSha", "status", "conclusion"})
GOVERNANCE_KEYS = frozenset({
    "decisionStatus",
    "checklistComplete",
    "billingOwnerConfirmed",
    "budgetApprovedKrw",
    "notificationRecipientsConfirmed",
    "privacyRetentionReviewed",
    "internalFlushExceptionAccepted",
})
ENVIRONMENT_KEYS = frozenset({
    "name",
    "configured",
    "requiredReviewerCount",
    "branchRestricted",
    "secretNames",
    "cloudCredentialsPresent",
    "idTokenWrite",
    "variableNames",
})
VALUES_KEYS = frozenset({"schemaVersion", "project", "firebase", "budget", "operations"})
FIREBASE_KEYS = frozenset({"storageBucket"})
STORAGE_BUCKET_KEYS = frozenset({"planned", "observed"})
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
SENSITIVE_EVIDENCE_KEY_EXEMPTIONS = frozenset({
    "cloudcredentialspresent",
    "idtokenwrite",
})


class BootstrapReadinessError(RuntimeError):
    pass


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise BootstrapReadinessError(f"{label} not found: {path}") from error
    except json.JSONDecodeError as error:
        raise BootstrapReadinessError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise BootstrapReadinessError(f"{label} root must be an object")
    return value


def normalize_materializer_values(payload: dict[str, Any]) -> dict[str, Any]:
    sensitive_paths = _find_sensitive_key_paths(payload, "readiness")
    if sensitive_paths:
        raise BootstrapReadinessError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )
    _require_exact_keys(payload, ROOT_KEYS, "readiness")
    if payload.get("schemaVersion") != INPUT_SCHEMA:
        raise BootstrapReadinessError(f"readiness.schemaVersion must be {INPUT_SCHEMA}")

    values = _mapping(payload, "values", "readiness")
    _require_exact_keys(values, VALUES_KEYS, "readiness.values")
    if values.get("schemaVersion") != VALUES_SCHEMA:
        raise BootstrapReadinessError(
            f"readiness.values.schemaVersion must be {VALUES_SCHEMA}"
        )
    firebase = _mapping(values, "firebase", "readiness.values")
    _require_exact_keys(firebase, FIREBASE_KEYS, "readiness.values.firebase")
    storage = _mapping(firebase, "storageBucket", "readiness.values.firebase")
    _require_exact_keys(
        storage,
        STORAGE_BUCKET_KEYS,
        "readiness.values.firebase.storageBucket",
    )
    planned = _required_string(
        storage,
        "planned",
        "readiness.values.firebase.storageBucket",
    )
    observed = storage.get("observed")
    if observed is not None and (not isinstance(observed, str) or not observed.strip()):
        raise BootstrapReadinessError(
            "readiness.values.firebase.storageBucket.observed must be null or a non-empty string"
        )
    if isinstance(observed, str) and observed != planned:
        raise BootstrapReadinessError(
            "planned and observed Firebase Storage bucket values must match before packet readiness"
        )

    normalized = copy.deepcopy(values)
    normalized_firebase = _mapping(normalized, "firebase", "normalized values")
    normalized_firebase["storageBucket"] = observed if isinstance(observed, str) else planned
    try:
        validate_bootstrap_values(normalized)
    except BootstrapMaterializerError as error:
        raise BootstrapReadinessError(str(error)) from error
    return normalized


def evaluate_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    sensitive_paths = _find_sensitive_key_paths(payload, "readiness")
    if sensitive_paths:
        raise BootstrapReadinessError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )

    blocked: list[str] = []
    repository_summary: dict[str, Any] = {}
    workflow_summary: list[dict[str, Any]] = []
    governance_summary: dict[str, Any] = {}
    environment_summary: dict[str, Any] = {}
    resource_summary: dict[str, Any] = {
        "firebaseStorageBucket": {
            "planned": None,
            "observed": None,
            "effective": None,
            "source": None,
        }
    }

    try:
        _require_exact_keys(payload, ROOT_KEYS, "readiness")
        if payload.get("schemaVersion") != INPUT_SCHEMA:
            blocked.append(f"schemaVersion must be {INPUT_SCHEMA}")

        repository = _mapping(payload, "repository", "readiness")
        _require_exact_keys(repository, REPOSITORY_KEYS, "readiness.repository")
        repository_summary = copy.deepcopy(repository)
        commit_sha = repository.get("commitSha")
        if repository.get("fullName") != EXPECTED_REPOSITORY:
            blocked.append(f"repository fullName must be {EXPECTED_REPOSITORY}")
        if repository.get("branch") != EXPECTED_BRANCH:
            blocked.append(f"repository branch must be {EXPECTED_BRANCH}")
        if repository.get("prNumber") != EXPECTED_PR_NUMBER:
            blocked.append(f"repository prNumber must be {EXPECTED_PR_NUMBER}")
        if not isinstance(commit_sha, str) or not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
            blocked.append("repository commitSha must be 40 lowercase hexadecimal characters")

        workflows = payload.get("workflows")
        if not isinstance(workflows, list):
            raise BootstrapReadinessError("readiness.workflows must be an array")
        names: list[str] = []
        for index, workflow in enumerate(workflows):
            if not isinstance(workflow, dict):
                raise BootstrapReadinessError(
                    f"readiness.workflows[{index}] must be an object"
                )
            _require_exact_keys(workflow, WORKFLOW_KEYS, f"readiness.workflows[{index}]")
            name = workflow.get("name")
            if not isinstance(name, str) or not name:
                blocked.append(f"workflow entry {index} name must be a non-empty string")
                continue
            names.append(name)
            run_number = workflow.get("runNumber")
            if isinstance(run_number, bool) or not isinstance(run_number, int) or run_number <= 0:
                blocked.append(f"workflow {name} runNumber must be a positive integer")
            if workflow.get("commitSha") != commit_sha:
                blocked.append(f"workflow {name} commit does not match repository commit")
            if workflow.get("status") != "completed" or workflow.get("conclusion") != "success":
                blocked.append(f"workflow {name} must be completed with success")
            workflow_summary.append(copy.deepcopy(workflow))
        if len(names) != len(set(names)):
            blocked.append("duplicate workflow names are not allowed")
        missing = sorted(set(REQUIRED_WORKFLOWS) - set(names))
        extra = sorted(set(names) - set(REQUIRED_WORKFLOWS))
        if missing:
            blocked.append("required workflow evidence is missing: " + ", ".join(missing))
        if extra:
            blocked.append("unknown workflow evidence is not allowed: " + ", ".join(extra))

        governance = _mapping(payload, "governance", "readiness")
        _require_exact_keys(governance, GOVERNANCE_KEYS, "readiness.governance")
        governance_summary = copy.deepcopy(governance)
        if governance.get("decisionStatus") != "approved":
            blocked.append("governance decisionStatus must be approved")
        for key in sorted(GOVERNANCE_KEYS - {"decisionStatus"}):
            if governance.get(key) is not True:
                blocked.append(f"governance {key} must be true")

        normalized = normalize_materializer_values(payload)
        storage = _mapping(
            _mapping(
                _mapping(payload, "values", "readiness"),
                "firebase",
                "readiness.values",
            ),
            "storageBucket",
            "readiness.values.firebase",
        )
        planned = storage.get("planned")
        observed = storage.get("observed")
        effective = normalized["firebase"]["storageBucket"]
        resource_summary["firebaseStorageBucket"] = {
            "planned": planned,
            "observed": observed,
            "effective": effective,
            "source": "observed" if observed is not None else "planned",
        }
    except BootstrapReadinessError as error:
        blocked.append(str(error))

    environment_pending = False
    try:
        environment = _mapping(payload, "protectedEnvironment", "readiness")
        _require_exact_keys(environment, ENVIRONMENT_KEYS, "readiness.protectedEnvironment")
        environment_summary = copy.deepcopy(environment)
        if environment.get("name") != "staging-bootstrap":
            blocked.append("protected environment name must be staging-bootstrap")
        secret_names = _string_list(
            environment,
            "secretNames",
            "readiness.protectedEnvironment",
            allow_empty=True,
        )
        if secret_names:
            blocked.append("protected environment must not contain secret names")
        if environment.get("cloudCredentialsPresent") is not False:
            blocked.append("protected environment cloud credential evidence must be false")
        if environment.get("idTokenWrite") is not False:
            blocked.append("protected environment id-token: write must be false")

        configured = environment.get("configured")
        if configured is False:
            environment_pending = True
        elif configured is not True:
            blocked.append("protected environment configured must be a boolean")
        else:
            reviewer_count = environment.get("requiredReviewerCount")
            if (
                isinstance(reviewer_count, bool)
                or not isinstance(reviewer_count, int)
                or reviewer_count < 1
            ):
                blocked.append("protected environment requiredReviewerCount must be at least 1")
            if environment.get("branchRestricted") is not True:
                blocked.append("protected environment branch restriction must be enabled")
            variable_names = _string_list(
                environment,
                "variableNames",
                "readiness.protectedEnvironment",
                allow_empty=True,
            )
            if len(variable_names) != len(set(variable_names)):
                blocked.append("protected environment variable names must not contain duplicates")
            if set(variable_names) != set(REQUIRED_ENVIRONMENT_VARIABLES):
                blocked.append("protected environment variable names must match the exact allowlist")
    except BootstrapReadinessError as error:
        blocked.append(str(error))

    if blocked:
        status = "blocked"
    elif environment_pending:
        status = "ready-for-protected-environment"
    else:
        status = "ready-for-bootstrap-packet"

    return {
        "schemaVersion": REPORT_SCHEMA,
        "status": status,
        "repository": repository_summary,
        "requiredWorkflows": list(REQUIRED_WORKFLOWS),
        "workflowEvidence": workflow_summary,
        "governance": governance_summary,
        "protectedEnvironment": environment_summary,
        "environmentPending": environment_pending,
        "resources": resource_summary,
        "normalizedValuesAvailable": status == "ready-for-bootstrap-packet",
        "blockedReasons": sorted(set(blocked)),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    if report.get("schemaVersion") != REPORT_SCHEMA:
        raise BootstrapReadinessError(f"report schemaVersion must be {REPORT_SCHEMA}")
    repository = report.get("repository") if isinstance(report.get("repository"), dict) else {}
    resource = report.get("resources") if isinstance(report.get("resources"), dict) else {}
    bucket = resource.get("firebaseStorageBucket") if isinstance(resource.get("firebaseStorageBucket"), dict) else {}
    lines = [
        "# rhwp Staging Bootstrap Readiness",
        "",
        "> This evidence is non-mutating and does not authorize cloud resource creation or deployment.",
        "",
        f"- Status: `{_md(report.get('status'))}`",
        f"- Repository: `{_md(repository.get('fullName'))}`",
        f"- Branch: `{_md(repository.get('branch'))}`",
        f"- Commit: `{_md(repository.get('commitSha'))}`",
        f"- Cloud mutation approved: `{str(report.get('cloudMutationApproved')).lower()}`",
        f"- Deployment approved: `{str(report.get('deploymentApproved')).lower()}`",
        "",
        "## Planned and observed resources",
        "",
        f"- Firebase Storage planned: `{_md(bucket.get('planned'))}`",
        f"- Firebase Storage observed: `{_md(bucket.get('observed'))}`",
        f"- Firebase Storage effective: `{_md(bucket.get('effective'))}`",
        f"- Selected source: `{_md(bucket.get('source'))}`",
        "",
        "## Required workflows",
        "",
    ]
    for workflow in report.get("workflowEvidence", []):
        if isinstance(workflow, dict):
            lines.append(
                f"- `{_md(workflow.get('name'))}` #{_md(workflow.get('runNumber'))}: "
                f"`{_md(workflow.get('status'))}/{_md(workflow.get('conclusion'))}`"
            )
    blocked = report.get("blockedReasons")
    if isinstance(blocked, list) and blocked:
        lines.extend(["", "## Blocked reasons", ""])
        lines.extend(f"- {_md(reason)}" for reason in blocked)
    lines.extend([
        "",
        "## Safety boundary",
        "",
        "- `mutationCommands=[]`",
        "- No cloud authentication or live query was performed.",
        "- A planned value is intent; an observed value is post-creation evidence.",
        "- `observed=null` is preserved and is never manufactured from the planned value.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate non-mutating rhwp staging bootstrap readiness"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--normalized-values-output", type=Path, required=True)
    args = parser.parse_args(argv)

    outputs = (args.json_output, args.markdown_output, args.normalized_values_output)
    temporaries = tuple(path.with_name(path.name + ".tmp") for path in outputs)
    try:
        payload = load_json_object(args.input, "staging bootstrap readiness input")
        report = evaluate_readiness(payload)
        markdown = render_markdown(report)
        _atomic_write(args.json_output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        _atomic_write(args.markdown_output, markdown)
        if report["status"] == "ready-for-bootstrap-packet":
            normalized = normalize_materializer_values(payload)
            _atomic_write(
                args.normalized_values_output,
                json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            )
        else:
            args.normalized_values_output.unlink(missing_ok=True)
        print(json.dumps({
            "status": report["status"],
            "jsonOutput": str(args.json_output),
            "markdownOutput": str(args.markdown_output),
            "normalizedValuesOutput": (
                str(args.normalized_values_output)
                if report["status"] == "ready-for-bootstrap-packet"
                else None
            ),
            "cloudMutationApproved": False,
            "mutationCommands": [],
        }, ensure_ascii=False, indent=2))
        return 1 if report["status"] == "blocked" else 0
    except (BootstrapReadinessError, OSError) as error:
        for temporary in temporaries:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"staging bootstrap readiness failed: {error}", file=sys.stderr)
        return 1


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(content)
    temporary.replace(path)


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        raise BootstrapReadinessError(f"{label}.{key} must be an object")
    return child


def _require_exact_keys(value: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown:
        raise BootstrapReadinessError(f"{label} has unknown key: {', '.join(unknown)}")
    if missing:
        raise BootstrapReadinessError(f"{label} is missing key: {', '.join(missing)}")


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    child = value.get(key)
    if not isinstance(child, str) or not child.strip():
        raise BootstrapReadinessError(f"{label}.{key} must be a non-empty string")
    return child


def _string_list(
    value: dict[str, Any],
    key: str,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    child = value.get(key)
    if not isinstance(child, list):
        raise BootstrapReadinessError(f"{label}.{key} must be an array")
    if not allow_empty and not child:
        raise BootstrapReadinessError(f"{label}.{key} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in child):
        raise BootstrapReadinessError(f"{label}.{key} must contain non-empty strings")
    return child


def _find_sensitive_key_paths(value: Any, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child_path = f"{path}.{key}"
            if (
                normalized not in SENSITIVE_EVIDENCE_KEY_EXEMPTIONS
                and any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)
            ):
                found.append(child_path)
            found.extend(_find_sensitive_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_sensitive_key_paths(child, f"{path}[{index}]"))
    return found


def _md(value: Any) -> str:
    if value is None:
        return "null"
    return str(value).replace("|", "\\|").replace("`", "\\`")


if __name__ == "__main__":
    raise SystemExit(main())
