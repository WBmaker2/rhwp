#!/usr/bin/env python3
"""Report fail-closed readiness for a future staging infrastructure executor."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.staging_infrastructure_action_io import ActionIoError, publish
    from scripts.staging_infrastructure_actions import InfrastructureActionsError, build_execution_manifest
    from scripts.staging_infrastructure_validation import StrictJsonError, canonical_json_bytes, parse_strict_json_bytes, validate_json_domain
    from scripts.staging_infrastructure_approval import InfrastructureApprovalError, load_json_with_bytes
except ImportError:  # pragma: no cover - direct script execution
    from staging_infrastructure_action_io import ActionIoError, publish
    from staging_infrastructure_actions import InfrastructureActionsError, build_execution_manifest
    from staging_infrastructure_validation import StrictJsonError, canonical_json_bytes, parse_strict_json_bytes, validate_json_domain
    from staging_infrastructure_approval import InfrastructureApprovalError, load_json_with_bytes

EXECUTION_SCHEMA = "rhwp.staging-infrastructure-execution/v1"
APPROVAL_SCHEMA = "rhwp.staging-infrastructure-approval-result/v1"
GATE_SCHEMA = "rhwp.staging-infrastructure-execution-readiness/v1"
REQUIRED_APPROVALS = [
    "mutation-architecture", "actual-evidence-transport", "canonical-mutation-subset",
    "staging-infrastructure-apply-environment", "wif-identity-and-least-privilege-iam-diff",
    "cloud-mutation-approval-record", "apply-workflow-dispatch",
]
STAGES = (
    ("project-billing", "observation-only", {"verify-project", "verify-billing-link", "verify-production-separation"}),
    ("api-baseline", "eligible-mutation", {"ensure-api-enabled"}),
    ("firebase-foundation", "irreversible-manual-decision", {"verify-firebase-project", "verify-firestore-location", "verify-storage-bucket", "verify-hosting-site"}),
    ("service-accounts", "eligible-mutation", {"ensure-service-account"}),
    ("artifact-registry", "eligible-mutation", {"ensure-artifact-repository"}),
    ("secret-metadata", "eligible-mutation", {"ensure-secret-container"}),
    ("iam-bindings", "deferred-resource-specific", {"review-iam-binding"}),
    ("budget-guardrails", "irreversible-manual-decision", {"verify-budget", "verify-notification-channel"}),
    ("cloud-run-prerequisites", "blocked-deferred", {"record-cloud-run-prerequisite"}),
    ("cloud-tasks-prerequisites", "blocked-deferred", {"record-cloud-tasks-prerequisite"}),
    ("post-bootstrap-evidence", "observation-only", {"collect-resource-evidence"}),
)
MANIFEST_KEYS = {"schemaVersion", "status", "projectId", "billingAccount", "sourcePlan", "sourceEvidence", "actions", "security"}
APPROVAL_KEYS = {"schemaVersion", "status", "planSha256", "planObjectSha256", "commitSha", "projectId", "billingAccount", "approvedStageIds", "maximumMonthlyBudgetKrw", "cloudMutationApproved", "requireCloudMutation", "deploymentApproved", "rollbackReviewed", "mutationCommands"}
ACTION_KEYS = {"id", "stageId", "classification", "kind", "resource", "dependencies", "desiredState", "rollbackBoundary", "evidenceQuery"}
SENSITIVE = ("accesstoken", "author" + "ization", "clientsecret", "creden" + "tial", "idtoken", "password", "private" + "key", "refreshtoken", "secret", "apikey", "internalflushtoken")
EXECUTABLE = ("command", "argv", "shell")


def evaluate_execution_readiness(manifest: dict[str, Any], approval_result: dict[str, Any], *, plan_bytes: bytes | None = None) -> dict[str, Any]:
    """Evaluate review evidence only; this function never grants execution authority."""
    reasons: list[str] = []
    try:
        if plan_bytes is None: raise GateError("plan-bytes-required")
        parse_strict_json_bytes(plan_bytes, "plan bytes")
        _validate(manifest, approval_result, plan_bytes)
    except (GateError, InfrastructureActionsError, StrictJsonError, TypeError, AttributeError, KeyError, IndexError, ValueError, RecursionError):
        reasons.append("malformed-input")
    requested = _approval_requested_state(approval_result)
    if reasons:
        status = "blocked"
    elif requested:
        status = "awaiting-executor-design-approval"
    else:
        status = "awaiting-cloud-mutation-approval"
    return {
        "schemaVersion": GATE_SCHEMA,
        "status": status,
        "projectId": _safe_string(_field(manifest, "projectId")) if not reasons else None,
        "blockedReasons": reasons,
        "requiredApprovals": list(REQUIRED_APPROVALS),
        "nextAction": "review-required-approvals",
        "approvalRecord": {"recordedStatus": _safe_string(_field(approval_result, "status")) if not reasons else "unavailable", "cloudMutationApprovedRequested": requested if not reasons else False},
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }


def render_markdown(result: dict[str, Any]) -> str:
    if result.get("schemaVersion") != GATE_SCHEMA or result.get("nextAction") != "review-required-approvals":
        raise GateError("readiness result contract is invalid")
    if result.get("cloudMutationApproved") is not False or result.get("deploymentApproved") is not False or result.get("mutationCommands") != []:
        raise GateError("readiness result must not authorize mutation or deployment")
    _reject_unsafe(result, "readiness")
    lines = ["# rhwp Staging Infrastructure Execution Readiness", "", "> This report is review evidence only; it cannot execute infrastructure changes.", "", f"- Status: `{_md(result.get('status'))}`", "- Next action: `review-required-approvals`", "- Cloud mutation authorized: `False`", "- Deployment authorized: `False`", "- Mutation commands: none", "", "## Required approvals", ""]
    lines.extend(f"- `{_md(item)}`" for item in result.get("requiredApprovals", []))
    if result.get("blockedReasons"):
        lines.extend(["", "## Blocked reasons", ""])
        lines.extend(f"- {_md(item)}" for item in result["blockedReasons"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report non-mutating staging execution readiness")
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--approval-result", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--strict-blocked-exit", action="store_true")
    args = parser.parse_args(argv)
    marker = args.json_output.with_name(args.json_output.name + ".complete")
    try:
        _validate_paths(args.execution_manifest, args.approval_result, args.plan, args.json_output, args.markdown_output, marker)
        manifest, _ = load_json_with_bytes(args.execution_manifest, "execution manifest")
        approval, _ = load_json_with_bytes(args.approval_result, "approval result")
        _, plan_bytes = load_json_with_bytes(args.plan, "infrastructure plan")
        result = evaluate_execution_readiness(manifest, approval, plan_bytes=plan_bytes)
        marker = publish(args.json_output, args.markdown_output, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", render_markdown(result))
    except (GateError, InfrastructureApprovalError, ActionIoError, OSError) as error:
        print(f"staging execution readiness failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "projectId": result["projectId"], "jsonOutput": str(args.json_output), "markdownOutput": str(args.markdown_output), "completionMarker": str(marker), "mutationCommands": []}))
    return 2 if args.strict_blocked_exit and result["status"] == "blocked" else 0


class GateError(RuntimeError):
    pass


def _validate(manifest: dict[str, Any], approval: dict[str, Any], plan_bytes: bytes) -> None:
    validate_json_domain(manifest); validate_json_domain(approval)
    _reject_unsafe(manifest, "manifest")
    _reject_unsafe(approval, "approval result")
    _exact_keys(manifest, MANIFEST_KEYS, "manifest")
    _exact_keys(approval, APPROVAL_KEYS, "approval result")
    if manifest["schemaVersion"] != EXECUTION_SCHEMA:
        raise GateError("manifest schemaVersion is not supported")
    if manifest["status"] not in {"awaiting-cloud-mutation-approval", "cloud-mutation-approved"}:
        raise GateError("manifest status is invalid")
    if approval["schemaVersion"] != APPROVAL_SCHEMA:
        raise GateError("approval result schemaVersion is not supported")
    _staging_project(_string(manifest, "projectId", "manifest"))
    _string(manifest, "billingAccount", "manifest")
    source_plan = manifest["sourcePlan"]
    if not isinstance(source_plan, dict):
        raise GateError("source-plan-invalid")
    if _plan_object_sha256(source_plan) != approval["planObjectSha256"]:
        raise GateError("source-plan-object-mismatch")
    if source_plan.get("projectId") != manifest["projectId"] or source_plan.get("billingAccount") != manifest["billingAccount"]:
        raise GateError("source-plan-binding-invalid")
    plan_source = source_plan.get("sourceEvidence")
    if not isinstance(plan_source, dict) or plan_source.get("commitSha") != approval["commitSha"]:
        raise GateError("source-plan-commit-binding-invalid")
    source = manifest["sourceEvidence"]
    _exact_keys(source, {"commitSha", "planSha256", "planObjectSha256", "actionSetSha256", "approvalResultSchema"}, "manifest sourceEvidence")
    if source["approvalResultSchema"] != APPROVAL_SCHEMA:
        raise GateError("manifest approval result provenance is invalid")
    _sha(source["commitSha"], 40, "manifest commitSha")
    _sha(source["planSha256"], 64, "manifest planSha256")
    _sha(source["planObjectSha256"], 64, "manifest planObjectSha256")
    _sha(source["actionSetSha256"], 64, "manifest actionSetSha256")
    _sha(approval["commitSha"], 40, "approval result commitSha")
    _sha(approval["planSha256"], 64, "approval result planSha256")
    _sha(approval["planObjectSha256"], 64, "approval result planObjectSha256")
    if source["commitSha"] != approval["commitSha"] or source["planSha256"] != approval["planSha256"] or source["planObjectSha256"] != approval["planObjectSha256"]:
        raise GateError("manifest source evidence does not match approval result")
    if manifest["projectId"] != approval["projectId"] or manifest["billingAccount"] != approval["billingAccount"]:
        raise GateError("manifest project or billing does not match approval result")
    _staging_project(_string(approval, "projectId", "approval result"))
    _string(approval, "billingAccount", "approval result")
    _validate_approval(approval)
    _validate_security(manifest["security"])
    if source["actionSetSha256"] != _action_set_sha256(manifest["actions"]):
        raise GateError("action-set-mismatch")
    expected = build_execution_manifest(source_plan, approval, plan_bytes=plan_bytes)
    for field in ("status", "projectId", "billingAccount", "sourceEvidence", "security", "actions"):
        if not _same_json_structure(manifest[field], expected[field]):
            raise GateError("canonical-manifest-mismatch")
    _validate_actions(manifest["actions"], approval)


def _validate_approval(approval: dict[str, Any]) -> None:
    requested = approval["cloudMutationApproved"]
    if not isinstance(requested, bool) or not isinstance(approval["requireCloudMutation"], bool):
        raise GateError("approval result mutation flags are invalid")
    expected_status = "cloud-mutation-approved" if requested else "awaiting-cloud-mutation-approval"
    if approval["status"] != expected_status or (approval["requireCloudMutation"] and not requested):
        raise GateError("approval result status does not match mutation review")
    if approval["deploymentApproved"] is not False or approval["rollbackReviewed"] is not True or approval["mutationCommands"] != []:
        raise GateError("approval result deployment, rollback, or command boundary is invalid")
    if isinstance(approval["maximumMonthlyBudgetKrw"], bool) or not isinstance(approval["maximumMonthlyBudgetKrw"], int) or approval["maximumMonthlyBudgetKrw"] <= 0:
        raise GateError("approval result budget is invalid")
    expected_ids = [item[0] for item in STAGES]
    if approval["approvedStageIds"] != expected_ids:
        raise GateError("approval result action stages are missing, duplicate, or reordered")


def _validate_security(security: Any) -> None:
    _exact_keys(security, {"secretValuesIncluded", "productionResourcesAllowed", "deploymentAuthorized", "containsMutationCommands", "mutationCommands"}, "manifest security")
    if security != {"secretValuesIncluded": False, "productionResourcesAllowed": False, "deploymentAuthorized": False, "containsMutationCommands": False, "mutationCommands": []}:
        raise GateError("manifest security boundary is invalid")


def _validate_actions(actions: Any, approval: dict[str, Any]) -> None:
    if not isinstance(actions, list) or not actions:
        raise GateError("manifest actions must be a non-empty array")
    stage_map = {stage: (classification, kinds) for stage, classification, kinds in STAGES}
    groups: dict[str, list[dict[str, Any]]] = {stage: [] for stage, _, _ in STAGES}
    seen_ids: set[str] = set(); seen_resources: set[str] = set(); sequence: list[str] = []
    for action in actions:
        _exact_keys(action, ACTION_KEYS, "action")
        action_id = _string(action, "id", "action")
        if action_id in seen_ids:
            raise GateError("duplicate-action-id")
        seen_ids.add(action_id)
        stage = _string(action, "stageId", "action")
        if stage not in stage_map:
            raise GateError("unknown-action-stage")
        classification, kinds = stage_map[stage]
        if action["classification"] != classification or action["kind"] not in kinds:
            raise GateError("invalid-action-kind")
        if not isinstance(action["resource"], dict) or not isinstance(action["desiredState"], dict) or not isinstance(action["evidenceQuery"], dict):
            raise GateError("invalid-action-shape")
        _string(action, "rollbackBoundary", "action")
        _validate_nested(action["resource"], "resource", _string(approval, "projectId", "approval result"), None)
        _validate_nested(action["desiredState"], "desiredState", _string(approval, "projectId", "approval result"), None)
        _validate_nested(action["evidenceQuery"], "evidenceQuery", _string(approval, "projectId", "approval result"), None)
        _validate_nested(action["rollbackBoundary"], "rollbackBoundary", _string(approval, "projectId", "approval result"), None)
        resource_key = _canonical(action["resource"])
        if resource_key in seen_resources:
            raise GateError("duplicate-action-resource")
        seen_resources.add(resource_key)
        if classification in {"observation-only", "irreversible-manual-decision", "deferred-resource-specific", "blocked-deferred"} and action["desiredState"].get("mutationAuthorized") is True:
            raise GateError("non-mutation-action-executable")
        groups[stage].append(action); sequence.append(stage)
    expected_stages = [item[0] for item in STAGES]
    if [stage for stage in dict.fromkeys(sequence)] != expected_stages:
        raise GateError("canonical-stage-order-invalid")
    finals: dict[str, str] = {}
    for stage in expected_stages:
        group = groups[stage]
        _validate_stage_group(stage, group)
        base = _base_dependencies(stage, finals)
        for index, action in enumerate(group):
            expected = base + ([group[index - 1]["id"]] if index else [])
            if action["dependencies"] != expected:
                raise GateError("canonical-dependencies-invalid")
        finals[stage] = group[-1]["id"]
    budget = groups["budget-guardrails"][0]
    if budget["resource"].get("amount") != approval["maximumMonthlyBudgetKrw"]:
        raise GateError("budget-binding-invalid")


def _validate_stage_group(stage: str, group: list[dict[str, Any]]) -> None:
    kinds = [item["kind"] for item in group]
    exact = {
        "project-billing": ["verify-project", "verify-billing-link", "verify-production-separation"],
        "firebase-foundation": ["verify-firebase-project", "verify-firestore-location", "verify-storage-bucket", "verify-hosting-site"],
        "service-accounts": ["ensure-service-account"] * 4,
        "artifact-registry": ["ensure-artifact-repository"],
        "budget-guardrails": ["verify-budget", "verify-notification-channel"],
        "cloud-run-prerequisites": ["record-cloud-run-prerequisite"] * 3,
        "cloud-tasks-prerequisites": ["record-cloud-tasks-prerequisite"] * 2,
    }
    if stage in exact and kinds != exact[stage]:
        raise GateError("canonical-action-count-or-order-invalid")
    if stage in {"api-baseline", "secret-metadata", "iam-bindings", "post-bootstrap-evidence"}:
        allowed = {"api-baseline": "ensure-api-enabled", "secret-metadata": "ensure-secret-container", "iam-bindings": "review-iam-binding", "post-bootstrap-evidence": "collect-resource-evidence"}[stage]
        if not group or any(kind != allowed for kind in kinds):
            raise GateError("canonical-action-kind-invalid")
    fixed_ids = {
        "project-billing": ("verify-project", "verify-billing-link", "verify-production-separation"),
        "firebase-foundation": ("firebase-project", "firestore-location", "storage-bucket", "hosting-site"),
        "service-accounts": ("ensure-collaboration", "ensure-documentApi", "ensure-documentWorker", "ensure-tasksCaller"),
        "artifact-registry": ("ensure-repository",),
        "budget-guardrails": ("verify-budget", "verify-notification-channel"),
        "cloud-run-prerequisites": ("record-collaboration", "record-documentApi", "record-documentWorker"),
        "cloud-tasks-prerequisites": ("record-parse", "record-export"),
    }
    if stage in fixed_ids and [item["id"] for item in group] != [f"{stage}.{suffix}" for suffix in fixed_ids[stage]]:
        raise GateError("canonical-action-id-order-invalid")
    for index, action in enumerate(group, start=1):
        if stage == "api-baseline" and action["id"] != f"{stage}.ensure-api-{index:02d}":
            raise GateError("canonical-action-id-order-invalid")
        if stage == "iam-bindings" and action["id"] != f"{stage}.review-{index:02d}":
            raise GateError("canonical-action-id-order-invalid")
        if stage == "post-bootstrap-evidence" and action["id"] != f"{stage}.collect-{index:02d}":
            raise GateError("canonical-action-id-order-invalid")
    if stage == "cloud-run-prerequisites" and [item["id"] for item in group] != [f"{stage}.record-{item}" for item in ("collaboration", "documentApi", "documentWorker")]:
        raise GateError("canonical-action-id-order-invalid")
    if stage == "cloud-tasks-prerequisites" and [item["id"] for item in group] != [f"{stage}.record-parse", f"{stage}.record-export"]:
        raise GateError("canonical-action-id-order-invalid")


def _base_dependencies(stage: str, finals: dict[str, str]) -> list[str]:
    lookup = {
        "project-billing": (), "api-baseline": ("project-billing",),
        "firebase-foundation": ("api-baseline",), "service-accounts": ("api-baseline",),
        "artifact-registry": ("api-baseline",), "secret-metadata": ("api-baseline", "service-accounts"),
        "iam-bindings": ("firebase-foundation", "service-accounts", "secret-metadata"),
        "budget-guardrails": ("project-billing",),
        "cloud-run-prerequisites": ("service-accounts", "artifact-registry", "secret-metadata", "iam-bindings"),
        "cloud-tasks-prerequisites": ("service-accounts", "cloud-run-prerequisites"),
        "post-bootstrap-evidence": ("firebase-foundation", "service-accounts", "artifact-registry", "secret-metadata", "iam-bindings", "budget-guardrails"),
    }
    return [finals[item] for item in lookup[stage]]


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise GateError(f"{label} has missing or unknown required fields")


def _string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or item != item.strip() or re.search(r"[\x00-\x1f\x7f\x85\u2028\u2029]", item):
        raise GateError(f"{label} {key} is invalid")
    return item


def _sha(value: Any, length: int, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
        raise GateError(f"{label} is invalid")


def _staging_project(value: str) -> None:
    lowered = value.lower()
    if "staging" not in lowered or "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
        raise GateError("project must be staging-only")


def _approval_requested_state(approval: dict[str, Any]) -> bool:
    return _field(approval, "cloudMutationApproved") is True


def _field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _safe_string(value: Any) -> str:
    return value if isinstance(value, str) and not _sensitive_value(value) else "unavailable"


def _reject_unsafe(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            safe_metadata = (normalized == "secretvaluesincluded" and item is False) or (normalized in {"containsmutationcommands", "containscloudmutationcommands"} and item is False) or (normalized == "mutationcommands" and item == [])
            if (any(marker in normalized for marker in SENSITIVE) and not safe_metadata) or (any(marker in normalized for marker in EXECUTABLE) and not safe_metadata):
                raise GateError("unsafe-input")
            _reject_unsafe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe(item, f"{path}[{index}]")
    elif isinstance(value, str) and _sensitive_value(value):
        raise GateError(f"sensitive value is not allowed at {path}")


def _sensitive_value(value: str) -> bool:
    lowered = value.lower()
    return bool(re.search(r"(?:bearer\s+|-----begin|aiza|ya29\.|ghp_|github_pat_|eyj|(?:token|password|api[_-]?key)\s*[:=]|secret\s*=)", lowered))


def _validate_nested(value: Any, label: str, project: str, parent_key: str | None) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise GateError("nested-key-invalid")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(marker in normalized for marker in SENSITIVE + EXECUTABLE):
                raise GateError("nested-unsafe-field")
            _validate_nested(item, label, project, normalized)
        return
    if isinstance(value, list):
        for item in value:
            _validate_nested(item, label, project, parent_key)
        return
    if isinstance(value, str):
        if not value or value != value.strip() or re.search(r"[\x00-\x1f\x7f\x85\u2028\u2029]", value) or _sensitive_value(value):
            raise GateError("nested-string-invalid")
        if parent_key != "forbiddenprojectids" and _production_like(value):
            raise GateError("nested-production-resource")
        if parent_key == "projectid" and value != project:
            raise GateError("nested-project-binding-invalid")
        if parent_key in {"identity", "serviceaccount", "callerserviceaccount", "principal"} and "@" in value and f"@{project}.iam.gserviceaccount.com" not in value:
            raise GateError("nested-identity-binding-invalid")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise GateError("nested-value-type-invalid")


def _production_like(value: str) -> bool:
    lowered = value.lower()
    return "production" in lowered or bool(re.search(r"(^|[-_.:/])prod(?:[-_.:/]|$)", lowered))


def _canonical(value: Any) -> str:
    return canonical_json_bytes(value).rstrip(b"\n").decode("utf-8")


def _action_set_sha256(actions: Any) -> str:
    if not isinstance(actions, list):
        raise GateError("action-set-invalid")
    return hashlib.sha256(_canonical(actions).encode("utf-8")).hexdigest()


def _plan_object_sha256(plan: dict[str, Any]) -> str:
    encoded = canonical_json_bytes(plan, indent=2)
    return hashlib.sha256(encoded).hexdigest()


def _same_json_structure(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_same_json_structure(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json_structure(item, right[index]) for index, item in enumerate(left))
    return left == right


def _validate_paths(manifest: Path, approval: Path, plan: Path, json_output: Path, markdown_output: Path, marker: Path) -> None:
    temporary = (json_output.with_name(json_output.name + ".tmp"), markdown_output.with_name(markdown_output.name + ".tmp"), marker.with_name(marker.name + ".tmp"))
    all_paths = (manifest, approval, plan, json_output, markdown_output, marker, *temporary)
    resolved = [path.resolve(strict=False) for path in all_paths]
    if any(path.is_symlink() for path in all_paths) or len(set(resolved)) != len(resolved):
        raise GateError("input, output, and marker paths must not overlap or alias")
    if any(path.exists() for path in temporary):
        raise GateError("temporary output path already exists")
    if any(path.exists() and path.is_dir() for path in (json_output, markdown_output, marker)):
        raise GateError("output path must not be a directory")


def _md(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").replace("`", "'")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
