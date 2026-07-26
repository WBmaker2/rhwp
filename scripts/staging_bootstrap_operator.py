#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.staging_bootstrap_approval_record import (
        APPROVAL_RECORD_SCHEMA,
        EXPECTED_ARTIFACT_NAME,
        REVIEW_SCHEMA,
        ApprovalRecordError,
        build_approval_record,
        packet_sha256,
        validate_packet_for_approval,
        validate_review_declaration,
    )
    from scripts.staging_bootstrap_readiness import (
        BootstrapReadinessError,
        REQUIRED_ENVIRONMENT_VARIABLES,
        evaluate_readiness,
    )
    from scripts.staging_infrastructure_plan import (
        InfrastructurePlanError,
        validate_bootstrap_approval_record,
    )
else:
    from staging_bootstrap_approval_record import (
        APPROVAL_RECORD_SCHEMA,
        EXPECTED_ARTIFACT_NAME,
        REVIEW_SCHEMA,
        ApprovalRecordError,
        build_approval_record,
        packet_sha256,
        validate_packet_for_approval,
        validate_review_declaration,
    )
    from staging_bootstrap_readiness import (
        BootstrapReadinessError,
        REQUIRED_ENVIRONMENT_VARIABLES,
        evaluate_readiness,
    )
    from staging_infrastructure_plan import (
        InfrastructurePlanError,
        validate_bootstrap_approval_record,
    )

REPORT_SCHEMA = "rhwp.staging-bootstrap-operator-status/v1"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class BootstrapOperatorError(RuntimeError):
    pass


