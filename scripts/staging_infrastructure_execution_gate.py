#!/usr/bin/env python3
"""Report fail-closed readiness for a future staging infrastructure executor."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.staging_infrastructure_action_io import ActionIoError, publish
    from scripts.staging_infrastructure_approval import InfrastructureApprovalError, load_json_with_bytes
except ImportError:  # pragma: no cover - direct script execution
    from staging_infrastructure_action_io import ActionIoError, publish
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
MANIFEST_KEYS = {"schemaVersion", "status", "projectId", "billingAccount", "sourceEvidence", "actions", "security"}
APPROVAL_KEYS = {"schemaVersion", "status", "planSha256", "planObjectSha256", "commitSha", "projectId", "billingAccount", "approvedStageIds", "maximumMonthlyBudgetKrw", "cloudMutationApproved", "requireCloudMutation", "deploymentApproved", "rollbackReviewed", "mutationCommands"}
ACTION_KEYS = {"id", "stageId", "classification", "kind", "resource", "dependencies", "desiredState", "rollbackBoundary", "evidenceQuery"}
SENSITIVE = ("accesstoken", "author" + "ization", "clientsecret", "creden" + "tial", "idtoken", "password", "private" + "key", "refreshtoken", "secretvalue", "apikey", "internalflushtoken")
EXECUTABLE = ("command", "argv", "shell")


def evaluate_execution_readiness(manifest: dict[str, Any], approval_result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate review evidence only; this function never grants execution authority."""
    reasons: list[str] = []
    try:
        _validate(manifest, approval_result)
    except GateError as error:
        reasons.append(str(error))
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
        "projectId": _safe_string(manifest.get("projectId")),
        "blockedReasons": reasons,
        "requiredApprovals": list(REQUIRED_APPROVALS),
        "nextAction": "review-required-approvals",
        "approvalRecord": {"recordedStatus": _safe_string(approval_result.get("status")), "cloudMutationApprovedRequested": requested},
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
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--strict-blocked-exit", action="store_true")
    args = parser.parse_args(argv)
    marker = args.json_output.with_name(args.json_output.name + ".complete")
    try:
        _validate_paths(args.execution_manifest, args.approval_result, args.json_output, args.markdown_output, marker)
        manifest, _ = load_json_with_bytes(args.execution_manifest, "execution manifest")
        approval, _ = load_json_with_bytes(args.approval_result, "approval result")
        result = evaluate_execution_readiness(manifest, approval)
        marker = publish(args.json_output, args.markdown_output, json.dumps(result, ensure_ascii=False, indent=2) + "\n", render_markdown(result))
    except (GateError, InfrastructureApprovalError, ActionIoError, OSError) as error:
        print(f"staging execution readiness failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "projectId": result["projectId"], "jsonOutput": str(args.json_output), "markdownOutput": str(args.markdown_output), "completionMarker": str(marker), "mutationCommands": []}))
    return 2 if args.strict_blocked_exit and result["status"] == "blocked" else 0


class GateError(RuntimeError):
    pass


def _validate(manifest: dict[str, Any], approval: dict[str, Any]) -> None:
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
    source = manifest["sourceEvidence"]
    _exact_keys(source, {"commitSha", "planSha256", "approvalResultSchema"}, "manifest sourceEvidence")
    if source["approvalResultSchema"] != APPROVAL_SCHEMA:
        raise GateError("manifest approval result provenance is invalid")
    _sha(source["commitSha"], 40, "manifest commitSha")
    _sha(source["planSha256"], 64, "manifest planSha256")
    _sha(approval["commitSha"], 40, "approval result commitSha")
    _sha(approval["planSha256"], 64, "approval result planSha256")
    _sha(approval["planObjectSha256"], 64, "approval result planObjectSha256")
    if source["commitSha"] != approval["commitSha"] or source["planSha256"] != approval["planSha256"]:
        raise GateError("manifest source evidence does not match approval result")
    if manifest["projectId"] != approval["projectId"] or manifest["billingAccount"] != approval["billingAccount"]:
        raise GateError("manifest project or billing does not match approval result")
    _staging_project(_string(approval, "projectId", "approval result"))
    _string(approval, "billingAccount", "approval result")
    _validate_approval(approval)
    _validate_security(manifest["security"])
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
    seen_ids: set[str] = set(); prior_stages: list[str] = []; last_index = -1
    budget_seen = False
    for index, action in enumerate(actions):
        _exact_keys(action, ACTION_KEYS, f"action {index}")
        action_id = _string(action, "id", f"action {index}")
        if action_id in seen_ids:
            raise GateError("manifest actions contain duplicate IDs")
        seen_ids.add(action_id)
        stage = _string(action, "stageId", f"action {index}")
        if stage not in stage_map:
            raise GateError("manifest actions contain an unknown stage")
        position = [item[0] for item in STAGES].index(stage)
        if position < last_index:
            raise GateError("manifest actions are reordered")
        last_index = position
        classification, kinds = stage_map[stage]
        if action["classification"] != classification or action["kind"] not in kinds:
            raise GateError("manifest action classification or kind is invalid")
        if not isinstance(action["dependencies"], list) or any(not isinstance(item, str) or item not in seen_ids for item in action["dependencies"]):
            raise GateError("manifest action dependency is missing or later")
        if len(action["dependencies"]) != len(set(action["dependencies"])):
            raise GateError("manifest action dependencies contain duplicates")
        if not isinstance(action["desiredState"], dict) or not isinstance(action["resource"], (dict, list)) or not isinstance(action["evidenceQuery"], dict):
            raise GateError("manifest action structure is invalid")
        _string(action, "rollbackBoundary", f"action {index}")
        if classification in {"observation-only", "irreversible-manual-decision", "deferred-resource-specific", "blocked-deferred"} and action["desiredState"].get("mutationAuthorized") is True:
            raise GateError("non-mutation action is marked executable")
        if stage == "budget-guardrails" and action["kind"] == "verify-budget":
            if action["resource"].get("amount") != approval["maximumMonthlyBudgetKrw"]:
                raise GateError("manifest budget does not match approval result")
            budget_seen = True
        prior_stages.append(stage)
    expected_stages = [item[0] for item in STAGES]
    if [stage for stage in dict.fromkeys(prior_stages)] != expected_stages:
        raise GateError("manifest actions are missing, duplicate, unknown, or reordered")
    if not budget_seen:
        raise GateError("manifest budget action is missing")


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
    return approval.get("cloudMutationApproved") is True


def _safe_string(value: Any) -> str:
    return value if isinstance(value, str) and not _sensitive_value(value) else "unavailable"


def _reject_unsafe(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            safe_metadata = (normalized == "secretvaluesincluded" and item is False) or (normalized == "containsmutationcommands" and item is False) or (normalized == "mutationcommands" and item == [])
            if (any(marker in normalized for marker in SENSITIVE) and not safe_metadata) or (any(marker in normalized for marker in EXECUTABLE) and not safe_metadata):
                raise GateError(f"unsafe field is not allowed at {path}.{key}")
            _reject_unsafe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe(item, f"{path}[{index}]")
    elif isinstance(value, str) and _sensitive_value(value):
        raise GateError(f"sensitive value is not allowed at {path}")


def _sensitive_value(value: str) -> bool:
    lowered = value.lower()
    return bool(re.search(r"(?:bearer\s+|-----begin|AIza|ya29\.)", lowered))


def _validate_paths(manifest: Path, approval: Path, json_output: Path, markdown_output: Path, marker: Path) -> None:
    temporary = (json_output.with_name(json_output.name + ".tmp"), markdown_output.with_name(markdown_output.name + ".tmp"), marker.with_name(marker.name + ".tmp"))
    all_paths = (manifest, approval, json_output, markdown_output, marker, *temporary)
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
