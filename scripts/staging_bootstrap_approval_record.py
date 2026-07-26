#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.staging_approval_packet import BOOTSTRAP_DEFERRED_PATHS
    from scripts.staging_infrastructure_plan import (
        InfrastructurePlanError,
        validate_bootstrap_approval_record,
    )
else:
    from staging_approval_packet import BOOTSTRAP_DEFERRED_PATHS
    from staging_infrastructure_plan import (
        InfrastructurePlanError,
        validate_bootstrap_approval_record,
    )

REVIEW_SCHEMA = "rhwp.staging-bootstrap-packet-review/v1"
REVIEW_RESULT_SCHEMA = "rhwp.staging-bootstrap-packet-review-result/v1"
APPROVAL_RECORD_SCHEMA = "rhwp.staging-bootstrap-approval/v1"
PACKET_SCHEMA = "rhwp.staging-approval-packet/v1"
EXPECTED_ARTIFACT_NAME = "staging-approval-packet-bootstrap"
ALLOWED_SECURITY_EXCEPTION = "mvp-staging-internal-token"

PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BILLING_ACCOUNT_PATTERN = re.compile(r"^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

PACKET_ROOT_KEYS = frozenset({
    "schemaVersion",
    "phase",
    "generatedAt",
    "status",
    "deferredValues",
    "approval",
    "project",
    "firebase",
    "budget",
    "iamDiff",
    "secrets",
    "cloudRun",
    "cloudTasks",
    "internalFlush",
    "rollback",
    "acceptanceTests",
    "preflight",
    "security",
})
PACKET_APPROVAL_KEYS = frozenset({
    "reference",
    "cloudMutationApproved",
    "packetIsDeploymentApproval",
})
PACKET_PROJECT_KEYS = frozenset({
    "id",
    "number",
    "billingAccount",
    "region",
    "forbiddenProjectIds",
})
PACKET_BUDGET_KEYS = frozenset({
    "currency",
    "amount",
    "thresholds",
    "notificationChannels",
})
PACKET_SECURITY_KEYS = frozenset({
    "readOnly",
    "containsCloudMutationCommands",
    "mutationCommands",
    "redactionApplied",
})
PACKET_PREFLIGHT_KEYS = frozenset({"comparisonMode", "static", "live"})
PACKET_DEFERRED_ENTRY_KEYS = frozenset({"path", "reason"})

REVIEW_KEYS = frozenset({
    "schemaVersion",
    "decision",
    "approvedAt",
    "approvedBy",
    "commitSha",
    "workflowRunId",
    "artifactName",
    "expectedPacketSha256",
    "expectedApprovalReference",
    "acknowledgements",
    "notes",
})
ACKNOWLEDGEMENT_KEYS = frozenset({
    "packetReviewed",
    "deferredPathsAccepted",
    "billingAndBudgetReviewed",
    "internalFlushExceptionAccepted",
    "cloudMutationNotApproved",
    "deploymentNotApproved",
})

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


class ApprovalRecordError(RuntimeError):
    pass


def packet_sha256(packet_bytes: bytes) -> str:
    return hashlib.sha256(packet_bytes).hexdigest()


def load_json_with_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise ApprovalRecordError(f"{label} not found: {path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ApprovalRecordError(f"{label} must be UTF-8 JSON") from error
    except json.JSONDecodeError as error:
        raise ApprovalRecordError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ApprovalRecordError(f"{label} root must be an object")
    return value, raw


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    value, _ = load_json_with_bytes(path, label)
    return value


def validate_packet_for_approval(packet: dict[str, Any]) -> None:
    sensitive_paths = _find_sensitive_key_paths(packet, "packet")
    if sensitive_paths:
        raise ApprovalRecordError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )

    _require_exact_keys(packet, PACKET_ROOT_KEYS, "bootstrap packet")
    if packet.get("schemaVersion") != PACKET_SCHEMA:
        raise ApprovalRecordError(f"packet schemaVersion must be {PACKET_SCHEMA}")
    if packet.get("phase") != "bootstrap":
        raise ApprovalRecordError("packet phase must be bootstrap")
    if packet.get("status") != "ready-for-bootstrap-approval":
        raise ApprovalRecordError(
            "packet status must be ready-for-bootstrap-approval"
        )

    approval = _mapping(packet, "approval", "bootstrap packet")
    _require_exact_keys(approval, PACKET_APPROVAL_KEYS, "packet approval")
    _required_string(approval, "reference", "packet approval")
    if approval.get("cloudMutationApproved") is not False:
        raise ApprovalRecordError("packet approval cloudMutationApproved must remain false")
    if approval.get("packetIsDeploymentApproval") is not False:
        raise ApprovalRecordError(
            "packet approval packetIsDeploymentApproval must remain false"
        )

    project = _mapping(packet, "project", "bootstrap packet")
    _require_exact_keys(project, PACKET_PROJECT_KEYS, "packet project")
    project_id = _required_string(project, "id", "packet project")
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ApprovalRecordError("packet project id is not a valid GCP project ID")
    lowered = project_id.lower()
    if "staging" not in lowered:
        raise ApprovalRecordError("packet project id must identify a staging project")
    if "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
        raise ApprovalRecordError("packet project id must not be production-like")

    billing = _required_string(project, "billingAccount", "packet project")
    if not BILLING_ACCOUNT_PATTERN.fullmatch(billing):
        raise ApprovalRecordError(
            "packet billingAccount must use XXXXXX-XXXXXX-XXXXXX format"
        )
    forbidden = _string_list(
        project,
        "forbiddenProjectIds",
        "packet project",
        allow_empty=False,
    )
    if len(forbidden) != len(set(forbidden)):
        raise ApprovalRecordError("packet forbiddenProjectIds must not contain duplicates")
    if project_id in forbidden:
        raise ApprovalRecordError("packet project id must not be forbidden")

    budget = _mapping(packet, "budget", "bootstrap packet")
    _require_exact_keys(budget, PACKET_BUDGET_KEYS, "packet budget")
    if budget.get("currency") != "KRW":
        raise ApprovalRecordError("packet budget currency must be KRW")
    amount = budget.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ApprovalRecordError("packet budget amount must be a positive KRW integer")
    if budget.get("thresholds") != [0.5, 0.8, 1.0]:
        raise ApprovalRecordError("packet budget thresholds must be 50%, 80%, and 100%")
    _string_list(
        budget,
        "notificationChannels",
        "packet budget",
        allow_empty=False,
    )

    deferred = packet.get("deferredValues")
    if not isinstance(deferred, list):
        raise ApprovalRecordError("packet deferredValues must be an array")
    paths: list[str] = []
    for index, entry in enumerate(deferred):
        if not isinstance(entry, dict):
            raise ApprovalRecordError(
                f"packet deferredValues[{index}] must be an object"
            )
        _require_exact_keys(
            entry,
            PACKET_DEFERRED_ENTRY_KEYS,
            f"packet deferredValues[{index}]",
        )
        path = _required_string(entry, "path", f"packet deferredValues[{index}]")
        _required_string(entry, "reason", f"packet deferredValues[{index}]")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise ApprovalRecordError("packet deferred paths must not contain duplicates")
    unknown_paths = sorted(set(paths) - set(BOOTSTRAP_DEFERRED_PATHS))
    if unknown_paths:
        raise ApprovalRecordError(
            "packet contains unapproved deferred path: " + ", ".join(unknown_paths)
        )
    if paths != sorted(paths):
        raise ApprovalRecordError("packet deferred paths must be sorted")

    internal_flush = _mapping(packet, "internalFlush", "bootstrap packet")
    if internal_flush.get("decision") != ALLOWED_SECURITY_EXCEPTION:
        raise ApprovalRecordError(
            "packet internal flush decision must be mvp-staging-internal-token"
        )

    preflight = _mapping(packet, "preflight", "bootstrap packet")
    _require_exact_keys(preflight, PACKET_PREFLIGHT_KEYS, "packet preflight")
    if preflight.get("comparisonMode") != "static-only":
        raise ApprovalRecordError("packet preflight comparisonMode must be static-only")
    static = _mapping(preflight, "static", "packet preflight")
    if static.get("status") != "pass":
        raise ApprovalRecordError("packet static preflight status must be pass")
    if preflight.get("live") is not None:
        raise ApprovalRecordError("bootstrap packet live preflight evidence must be null")

    security = _mapping(packet, "security", "bootstrap packet")
    _require_exact_keys(security, PACKET_SECURITY_KEYS, "packet security")
    if security.get("readOnly") is not True:
        raise ApprovalRecordError("packet security readOnly must be true")
    if security.get("containsCloudMutationCommands") is not False:
        raise ApprovalRecordError(
            "packet security containsCloudMutationCommands must remain false"
        )
    if security.get("mutationCommands") != []:
        raise ApprovalRecordError("packet security mutationCommands must be empty")
    if security.get("redactionApplied") is not True:
        raise ApprovalRecordError("packet security redactionApplied must be true")


def validate_review_declaration(
    review: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    sensitive_paths = _find_sensitive_key_paths(review, "review")
    if sensitive_paths:
        raise ApprovalRecordError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )
    _require_exact_keys(review, REVIEW_KEYS, "review declaration")
    if review.get("schemaVersion") != REVIEW_SCHEMA:
        raise ApprovalRecordError(f"review schemaVersion must be {REVIEW_SCHEMA}")
    if review.get("decision") != "approved":
        raise ApprovalRecordError("review decision must be approved")

    approved_at = _required_string(review, "approvedAt", "review declaration")
    if not UTC_TIMESTAMP_PATTERN.fullmatch(approved_at):
        raise ApprovalRecordError(
            "review approvedAt must use UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    approvers = _string_list(
        review,
        "approvedBy",
        "review declaration",
        allow_empty=False,
    )
    if len(approvers) != len(set(approvers)):
        raise ApprovalRecordError("review approvedBy must not contain duplicate approvers")

    commit_sha = _required_string(review, "commitSha", "review declaration")
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise ApprovalRecordError(
            "review commitSha must be 40 lowercase hexadecimal characters"
        )
    workflow_run_id = review.get("workflowRunId")
    if (
        isinstance(workflow_run_id, bool)
        or not isinstance(workflow_run_id, int)
        or workflow_run_id <= 0
    ):
        raise ApprovalRecordError("review workflowRunId must be a positive integer")
    if review.get("artifactName") != EXPECTED_ARTIFACT_NAME:
        raise ApprovalRecordError(
            f"review artifactName must be {EXPECTED_ARTIFACT_NAME}"
        )
    expected_digest = _required_string(
        review,
        "expectedPacketSha256",
        "review declaration",
    )
    if not SHA256_PATTERN.fullmatch(expected_digest):
        raise ApprovalRecordError(
            "review expectedPacketSha256 must be a 64-character SHA-256 digest"
        )

    approval = _mapping(packet, "approval", "bootstrap packet")
    if review.get("expectedApprovalReference") != approval.get("reference"):
        raise ApprovalRecordError(
            "review expectedApprovalReference does not match packet approvalReference"
        )

    acknowledgements = _mapping(
        review,
        "acknowledgements",
        "review declaration",
    )
    _require_exact_keys(
        acknowledgements,
        ACKNOWLEDGEMENT_KEYS,
        "review acknowledgements",
    )
    for key in sorted(ACKNOWLEDGEMENT_KEYS):
        if acknowledgements.get(key) is not True:
            raise ApprovalRecordError(f"review acknowledgement {key} must be true")

    _string_list(review, "notes", "review declaration", allow_empty=True)


def build_approval_record(
    packet: dict[str, Any],
    review: dict[str, Any],
    digest: str,
) -> dict[str, Any]:
    validate_packet_for_approval(packet)
    validate_review_declaration(review, packet)
    if not SHA256_PATTERN.fullmatch(digest):
        raise ApprovalRecordError("computed packet digest is not a valid SHA-256 digest")
    if review.get("expectedPacketSha256") != digest:
        raise ApprovalRecordError(
            "computed packet digest does not match review expectedPacketSha256"
        )

    project = _mapping(packet, "project", "bootstrap packet")
    deferred = packet.get("deferredValues")
    assert isinstance(deferred, list)
    accepted_paths = sorted(str(entry["path"]) for entry in deferred)
    internal_flush = _mapping(packet, "internalFlush", "bootstrap packet")
    security_exceptions = (
        [ALLOWED_SECURITY_EXCEPTION]
        if internal_flush.get("decision") == ALLOWED_SECURITY_EXCEPTION
        else []
    )
    record: dict[str, Any] = {
        "schemaVersion": APPROVAL_RECORD_SCHEMA,
        "decision": "approved",
        "approvedAt": review["approvedAt"],
        "approvedBy": list(review["approvedBy"]),
        "commitSha": review["commitSha"],
        "workflowRunId": review["workflowRunId"],
        "packetSha256": digest,
        "projectId": project["id"],
        "billingAccount": project["billingAccount"],
        "acceptedDeferredPaths": accepted_paths,
        "securityExceptions": security_exceptions,
        "deploymentApproved": False,
        "cloudMutationApproved": False,
    }
    try:
        validate_bootstrap_approval_record(record, packet, digest)
    except InfrastructurePlanError as error:
        raise ApprovalRecordError(
            f"generated approval record failed planner validation: {error}"
        ) from error
    return record


def build_review_result(
    packet: dict[str, Any],
    review: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    validate_packet_for_approval(packet)
    validate_review_declaration(review, packet)
    project = _mapping(packet, "project", "bootstrap packet")
    budget = _mapping(packet, "budget", "bootstrap packet")
    approval = _mapping(packet, "approval", "bootstrap packet")
    return {
        "schemaVersion": REVIEW_RESULT_SCHEMA,
        "status": "approved-record-generated",
        "approvalReference": approval["reference"],
        "packet": {
            "schemaVersion": packet["schemaVersion"],
            "phase": packet["phase"],
            "status": packet["status"],
            "artifactName": review["artifactName"],
        },
        "packetSha256": record["packetSha256"],
        "projectId": project["id"],
        "billingAccountMasked": _mask_billing(str(project["billingAccount"])),
        "budget": {
            "currency": budget["currency"],
            "amount": budget["amount"],
            "thresholds": budget["thresholds"],
        },
        "sourceEvidence": {
            "commitSha": review["commitSha"],
            "workflowRunId": review["workflowRunId"],
        },
        "approvedAt": review["approvedAt"],
        "approvedBy": list(review["approvedBy"]),
        "acceptedDeferredPaths": list(record["acceptedDeferredPaths"]),
        "securityExceptions": list(record["securityExceptions"]),
        "notes": list(review["notes"]),
        "outputRecordSchema": record["schemaVersion"],
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }


def render_markdown(result: dict[str, Any]) -> str:
    if result.get("schemaVersion") != REVIEW_RESULT_SCHEMA:
        raise ApprovalRecordError(
            f"review result schemaVersion must be {REVIEW_RESULT_SCHEMA}"
        )
    packet = _mapping(result, "packet", "review result")
    source = _mapping(result, "sourceEvidence", "review result")
    budget = _mapping(result, "budget", "review result")
    lines = [
        "# rhwp Staging Bootstrap Packet Review",
        "",
        "> This approval record does not authorize infrastructure mutation or deployment.",
        "",
        f"- Status: `{_md(result.get('status'))}`",
        f"- Approval reference: `{_md(result.get('approvalReference'))}`",
        f"- Packet artifact: `{_md(packet.get('artifactName'))}`",
        f"- Packet phase/status: `{_md(packet.get('phase'))}` / `{_md(packet.get('status'))}`",
        f"- Packet SHA-256: `{_md(result.get('packetSha256'))}`",
        f"- Commit SHA: `{_md(source.get('commitSha'))}`",
        f"- Workflow run ID: `{_md(source.get('workflowRunId'))}`",
        f"- Project ID: `{_md(result.get('projectId'))}`",
        f"- Billing account: `{_md(result.get('billingAccountMasked'))}`",
        f"- Monthly budget: `{_md(budget.get('amount'))} {_md(budget.get('currency'))}`",
        f"- Approved at: `{_md(result.get('approvedAt'))}`",
        f"- Approved by: {_md_list(result.get('approvedBy'))}",
        "",
        "## Accepted deferred paths",
        "",
    ]
    paths = result.get("acceptedDeferredPaths")
    if isinstance(paths, list):
        for path in paths:
            lines.append(f"- `{_md(path)}`")
    lines.extend([
        "",
        "## Security exceptions",
        "",
    ])
    exceptions = result.get("securityExceptions")
    if isinstance(exceptions, list):
        for exception in exceptions:
            lines.append(f"- `{_md(exception)}`")
    lines.extend([
        "",
        "## Safety boundary",
        "",
        "- Cloud mutation approved: `false`",
        "- Deployment approved: `false`",
        "- Mutation commands: `[]`",
        "- A separate infrastructure approval is required before any resource mutation.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review a bootstrap packet and generate a non-mutating approval record"
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--record-output", type=Path, required=True)
    parser.add_argument("--review-json-output", type=Path, required=True)
    parser.add_argument("--review-markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)

    outputs = (
        args.record_output,
        args.review_json_output,
        args.review_markdown_output,
    )
    try:
        packet, raw = load_json_with_bytes(args.packet, "bootstrap packet")
        review = load_json_object(args.review, "packet review declaration")
        digest = packet_sha256(raw)
        record = build_approval_record(packet, review, digest)
        result = build_review_result(packet, review, record)
        markdown = render_markdown(result)
        _atomic_write_bundle({
            args.record_output: json.dumps(
                record,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            args.review_json_output: json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            args.review_markdown_output: markdown,
        })
    except (ApprovalRecordError, OSError) as error:
        _cleanup_outputs(outputs)
        print(f"staging bootstrap approval record failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": result["status"],
        "approvalReference": result["approvalReference"],
        "packetSha256": result["packetSha256"],
        "recordOutput": str(args.record_output),
        "reviewJsonOutput": str(args.review_json_output),
        "reviewMarkdownOutput": str(args.review_markdown_output),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def _atomic_write_bundle(contents: dict[Path, str]) -> None:
    temporary_paths: list[Path] = []
    try:
        for path, content in contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(content)
            temporary_paths.append(temporary)
        for path in contents:
            path.with_name(path.name + ".tmp").replace(path)
    except OSError:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
        raise


def _cleanup_outputs(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        except OSError:
            pass


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ApprovalRecordError(f"{label} keys are invalid: {'; '.join(details)}")


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ApprovalRecordError(f"{label}.{key} must be an object")
    return item


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ApprovalRecordError(f"{label}.{key} must be a non-empty string")
    return item


def _string_list(
    value: dict[str, Any],
    key: str,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ApprovalRecordError(f"{label}.{key} must be an array")
    if not allow_empty and not item:
        raise ApprovalRecordError(f"{label}.{key} must not be empty")
    result: list[str] = []
    for index, entry in enumerate(item):
        if not isinstance(entry, str) or not entry.strip():
            raise ApprovalRecordError(
                f"{label}.{key}[{index}] must be a non-empty string"
            )
        result.append(entry)
    return result


def _find_sensitive_key_paths(value: Any, path: str) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child = f"{path}.{key}"
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                paths.append(child)
            else:
                paths.extend(_find_sensitive_key_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_find_sensitive_key_paths(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if "-----BEGIN PRIVATE KEY-----" in value or value.startswith("Bearer "):
            paths.append(path)
    return paths


def _mask_billing(value: str) -> str:
    if not BILLING_ACCOUNT_PATTERN.fullmatch(value):
        return "[INVALID]"
    first, _, last = value.split("-")
    return f"{first}-******-{last}"


def _md(value: Any) -> str:
    if value is None:
        return "null"
    return str(value).replace("|", "\\|").replace("`", "\\`")


def _md_list(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(f"`{_md(item)}`" for item in value)


if __name__ == "__main__":
    raise SystemExit(main())