def evaluate_operator_status(
    readiness: dict[str, Any] | None,
    *,
    packet: dict[str, Any] | None = None,
    packet_bytes: bytes | None = None,
    packet_workflow_run_id: int | None = None,
    packet_commit_sha: str | None = None,
    review: dict[str, Any] | None = None,
    approval_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if readiness is None:
        if any(value is not None for value in (packet, review, approval_record)):
            return _blocked_report(
                ["readiness input is required before packet, review, or approval evidence"],
            )
        return _base_report(
            status="collect-operating-values",
            readiness_status=None,
            project_id=None,
            billing_masked=None,
            approval_reference=None,
            packet_digest=None,
            packet_run_id=None,
            packet_commit=None,
            approval_record_schema=None,
            blocked_reasons=[],
            next_action=_collect_values_action(),
        )

    try:
        readiness_report = evaluate_readiness(readiness)
    except BootstrapReadinessError as error:
        return _blocked_report([str(error)])

    project_id, billing_account, approval_reference = _readiness_identity(readiness)
    billing_masked = _mask_billing(billing_account)
    readiness_status = readiness_report.get("status")

    if readiness_status == "blocked":
        reasons = readiness_report.get("blockedReasons")
        if not isinstance(reasons, list):
            reasons = ["readiness evaluation is blocked"]
        return _base_report(
            status="blocked",
            readiness_status="blocked",
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
            packet_digest=None,
            packet_run_id=None,
            packet_commit=None,
            approval_record_schema=None,
            blocked_reasons=[str(item) for item in reasons],
            next_action=_blocked_action(),
        )

    if readiness_status == "ready-for-protected-environment":
        if any(value is not None for value in (packet, review, approval_record)):
            return _blocked_report(
                ["packet evidence is not allowed before staging-bootstrap environment attestation"],
                readiness_status=readiness_status,
                project_id=project_id,
                billing_masked=billing_masked,
                approval_reference=approval_reference,
            )
        return _base_report(
            status="configure-staging-bootstrap-environment",
            readiness_status=readiness_status,
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
            packet_digest=None,
            packet_run_id=None,
            packet_commit=None,
            approval_record_schema=None,
            blocked_reasons=[],
            next_action={
                "id": "configure-staging-bootstrap-environment",
                "environment": "staging-bootstrap",
                "requiredReviewerCountMinimum": 1,
                "branchRestrictionRequired": True,
                "requiredVariableNames": sorted(REQUIRED_ENVIRONMENT_VARIABLES),
                "secretsAllowed": False,
                "cloudCredentialsAllowed": False,
                "idTokenWriteAllowed": False,
            },
        )

    if readiness_status != "ready-for-bootstrap-packet":
        return _blocked_report(
            [f"unknown readiness status: {readiness_status}"],
            readiness_status=str(readiness_status),
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
        )

    if packet is None:
        if review is not None or approval_record is not None:
            return _blocked_report(
                ["bootstrap packet is required before review or approval record evidence"],
                readiness_status=readiness_status,
                project_id=project_id,
                billing_masked=billing_masked,
                approval_reference=approval_reference,
            )
        return _base_report(
            status="generate-actual-bootstrap-packet",
            readiness_status=readiness_status,
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
            packet_digest=None,
            packet_run_id=None,
            packet_commit=None,
            approval_record_schema=None,
            blocked_reasons=[],
            next_action={
                "id": "generate-actual-bootstrap-packet",
                "workflow": {
                    "name": "Staging configuration",
                    "approvalPhase": "bootstrap",
                    "liveCheck": False,
                    "protectedEnvironment": "staging-bootstrap",
                },
                "expectedArtifactName": EXPECTED_ARTIFACT_NAME,
            },
        )

    try:
        digest = _validate_packet_evidence(
            readiness,
            packet,
            packet_bytes,
            packet_workflow_run_id,
            packet_commit_sha,
        )
        _validate_packet_matches_readiness(
            readiness,
            packet,
            project_id=project_id,
            billing_account=billing_account,
            approval_reference=approval_reference,
        )

        if review is None:
            if approval_record is not None:
                raise BootstrapOperatorError(
                    "bootstrap packet review is required before approval record evidence"
                )
            return _base_report(
                status="review-actual-bootstrap-packet",
                readiness_status=readiness_status,
                project_id=project_id,
                billing_masked=billing_masked,
                approval_reference=approval_reference,
                packet_digest=digest,
                packet_run_id=packet_workflow_run_id,
                packet_commit=packet_commit_sha,
                approval_record_schema=None,
                blocked_reasons=[],
                next_action={
                    "id": "review-actual-bootstrap-packet",
                    "artifactName": EXPECTED_ARTIFACT_NAME,
                    "expectedPacketSha256": digest,
                    "humanReviewRequired": True,
                    "reviewDraftDecision": "pending",
                },
            )

        validate_review_declaration(review, packet)
        if review.get("expectedPacketSha256") != digest:
            raise BootstrapOperatorError(
                "review expected packet digest does not match exact packet bytes"
            )
        if review.get("commitSha") != packet_commit_sha:
            raise BootstrapOperatorError(
                "review commit does not match packet source commit"
            )
        if review.get("workflowRunId") != packet_workflow_run_id:
            raise BootstrapOperatorError(
                "review workflow run ID does not match packet source workflow run"
            )

        expected_record = build_approval_record(packet, review, digest)
        if approval_record is None:
            return _base_report(
                status="generate-bootstrap-approval-record",
                readiness_status=readiness_status,
                project_id=project_id,
                billing_masked=billing_masked,
                approval_reference=approval_reference,
                packet_digest=digest,
                packet_run_id=packet_workflow_run_id,
                packet_commit=packet_commit_sha,
                approval_record_schema=None,
                blocked_reasons=[],
                next_action={
                    "id": "generate-bootstrap-approval-record",
                    "workflow": {
                        "name": "Staging configuration",
                        "approvalPhase": "bootstrap-review",
                        "liveCheck": False,
                        "protectedEnvironment": "staging-bootstrap-approval",
                    },
                    "expectedArtifactName": "staging-bootstrap-approval-review",
                },
            )

        validate_bootstrap_approval_record(approval_record, packet, digest)
        if approval_record != expected_record:
            raise BootstrapOperatorError(
                "approval record does not exactly match the reviewed packet and review declaration"
            )
        return _base_report(
            status="ready-for-infrastructure-plan",
            readiness_status=readiness_status,
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
            packet_digest=digest,
            packet_run_id=packet_workflow_run_id,
            packet_commit=packet_commit_sha,
            approval_record_schema=APPROVAL_RECORD_SCHEMA,
            blocked_reasons=[],
            next_action={
                "id": "generate-infrastructure-plan",
                "workflow": {
                    "name": "Staging configuration",
                    "approvalPhase": "infrastructure-plan",
                    "liveCheck": False,
                    "protectedEnvironment": "staging-infrastructure",
                },
                "cloudMutationAuthorized": False,
                "deploymentAuthorized": False,
            },
        )
    except (
        ApprovalRecordError,
        BootstrapOperatorError,
        InfrastructurePlanError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        return _blocked_report(
            [str(error)],
            readiness_status=readiness_status,
            project_id=project_id,
            billing_masked=billing_masked,
            approval_reference=approval_reference,
        )


def build_pending_review_draft(
    packet: dict[str, Any],
    packet_bytes: bytes,
    *,
    commit_sha: str,
    workflow_run_id: int,
) -> dict[str, Any]:
    validate_packet_for_approval(packet)
    _validate_source_evidence(commit_sha, workflow_run_id)
    _require_packet_bytes_match(packet, packet_bytes)
    approval = _mapping(packet, "approval", "bootstrap packet")
    return {
        "schemaVersion": REVIEW_SCHEMA,
        "decision": "pending",
        "approvedAt": None,
        "approvedBy": [],
        "commitSha": commit_sha,
        "workflowRunId": workflow_run_id,
        "artifactName": EXPECTED_ARTIFACT_NAME,
        "expectedPacketSha256": packet_sha256(packet_bytes),
        "expectedApprovalReference": approval.get("reference"),
        "acknowledgements": {
            "packetReviewed": False,
            "deferredPathsAccepted": False,
            "billingAndBudgetReviewed": False,
            "internalFlushExceptionAccepted": False,
            "cloudMutationNotApproved": False,
            "deploymentNotApproved": False,
        },
        "notes": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    if report.get("schemaVersion") != REPORT_SCHEMA:
        raise BootstrapOperatorError(f"report schemaVersion must be {REPORT_SCHEMA}")
    next_action = report.get("nextAction")
    if not isinstance(next_action, dict):
        raise BootstrapOperatorError("report nextAction must be an object")
    lines = [
        "# rhwp Staging Bootstrap Operator Status",
        "",
        "> This status report is read-only and does not authorize cloud mutation or deployment.",
        "",
        f"- Status: `{_md(report.get('status'))}`",
        f"- Readiness status: `{_md(report.get('readinessStatus'))}`",
        f"- Project ID: `{_md(report.get('projectId'))}`",
        f"- Billing account: `{_md(report.get('billingAccountMasked'))}`",
        f"- Approval reference: `{_md(report.get('approvalReference'))}`",
        f"- Packet SHA-256: `{_md(report.get('packetSha256'))}`",
        f"- Packet workflow run ID: `{_md(report.get('packetWorkflowRunId'))}`",
        f"- Packet commit SHA: `{_md(report.get('packetCommitSha'))}`",
        f"- Approval record schema: `{_md(report.get('approvalRecordSchema'))}`",
        "",
        "## Next action",
        "",
        f"- Action: `{_md(next_action.get('id'))}`",
        f"- Evidence: `{_md(json.dumps(next_action, ensure_ascii=False, sort_keys=True))}`",
        "",
        "## Blocked reasons",
        "",
    ]
    blocked = report.get("blockedReasons")
    if isinstance(blocked, list) and blocked:
        lines.extend(f"- {_md(item)}" for item in blocked)
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Safety boundary",
        "",
        "- Cloud mutation approved: `false`",
        "- Deployment approved: `false`",
        "- Mutation commands: `[]`",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the non-mutating rhwp actual staging bootstrap operator lifecycle"
    )
    parser.add_argument("--readiness-input", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--packet-workflow-run-id", type=int)
    parser.add_argument("--packet-commit-sha")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--approval-record", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--review-draft-output", type=Path)
    parser.add_argument("--strict-blocked-exit", action="store_true")
    args = parser.parse_args(argv)

    try:
        readiness = (
            _load_json_object(args.readiness_input, "readiness input")
            if args.readiness_input.exists()
            else None
        )
        packet, raw_packet = (
            _load_json_with_bytes(args.packet, "bootstrap packet")
            if args.packet is not None
            else (None, None)
        )
        review = (
            _load_json_object(args.review, "packet review")
            if args.review is not None
            else None
        )
        approval_record = (
            _load_json_object(args.approval_record, "bootstrap approval record")
            if args.approval_record is not None
            else None
        )
        report = evaluate_operator_status(
            readiness,
            packet=packet,
            packet_bytes=raw_packet,
            packet_workflow_run_id=args.packet_workflow_run_id,
            packet_commit_sha=args.packet_commit_sha,
            review=review,
            approval_record=approval_record,
        )
        if report["status"] == "blocked" and args.strict_blocked_exit:
            raise BootstrapOperatorError("operator status is blocked")

        outputs: list[tuple[Path, str]] = [
            (
                args.json_output,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            ),
            (args.markdown_output, render_markdown(report)),
        ]
        if args.review_draft_output is not None:
            if report["status"] != "review-actual-bootstrap-packet":
                raise BootstrapOperatorError(
                    "review draft output is allowed only at review-actual-bootstrap-packet"
                )
            assert packet is not None and raw_packet is not None
            assert args.packet_commit_sha is not None
            assert args.packet_workflow_run_id is not None
            draft = build_pending_review_draft(
                packet,
                raw_packet,
                commit_sha=args.packet_commit_sha,
                workflow_run_id=args.packet_workflow_run_id,
            )
            outputs.append((
                args.review_draft_output,
                json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
            ))
        _atomic_write_many(outputs)
    except (
        ApprovalRecordError,
        BootstrapOperatorError,
        InfrastructurePlanError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        print(f"staging bootstrap operator failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": report["status"],
        "nextAction": report["nextAction"]["id"],
        "jsonOutput": str(args.json_output),
        "markdownOutput": str(args.markdown_output),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def _validate_packet_evidence(
    readiness: dict[str, Any],
    packet: dict[str, Any],
    raw_packet: bytes | None,
    workflow_run_id: int | None,
    commit_sha: str | None,
) -> str:
    if raw_packet is None:
        raise BootstrapOperatorError("exact bootstrap packet bytes are required")
    _validate_source_evidence(commit_sha, workflow_run_id)
    repository = _mapping(readiness, "repository", "readiness input")
    if commit_sha != repository.get("commitSha"):
        raise BootstrapOperatorError(
            "packet source commit does not match readiness repository commit"
        )
    _require_packet_bytes_match(packet, raw_packet)
    validate_packet_for_approval(packet)
    return packet_sha256(raw_packet)


def _validate_source_evidence(commit_sha: str | None, workflow_run_id: int | None) -> None:
    if not isinstance(commit_sha, str) or not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise BootstrapOperatorError(
            "packet source commit must be 40 lowercase hexadecimal characters"
        )
    if (
        isinstance(workflow_run_id, bool)
        or not isinstance(workflow_run_id, int)
        or workflow_run_id <= 0
    ):
        raise BootstrapOperatorError("packet source workflow run ID must be a positive integer")


def _require_packet_bytes_match(packet: dict[str, Any], raw_packet: bytes) -> None:
    try:
        decoded = json.loads(raw_packet.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise BootstrapOperatorError("bootstrap packet must be UTF-8 JSON") from error
    except json.JSONDecodeError as error:
        raise BootstrapOperatorError(f"bootstrap packet is not valid JSON: {error}") from error
    if decoded != packet:
        raise BootstrapOperatorError(
            "bootstrap packet object does not match the exact packet bytes"
        )


def _validate_packet_matches_readiness(
    readiness: dict[str, Any],
    packet: dict[str, Any],
    *,
    project_id: str | None,
    billing_account: str | None,
    approval_reference: str | None,
) -> None:
    packet_project = _mapping(packet, "project", "bootstrap packet")
    packet_approval = _mapping(packet, "approval", "bootstrap packet")
    if packet_project.get("id") != project_id:
        raise BootstrapOperatorError(
            "bootstrap packet project ID does not match readiness operating values"
        )
    if packet_project.get("billingAccount") != billing_account:
        raise BootstrapOperatorError(
            "bootstrap packet billing account does not match readiness operating values"
        )
    if packet_approval.get("reference") != approval_reference:
        raise BootstrapOperatorError(
            "bootstrap packet approval reference does not match readiness operating values"
        )


def _readiness_identity(
    readiness: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    values = readiness.get("values")
    if not isinstance(values, dict):
        return None, None, None
    project = values.get("project")
    operations = values.get("operations")
    project_id = project.get("id") if isinstance(project, dict) else None
    billing = project.get("billingAccount") if isinstance(project, dict) else None
    approval = operations.get("approvalReference") if isinstance(operations, dict) else None
    return (
        project_id if isinstance(project_id, str) else None,
        billing if isinstance(billing, str) else None,
        approval if isinstance(approval, str) else None,
    )


def _base_report(
    *,
    status: str,
    readiness_status: str | None,
    project_id: str | None,
    billing_masked: str | None,
    approval_reference: str | None,
    packet_digest: str | None,
    packet_run_id: int | None,
    packet_commit: str | None,
    approval_record_schema: str | None,
    blocked_reasons: list[str],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": REPORT_SCHEMA,
        "status": status,
        "readinessStatus": readiness_status,
        "projectId": project_id,
        "billingAccountMasked": billing_masked,
        "approvalReference": approval_reference,
        "packetSha256": packet_digest,
        "packetWorkflowRunId": packet_run_id,
        "packetCommitSha": packet_commit,
        "approvalRecordSchema": approval_record_schema,
        "nextAction": next_action,
        "blockedReasons": sorted(set(blocked_reasons)),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }


def _blocked_report(
    reasons: list[str],
    *,
    readiness_status: str | None = None,
    project_id: str | None = None,
    billing_masked: str | None = None,
    approval_reference: str | None = None,
) -> dict[str, Any]:
    return _base_report(
        status="blocked",
        readiness_status=readiness_status,
        project_id=project_id,
        billing_masked=billing_masked,
        approval_reference=approval_reference,
        packet_digest=None,
        packet_run_id=None,
        packet_commit=None,
        approval_record_schema=None,
        blocked_reasons=reasons,
        next_action=_blocked_action(),
    )


def _blocked_action() -> dict[str, Any]:
    return {
        "id": "resolve-blockers",
        "cloudMutationAuthorized": False,
        "deploymentAuthorized": False,
    }


def _collect_values_action() -> dict[str, Any]:
    return {
        "id": "collect-operating-values",
        "targetPath": "deploy/staging/staging-bootstrap-readiness.local.json",
        "requiredValueNames": [
            "STAGING_PROJECT_ID",
            "STAGING_BILLING_ACCOUNT",
            "STAGING_FORBIDDEN_PROJECT_IDS_JSON",
            "STAGING_STORAGE_BUCKET",
            "STAGING_MONTHLY_BUDGET_KRW",
            "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON",
            "STAGING_DATA_RETENTION_DAYS",
            "STAGING_APPROVAL_REFERENCE",
            "STAGING_INTERNAL_FLUSH_DECISION",
        ],
        "inventValues": False,
    }


def _load_json_with_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise BootstrapOperatorError(f"{label} not found: {path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise BootstrapOperatorError(f"{label} must be UTF-8 JSON") from error
    except json.JSONDecodeError as error:
        raise BootstrapOperatorError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise BootstrapOperatorError(f"{label} root must be an object")
    return value, raw


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    value, _ = _load_json_with_bytes(path, label)
    return value


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise BootstrapOperatorError(f"{label}.{key} must be an object")
    return item


def _mask_billing(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.split("-")
    if len(parts) != 3:
        return "[MASKED]"
    return f"{parts[0]}-******-{parts[2]}"


def _atomic_write_many(outputs: list[tuple[Path, str]]) -> None:
    temp_paths: list[Path] = []
    try:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(content)
            temp_paths.append(temp)
        for (path, _), temp in zip(outputs, temp_paths, strict=True):
            temp.replace(path)
    except OSError:
        for temp in temp_paths:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        for path, _ in outputs:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _md(value: Any) -> str:
    if value is None:
        return "null"
    return str(value).replace("|", "\\|").replace("`", "\\`")


if __name__ == "__main__":
    raise SystemExit(main())
