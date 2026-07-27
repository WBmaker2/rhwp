#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

INFRASTRUCTURE_APPROVAL_SCHEMA = "rhwp.staging-infrastructure-approval/v1"
INFRASTRUCTURE_APPROVAL_RESULT_SCHEMA = "rhwp.staging-infrastructure-approval-result/v1"
INFRASTRUCTURE_PLAN_SCHEMA = "rhwp.staging-infrastructure-plan/v1"
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BILLING_ACCOUNT_PATTERN = re.compile(r"^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

APPROVAL_KEYS = frozenset({
    "schemaVersion", "decision", "approvedAt", "approvedBy", "commitSha",
    "planSha256", "projectId", "billingAccount", "approvedStageIds",
    "maximumMonthlyBudgetKrw", "cloudMutationApproved", "deploymentApproved",
    "rollbackReviewed",
})
SENSITIVE_KEY_MARKERS = (
    "accesstoken", "authorization", "clientsecret", "credential", "idtoken",
    "password", "privatekey", "refreshtoken", "secretvalue", "firebaseapikey",
    "internalflushtoken",
)


class InfrastructureApprovalError(RuntimeError):
    pass


def load_json_with_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise InfrastructureApprovalError(f"{label} not found: {path}") from error
    return _parse_json_object(raw, label), raw


def validate_infrastructure_approval(
    plan: dict[str, Any],
    plan_bytes: bytes,
    approval: dict[str, Any],
    *,
    require_cloud_mutation: bool,
) -> dict[str, Any]:
    parsed_plan = _parse_json_object(plan_bytes, "plan bytes")
    if not _same_json_structure(plan, parsed_plan):
        raise InfrastructureApprovalError("plan object does not match exact plan bytes")
    _reject_sensitive_keys(plan, "plan")
    _reject_sensitive_keys(approval, "approval")
    _validate_plan(plan)
    _require_exact_keys(approval, APPROVAL_KEYS, "approval record")

    if approval.get("schemaVersion") != INFRASTRUCTURE_APPROVAL_SCHEMA:
        raise InfrastructureApprovalError(
            f"approval record schemaVersion must be {INFRASTRUCTURE_APPROVAL_SCHEMA}"
        )
    if approval.get("decision") != "approved":
        raise InfrastructureApprovalError("approval record decision must be approved")
    approved_at = _required_string(approval, "approvedAt", "approval record")
    if not UTC_TIMESTAMP_PATTERN.fullmatch(approved_at):
        raise InfrastructureApprovalError(
            "approval record approvedAt must use UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        datetime.strptime(approved_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise InfrastructureApprovalError(
            "approval record approvedAt must be a real UTC timestamp"
        ) from error
    _approver_list(approval)

    commit_sha = _required_string(approval, "commitSha", "approval record")
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise InfrastructureApprovalError(
            "approval record commitSha must be 40 lowercase hexadecimal characters"
        )
    source = _mapping(plan, "sourceEvidence", "plan")
    if commit_sha != _required_string(source, "commitSha", "plan sourceEvidence"):
        raise InfrastructureApprovalError("approval record commitSha does not match plan sourceEvidence")

    plan_sha256 = _required_string(approval, "planSha256", "approval record")
    if not SHA256_PATTERN.fullmatch(plan_sha256):
        raise InfrastructureApprovalError(
            "approval record planSha256 must be a 64-character SHA-256 digest"
        )
    if plan_sha256 != hashlib.sha256(plan_bytes).hexdigest():
        raise InfrastructureApprovalError("plan digest does not match approval record")

    project_id = _staging_project_id(_required_string(approval, "projectId", "approval record"))
    if project_id != _required_string(plan, "projectId", "plan"):
        raise InfrastructureApprovalError("approval record projectId does not match plan")
    billing_account = _required_string(approval, "billingAccount", "approval record")
    if not BILLING_ACCOUNT_PATTERN.fullmatch(billing_account):
        raise InfrastructureApprovalError(
            "approval record billingAccount must use XXXXXX-XXXXXX-XXXXXX format"
        )
    if billing_account != _required_string(plan, "billingAccount", "plan"):
        raise InfrastructureApprovalError("approval record billingAccount does not match plan")

    budget = approval.get("maximumMonthlyBudgetKrw")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise InfrastructureApprovalError(
            "approval record maximumMonthlyBudgetKrw must be a positive integer"
        )
    if budget != _budget_guardrails_amount(plan):
        raise InfrastructureApprovalError(
            "approval record maximumMonthlyBudgetKrw does not match budget-guardrails amount"
        )
    stage_ids = _plan_stage_ids(plan)
    approved_stage_ids = _string_list(approval, "approvedStageIds", "approval record")
    if approved_stage_ids != stage_ids:
        raise InfrastructureApprovalError(
            "approval record approvedStageIds must list every plan stage exactly once and in order"
        )
    if approval.get("rollbackReviewed") is not True:
        raise InfrastructureApprovalError("approval record rollbackReviewed must be true")
    if approval.get("deploymentApproved") is not False:
        raise InfrastructureApprovalError("approval record deploymentApproved must remain false")
    cloud_mutation_approved = approval.get("cloudMutationApproved")
    if not isinstance(cloud_mutation_approved, bool):
        raise InfrastructureApprovalError("approval record cloudMutationApproved must be a boolean")
    if require_cloud_mutation and cloud_mutation_approved is not True:
        raise InfrastructureApprovalError(
            "approval record cloudMutationApproved must be true when cloud mutation is required"
        )

    return {
        "schemaVersion": INFRASTRUCTURE_APPROVAL_RESULT_SCHEMA,
        "status": "cloud-mutation-approved" if cloud_mutation_approved else "awaiting-cloud-mutation-approval",
        "planSha256": plan_sha256,
        "planObjectSha256": hashlib.sha256(_canonical_plan_bytes(plan)).hexdigest(),
        "commitSha": commit_sha,
        "projectId": project_id,
        "billingAccount": billing_account,
        "approvedStageIds": stage_ids,
        "maximumMonthlyBudgetKrw": budget,
        "cloudMutationApproved": cloud_mutation_approved,
        "requireCloudMutation": require_cloud_mutation,
        "deploymentApproved": False,
        "rollbackReviewed": True,
        "mutationCommands": [],
    }


def render_markdown(result: dict[str, Any]) -> str:
    _reject_sensitive_keys(result, "approval result")
    if result.get("schemaVersion") != INFRASTRUCTURE_APPROVAL_RESULT_SCHEMA:
        raise InfrastructureApprovalError("approval result schemaVersion is not supported")
    if result.get("deploymentApproved") is not False or result.get("mutationCommands") != []:
        raise InfrastructureApprovalError("approval result must not authorize deployment or commands")
    stages = result.get("approvedStageIds")
    if not isinstance(stages, list) or not all(isinstance(stage, str) for stage in stages):
        raise InfrastructureApprovalError("approval result approvedStageIds must be an array of strings")
    lines = [
        "# rhwp Staging Infrastructure Approval Result", "",
        "> This record does not authorize deployment and contains no mutation commands.", "",
        f"- Status: `{_md(result.get('status'))}`",
        f"- Project ID: `{_md(result.get('projectId'))}`",
        f"- Plan SHA-256: `{_md(result.get('planSha256'))}`",
        f"- Cloud mutation approved: `{_md(result.get('cloudMutationApproved'))}`",
        "- Deployment approved: `False`", "- Mutation commands: none", "",
        "## Approved stages", "",
    ]
    lines.extend(f"- `{_md(stage)}`" for stage in stages)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a non-deployment staging infrastructure approval")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--require-cloud-mutation", action="store_true")
    args = parser.parse_args(argv)
    json_temp = args.json_output.with_name(args.json_output.name + ".tmp")
    markdown_temp = args.markdown_output.with_name(args.markdown_output.name + ".tmp")
    output_backups: dict[Path, bytes | None] = {}
    published_paths: list[Path] = []
    try:
        _validate_output_paths(
            args.plan,
            args.approval,
            args.json_output,
            args.markdown_output,
        )
        plan, plan_bytes = load_json_with_bytes(args.plan, "infrastructure plan")
        approval, _ = load_json_with_bytes(args.approval, "infrastructure approval")
        result = validate_infrastructure_approval(
            plan, plan_bytes, approval, require_cloud_mutation=args.require_cloud_mutation
        )
        markdown = render_markdown(result)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        output_backups = {
            path: path.read_bytes() if path.exists() else None
            for path in (args.json_output, args.markdown_output)
        }
        json_temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        markdown_temp.write_text(markdown)
        json_temp.replace(args.json_output)
        published_paths.append(args.json_output)
        markdown_temp.replace(args.markdown_output)
        published_paths.append(args.markdown_output)
    except (InfrastructureApprovalError, OSError) as error:
        for path in (json_temp, markdown_temp):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for path in published_paths:
            try:
                prior = output_backups[path]
                if prior is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(prior)
            except OSError:
                pass
        print(f"staging infrastructure approval failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "projectId": result["projectId"], "jsonOutput": str(args.json_output), "markdownOutput": str(args.markdown_output), "mutationCommands": []}))
    return 0


def _validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schemaVersion") != INFRASTRUCTURE_PLAN_SCHEMA:
        raise InfrastructureApprovalError(f"plan schemaVersion must be {INFRASTRUCTURE_PLAN_SCHEMA}")
    if plan.get("status") != "ready-for-infrastructure-approval":
        raise InfrastructureApprovalError("plan status must be ready-for-infrastructure-approval")
    _staging_project_id(_required_string(plan, "projectId", "plan"))
    billing_account = _required_string(plan, "billingAccount", "plan")
    if not BILLING_ACCOUNT_PATTERN.fullmatch(billing_account):
        raise InfrastructureApprovalError("plan billingAccount must use XXXXXX-XXXXXX-XXXXXX format")
    commit_sha = _required_string(_mapping(plan, "sourceEvidence", "plan"), "commitSha", "plan sourceEvidence")
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise InfrastructureApprovalError("plan sourceEvidence.commitSha must be a lowercase commit SHA")
    _budget_guardrails_amount(plan)
    _plan_stage_ids(plan)


def _validate_output_paths(
    plan_input: Path,
    approval_input: Path,
    json_output: Path,
    markdown_output: Path,
) -> None:
    json_path = json_output.resolve(strict=False)
    markdown_path = markdown_output.resolve(strict=False)
    if (
        json_path == markdown_path
        or json_path in markdown_path.parents
        or markdown_path in json_path.parents
    ):
        raise InfrastructureApprovalError("JSON and Markdown output paths must not overlap")
    temporary_paths = (
        json_path.with_name(json_path.name + ".tmp"),
        markdown_path.with_name(markdown_path.name + ".tmp"),
    )
    if len({json_path, markdown_path, *temporary_paths}) != 4:
        raise InfrastructureApprovalError("output paths conflict with their temporary files")
    for input_path in (plan_input.resolve(strict=False), approval_input.resolve(strict=False)):
        for output_path in (json_path, markdown_path, *temporary_paths):
            if (
                input_path == output_path
                or input_path in output_path.parents
                or output_path in input_path.parents
            ):
                raise InfrastructureApprovalError("input and output paths must not overlap")
    for path in (json_path, markdown_path):
        if path.exists() and path.is_dir():
            raise InfrastructureApprovalError("output path must not be a directory")


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_json_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as error:
        raise InfrastructureApprovalError(f"{label} must be UTF-8 JSON") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise InfrastructureApprovalError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise InfrastructureApprovalError(f"{label} root must be an object")
    return value


def _same_json_structure(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _same_json_structure(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_structure(value, right[index])
            for index, value in enumerate(left)
        )
    return left == right


def _canonical_plan_bytes(plan: dict[str, Any]) -> bytes:
    return (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _staging_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise InfrastructureApprovalError("approval record projectId is not a valid GCP project ID")
    lowered = project_id.lower()
    if "staging" not in lowered or "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
        raise InfrastructureApprovalError("approval record projectId must identify a staging-only project")
    return project_id


def _plan_stage_ids(plan: dict[str, Any]) -> list[str]:
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        raise InfrastructureApprovalError("plan stages must be a non-empty array")
    result: list[str] = []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise InfrastructureApprovalError(f"plan stages[{index}] must be an object")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise InfrastructureApprovalError(f"plan stages[{index}].id must be a non-empty string")
        result.append(stage_id)
    if len(result) != len(set(result)):
        raise InfrastructureApprovalError("plan stage IDs must not contain duplicates")
    return result


def _budget_guardrails_amount(plan: dict[str, Any]) -> int:
    stages = plan.get("stages")
    if not isinstance(stages, list):
        raise InfrastructureApprovalError("plan stages must be an array")
    budget_stages = [stage for stage in stages if isinstance(stage, dict) and stage.get("id") == "budget-guardrails"]
    if len(budget_stages) != 1:
        raise InfrastructureApprovalError("plan must contain exactly one budget-guardrails stage")
    resources = budget_stages[0].get("resources")
    if not isinstance(resources, dict):
        raise InfrastructureApprovalError("budget-guardrails resources must be an object")
    amount = resources.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise InfrastructureApprovalError("budget-guardrails amount must be a positive integer")
    return amount


def _require_exact_keys(value: dict[str, Any], required: frozenset[str], label: str) -> None:
    unknown, missing = sorted(set(value) - required), sorted(required - set(value))
    if unknown:
        raise InfrastructureApprovalError(f"unknown keys are not allowed in {label}: " + ", ".join(unknown))
    if missing:
        raise InfrastructureApprovalError(f"missing required keys in {label}: " + ", ".join(missing))


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise InfrastructureApprovalError(f"{label}.{key} must be an object")
    return item


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise InfrastructureApprovalError(f"{label}.{key} must be a non-empty string")
    return item


def _string_list(value: dict[str, Any], key: str, label: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not item or not all(isinstance(entry, str) and entry.strip() for entry in item):
        raise InfrastructureApprovalError(f"{label}.{key} must be a non-empty array of strings")
    return list(item)


def _approver_list(approval: dict[str, Any]) -> list[str]:
    approvers = _string_list(approval, "approvedBy", "approval record")
    if any(approver != approver.strip() for approver in approvers):
        raise InfrastructureApprovalError(
            "approval record approvedBy must not contain surrounding whitespace"
        )
    if len(approvers) != len(set(approvers)):
        raise InfrastructureApprovalError("approval record approvedBy must not contain duplicates")
    return approvers


def _reject_sensitive_keys(value: Any, path: str) -> None:
    paths = _find_sensitive_key_paths(value, path)
    if paths:
        raise InfrastructureApprovalError("sensitive key is not allowed at " + ", ".join(sorted(paths)))


def _find_sensitive_key_paths(value: Any, path: str) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            child = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if (
                any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)
                and not _is_safe_secret_values_declaration(child, item)
            ):
                result.append(child)
            result.extend(_find_sensitive_key_paths(item, child))
        return result
    if isinstance(value, list):
        return [child for index, item in enumerate(value) for child in _find_sensitive_key_paths(item, f"{path}[{index}]")]
    return []


def _is_safe_secret_values_declaration(path: str, value: Any) -> bool:
    return path == "plan.security.secretValuesIncluded" and value is False


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[\x00-\x1f\x7f\x85\u2028\u2029]", " ", text)
    return text.replace("|", "\\|").replace("`", "'")


if __name__ == "__main__":
    raise SystemExit(main())
