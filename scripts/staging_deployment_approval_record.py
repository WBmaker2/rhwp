#!/usr/bin/env python3
"""Validate a deployment packet and build a separately scoped approval record.

The packet and evidence files are read as bytes.  The packet is never parsed and
re-serialized for digest purposes; the generated record only contains derived,
reviewable metadata and never grants authority by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.staging_deployment_binding import source_run_binding_mismatch
else:
    from staging_deployment_binding import source_run_binding_mismatch

PACKET_SCHEMA = "rhwp.staging-approval-packet/v1"
REVIEW_SCHEMA = "rhwp.staging-deployment-packet-review/v1"
EVIDENCE_SCHEMA = "rhwp.staging-deployment-evidence/v1"
RECORD_SCHEMA = "rhwp.staging-deployment-approval/v1"
RESULT_SCHEMA = "rhwp.staging-deployment-packet-review-result/v1"
PACKET_ARTIFACT = "staging-approval-packet-deployment"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SENSITIVE_MARKERS = (
    "accesstoken", "authorization", "clientsecret", "credential", "idtoken",
    "internalflushtoken", "password", "privatekey", "refreshtoken", "secretvalue",
)

PACKET_KEYS = frozenset({
    "schemaVersion", "phase", "generatedAt", "status", "deferredValues", "approval",
    "project", "firebase", "budget", "iamDiff", "secrets", "cloudRun", "cloudTasks",
    "internalFlush", "rollback", "acceptanceTests", "preflight", "security",
})
APPROVAL_KEYS = frozenset({"reference", "cloudMutationApproved", "packetIsDeploymentApproval"})
PROJECT_KEYS = frozenset({"id", "number", "billingAccount", "region", "forbiddenProjectIds"})
RUN_KEYS = frozenset({"collaboration", "documentApi", "documentWorker"})
RUN_ENTRY_KEYS = frozenset({"name", "image", "digest", "serviceAccount", "ingress", "reachability", "runtime"})
IAM_KEYS = frozenset({"principal", "role", "resource", "state", "plannedAction"})
ROLLBACK_KEYS = frozenset({"deploymentStage", "revisionIds", "dataRetentionDays", "automaticDeletionAllowed"})
ACCEPTANCE_KEYS = frozenset({"id", "name", "expected", "status"})
SECURITY_KEYS = frozenset({"readOnly", "containsCloudMutationCommands", "mutationCommands", "redactionApplied"})
REVIEW_KEYS = frozenset({
    "schemaVersion", "decision", "approvedAt", "approvedBy", "commitSha", "workflowRunId",
    "workflowRunAttempt", "artifactName", "expectedPacketSha256", "expectedApprovalReference",
    "expectedIamDiffSha256", "acceptanceEvidenceSha256", "rollbackEvidenceSha256",
    "acknowledgements", "deploymentApproved", "cloudMutationApproved", "notes",
})
ACK_KEYS = frozenset({
    "packetReviewed", "imageDigestsReviewed", "iamDiffReviewed", "acceptanceEvidenceReviewed",
    "rollbackEvidenceReviewed", "initialRollbackStateAcknowledged", "deploymentApprovalExplicit",
    "cloudMutationApprovalExplicit",
})
EVIDENCE_KEYS = frozenset({
    "schemaVersion", "evidenceKind", "status", "sourceCommitSha", "workflowRunId",
    "workflowRunAttempt", "packetSha256", "observedAt", "data", "mutationCommands", "redactionApplied",
})
RECORD_KEYS = frozenset({
    "schemaVersion", "decision", "approvedAt", "approvedBy", "commitSha", "workflowRunId",
    "workflowRunAttempt", "artifactName", "deploymentPacketSha256", "approvalReference", "projectId",
    "approvedImageDigests", "acceptedIamDiffSha256", "acceptanceEvidence", "rollbackEvidence",
    "reviewed", "deploymentApproved", "cloudMutationApproved", "mutationCommands",
})


class DeploymentApprovalError(RuntimeError):
    pass


def packet_sha256(raw: bytes) -> str:
    """Return the SHA-256 of the exact packet file bytes."""
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_json_with_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise DeploymentApprovalError(f"{label} not found: {path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeploymentApprovalError(f"{label} is not UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise DeploymentApprovalError(f"{label} root must be an object")
    return value, raw


def load_json(path: Path, label: str) -> dict[str, Any]:
    return load_json_with_bytes(path, label)[0]


def validate_deployment_packet(packet: dict[str, Any]) -> None:
    _reject_sensitive(packet, "packet")
    _exact(packet, PACKET_KEYS, "deployment packet")
    if packet.get("schemaVersion") != PACKET_SCHEMA or packet.get("phase") != "deployment":
        raise DeploymentApprovalError("packet must be a deployment v1 packet")
    if packet.get("status") != "ready-for-deployment-approval":
        raise DeploymentApprovalError("packet status must be ready-for-deployment-approval")

    approval = _mapping(packet, "approval", "packet")
    _exact(approval, APPROVAL_KEYS, "packet approval")
    _string(approval, "reference", "packet approval")
    if approval.get("cloudMutationApproved") is not False or approval.get("packetIsDeploymentApproval") is not False:
        raise DeploymentApprovalError("packet cannot carry deployment authority")

    project = _mapping(packet, "project", "packet")
    _exact(project, PROJECT_KEYS, "packet project")
    project_id = _string(project, "id", "packet project")
    if not PROJECT_RE.fullmatch(project_id) or "staging" not in project_id or "production" in project_id:
        raise DeploymentApprovalError("packet project must be a staging project")
    if not _string(project, "number", "packet project").isdigit():
        raise DeploymentApprovalError("packet project number must be numeric")
    if not re.fullmatch(r"[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}", _string(project, "billingAccount", "packet project")):
        raise DeploymentApprovalError("packet billing account format is invalid")
    if _string(project, "region", "packet project") != "asia-northeast3":
        raise DeploymentApprovalError("packet region must be asia-northeast3")
    forbidden = project.get("forbiddenProjectIds")
    if not isinstance(forbidden, list) or project_id in forbidden:
        raise DeploymentApprovalError("packet forbidden project list is invalid")

    cloud_run = _mapping(packet, "cloudRun", "packet")
    if set(cloud_run) != set(RUN_KEYS):
        raise DeploymentApprovalError("packet cloudRun services are not exact")
    for key in sorted(RUN_KEYS):
        entry = _mapping(cloud_run, key, f"packet cloudRun.{key}")
        _exact(entry, RUN_ENTRY_KEYS, f"packet cloudRun.{key}")
        image = _string(entry, "image", f"packet cloudRun.{key}")
        digest = _string(entry, "digest", f"packet cloudRun.{key}")
        if not SHA_RE.fullmatch(digest) or "@sha256:" in image or ":" in image:
            raise DeploymentApprovalError(f"packet cloudRun.{key} must use a digest-only image")
        _string(entry, "name", f"packet cloudRun.{key}")
        _string(entry, "serviceAccount", f"packet cloudRun.{key}")
        _string(entry, "ingress", f"packet cloudRun.{key}")
        _mapping(entry, "runtime", f"packet cloudRun.{key}")

    iam_diff = packet.get("iamDiff")
    if not isinstance(iam_diff, list) or not iam_diff:
        raise DeploymentApprovalError("packet iamDiff must be a non-empty array")
    for index, entry in enumerate(iam_diff):
        if not isinstance(entry, dict):
            raise DeploymentApprovalError(f"packet iamDiff[{index}] must be an object")
        _exact(entry, IAM_KEYS, f"packet iamDiff[{index}]")
        for key in IAM_KEYS:
            _string(entry, key, f"packet iamDiff[{index}]")

    rollback = _mapping(packet, "rollback", "packet")
    _exact(rollback, ROLLBACK_KEYS, "packet rollback")
    stage = _string(rollback, "deploymentStage", "packet rollback")
    revisions = rollback.get("revisionIds")
    if stage not in {"initial", "upgrade"} or not isinstance(revisions, list) or len(revisions) != 3:
        raise DeploymentApprovalError("packet rollback stage or revisionIds are invalid")
    if stage == "initial" and revisions != [None, None, None]:
        raise DeploymentApprovalError("initial packet rollback revisions must be null")
    if stage == "upgrade" and (any(not isinstance(item, str) or not item.strip() for item in revisions)):
        raise DeploymentApprovalError("upgrade packet rollback revisions must be concrete")

    acceptance = packet.get("acceptanceTests")
    if not isinstance(acceptance, list) or not acceptance:
        raise DeploymentApprovalError("packet acceptanceTests must be a non-empty array")
    ids: list[str] = []
    for index, entry in enumerate(acceptance):
        if not isinstance(entry, dict):
            raise DeploymentApprovalError(f"packet acceptanceTests[{index}] must be an object")
        _exact(entry, ACCEPTANCE_KEYS, f"packet acceptanceTests[{index}]")
        ids.append(_string(entry, "id", f"packet acceptanceTests[{index}]"))
        _string(entry, "name", f"packet acceptanceTests[{index}]")
        _string(entry, "expected", f"packet acceptanceTests[{index}]")
        if entry.get("status") not in {"pending", "pass", "fail"}:
            raise DeploymentApprovalError("packet acceptance status is invalid")
    if len(ids) != len(set(ids)):
        raise DeploymentApprovalError("packet acceptance test IDs must be unique")

    security = _mapping(packet, "security", "packet")
    _exact(security, SECURITY_KEYS, "packet security")
    if security.get("readOnly") is not True or security.get("containsCloudMutationCommands") is not False:
        raise DeploymentApprovalError("packet security must be read-only")
    if security.get("mutationCommands") != [] or security.get("redactionApplied") is not True:
        raise DeploymentApprovalError("packet security mutationCommands/redaction are invalid")
    preflight = _mapping(packet, "preflight", "packet")
    if _mapping(preflight, "static", "packet preflight").get("status") != "pass":
        raise DeploymentApprovalError("packet static preflight must pass")
    live = preflight.get("live")
    if not isinstance(live, dict) or live.get("status") not in {"pass", "review"}:
        raise DeploymentApprovalError("packet live preflight must pass or require review")


def validate_evidence(evidence: dict[str, Any], packet: dict[str, Any], packet_digest: str, kind: str) -> str:
    _reject_sensitive(evidence, f"{kind} evidence")
    _exact(evidence, EVIDENCE_KEYS, f"{kind} evidence")
    if evidence.get("schemaVersion") != EVIDENCE_SCHEMA or evidence.get("evidenceKind") != kind:
        raise DeploymentApprovalError(f"{kind} evidence schema/kind is invalid")
    source = _string(evidence, "sourceCommitSha", f"{kind} evidence")
    if not COMMIT_RE.fullmatch(source):
        raise DeploymentApprovalError(f"{kind} evidence sourceCommitSha is invalid")
    _positive_int(evidence, "workflowRunId", f"{kind} evidence")
    _positive_int(evidence, "workflowRunAttempt", f"{kind} evidence")
    if evidence.get("packetSha256") != packet_digest or not SHA_RE.fullmatch(str(evidence.get("packetSha256"))):
        raise DeploymentApprovalError(f"{kind} evidence packet SHA does not match exact packet bytes")
    observed = _string(evidence, "observedAt", f"{kind} evidence")
    if not UTC_RE.fullmatch(observed):
        raise DeploymentApprovalError(f"{kind} evidence observedAt must be UTC")
    if evidence.get("mutationCommands") != [] or evidence.get("redactionApplied") is not True:
        raise DeploymentApprovalError(f"{kind} evidence must be redacted and mutation-free")
    data = _mapping(evidence, "data", f"{kind} evidence")
    if kind == "acceptance":
        statuses = data.get("testStatuses")
        expected = [str(item["id"]) for item in packet["acceptanceTests"]]
        if not isinstance(statuses, list) or sorted(str(item.get("id")) for item in statuses if isinstance(item, dict)) != sorted(expected):
            raise DeploymentApprovalError("acceptance evidence test IDs do not match packet")
        if any(not isinstance(item, dict) or item.get("status") not in {"pending", "pass", "fail"} for item in statuses):
            raise DeploymentApprovalError("acceptance evidence contains an invalid status")
        if evidence.get("status") not in {"pending", "pass", "fail"}:
            raise DeploymentApprovalError("acceptance evidence status is invalid")
    else:
        rollback = packet["rollback"]
        if evidence.get("status") not in {"not-applicable-initial", "pass", "fail"}:
            raise DeploymentApprovalError("rollback evidence status is invalid")
        if data.get("deploymentStage") != rollback["deploymentStage"] or data.get("revisionIds") != rollback["revisionIds"]:
            raise DeploymentApprovalError("rollback evidence does not match packet")
        if rollback["deploymentStage"] == "initial" and evidence.get("status") != "not-applicable-initial":
            raise DeploymentApprovalError("initial rollback evidence must be not-applicable-initial")
    return canonical_sha256(evidence)


def validate_review(review: dict[str, Any], packet: dict[str, Any], digest: str, iam_digest: str, acceptance_digest: str, rollback_digest: str) -> None:
    _reject_sensitive(review, "review")
    _exact(review, REVIEW_KEYS, "deployment review declaration")
    if review.get("schemaVersion") != REVIEW_SCHEMA or review.get("decision") not in {"pending", "approved", "rejected"}:
        raise DeploymentApprovalError("review schema or decision is invalid")
    _string(review, "commitSha", "review")
    if not COMMIT_RE.fullmatch(review["commitSha"]):
        raise DeploymentApprovalError("review commitSha is invalid")
    _positive_int(review, "workflowRunId", "review")
    _positive_int(review, "workflowRunAttempt", "review")
    if review.get("artifactName") != PACKET_ARTIFACT or review.get("expectedPacketSha256") != digest:
        raise DeploymentApprovalError("review packet artifact/SHA does not match exact packet bytes")
    if review.get("expectedApprovalReference") != packet["approval"]["reference"]:
        raise DeploymentApprovalError("review approval reference does not match packet")
    if review.get("expectedIamDiffSha256") != iam_digest or not SHA_RE.fullmatch(str(review.get("expectedIamDiffSha256"))):
        raise DeploymentApprovalError("review IAM diff SHA does not match canonical packet diff")
    if review.get("acceptanceEvidenceSha256") != acceptance_digest or review.get("rollbackEvidenceSha256") != rollback_digest:
        raise DeploymentApprovalError("review evidence SHA does not match exact evidence content")
    ack = _mapping(review, "acknowledgements", "review")
    _exact(ack, ACK_KEYS, "review acknowledgements")
    if review.get("decision") == "approved":
        _string(review, "approvedAt", "review")
        if not UTC_RE.fullmatch(review["approvedAt"]) or not _nonempty_unique_strings(review.get("approvedBy")):
            raise DeploymentApprovalError("approved review requires UTC time and approver")
        if any(ack.get(key) is not True for key in ACK_KEYS):
            raise DeploymentApprovalError("approved review requires every acknowledgement")
    else:
        if review.get("approvedAt") is not None or review.get("approvedBy") != []:
            raise DeploymentApprovalError("non-approved review cannot contain approval identity/time")
    if review.get("deploymentApproved") is True and review.get("cloudMutationApproved") is not True:
        raise DeploymentApprovalError("deployment approval requires cloudMutationApproved=true")
    if review.get("cloudMutationApproved") is True and review.get("deploymentApproved") is not True:
        raise DeploymentApprovalError("cloud mutation approval requires deploymentApproved=true")
    if review.get("decision") != "approved" and (review.get("deploymentApproved") or review.get("cloudMutationApproved")):
        raise DeploymentApprovalError("non-approved review cannot authorize deployment")
    if not isinstance(review.get("notes"), list) or any(not isinstance(item, str) for item in review["notes"]):
        raise DeploymentApprovalError("review notes must be an array of strings")


def build_approval_record(packet: dict[str, Any], packet_raw: bytes, review: dict[str, Any], acceptance: dict[str, Any], rollback: dict[str, Any]) -> dict[str, Any]:
    validate_deployment_packet(packet)
    digest = packet_sha256(packet_raw)
    iam_digest = canonical_sha256(packet["iamDiff"])
    acceptance_digest = validate_evidence(acceptance, packet, digest, "acceptance")
    rollback_digest = validate_evidence(rollback, packet, digest, "rollback")
    validate_review(review, packet, digest, iam_digest, acceptance_digest, rollback_digest)
    binding_error = source_run_binding_mismatch(review, acceptance, rollback)
    if binding_error:
        raise DeploymentApprovalError(binding_error)
    images = [f"{packet['cloudRun'][key]['image']}@sha256:{packet['cloudRun'][key]['digest']}" for key in ("collaboration", "documentApi", "documentWorker")]
    record = {
        "schemaVersion": RECORD_SCHEMA,
        "decision": review["decision"],
        "approvedAt": review["approvedAt"],
        "approvedBy": list(review["approvedBy"]),
        "commitSha": review["commitSha"],
        "workflowRunId": review["workflowRunId"],
        "workflowRunAttempt": review["workflowRunAttempt"],
        "artifactName": review["artifactName"],
        "deploymentPacketSha256": digest,
        "approvalReference": packet["approval"]["reference"],
        "projectId": packet["project"]["id"],
        "approvedImageDigests": images,
        "acceptedIamDiffSha256": iam_digest,
        "acceptanceEvidence": {"status": acceptance["status"], "sha256": acceptance_digest},
        "rollbackEvidence": {"status": rollback["status"], "sha256": rollback_digest, "revisionIds": list(rollback["data"]["revisionIds"])},
        "reviewed": dict(review["acknowledgements"]),
        "deploymentApproved": review["deploymentApproved"],
        "cloudMutationApproved": review["cloudMutationApproved"],
        "mutationCommands": [],
    }
    _exact(record, RECORD_KEYS, "generated deployment approval record")
    return record


def build_review_result(record: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    if record["decision"] == "rejected":
        status = "rejected"
    elif record["decision"] == "pending":
        status = "pending-review"
    elif record["deploymentApproved"]:
        status = "ready-for-deployment-workflow"
    else:
        status = "reviewed-awaiting-deployment-approval"
    return {
        "schemaVersion": RESULT_SCHEMA,
        "status": status,
        "approvalReference": record["approvalReference"],
        "deploymentPacketSha256": record["deploymentPacketSha256"],
        "sourceCommitSha": record["commitSha"],
        "workflowRunId": record["workflowRunId"],
        "workflowRunAttempt": record["workflowRunAttempt"],
        "decision": record["decision"],
        "deploymentApproved": record["deploymentApproved"],
        "cloudMutationApproved": record["cloudMutationApproved"],
        "mutationCommands": [],
        "notes": list(review["notes"]),
    }


def render_markdown(result: dict[str, Any], record: dict[str, Any]) -> str:
    lines = [
        "# rhwp Staging Deployment Packet Review",
        "",
        "> This record is separate from bootstrap and infrastructure approval records.",
        "",
        f"- Status: `{result['status']}`",
        f"- Decision: `{record['decision']}`",
        f"- Approval reference: `{record['approvalReference']}`",
        f"- Packet SHA-256: `{record['deploymentPacketSha256']}`",
        f"- Source commit: `{record['commitSha']}`",
        f"- Workflow run: `{record['workflowRunId']}` (attempt `{record['workflowRunAttempt']}`)",
        f"- Project: `{record['projectId']}`",
        "",
        "## Evidence bindings",
        "",
        f"- IAM diff SHA-256: `{record['acceptedIamDiffSha256']}`",
        f"- Acceptance evidence: `{record['acceptanceEvidence']['status']}` / `{record['acceptanceEvidence']['sha256']}`",
        f"- Rollback evidence: `{record['rollbackEvidence']['status']}` / `{record['rollbackEvidence']['sha256']}`",
        f"- Rollback revision IDs: `{json.dumps(record['rollbackEvidence']['revisionIds'], ensure_ascii=False)}`",
        "",
        "## Authority boundary",
        "",
        f"- Deployment approved: `{str(record['deploymentApproved']).lower()}`",
        f"- Cloud mutation approved: `{str(record['cloudMutationApproved']).lower()}`",
        "- Mutation commands: `[]`",
        "- A protected deployment Environment and same-run artifact validation are still required.",
        "- Acceptance tests are post-deployment evidence; a pending pre-deployment plan is never promoted to pass.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a deployment packet and generate its separate approval record")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--rollback-evidence", type=Path, required=True)
    parser.add_argument("--record-output", type=Path, required=True)
    parser.add_argument("--review-json-output", type=Path, required=True)
    parser.add_argument("--review-markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = (args.record_output, args.review_json_output, args.review_markdown_output)
    try:
        packet, raw = load_json_with_bytes(args.packet, "deployment packet")
        review = load_json(args.review, "deployment review declaration")
        acceptance = load_json(args.acceptance_evidence, "acceptance evidence")
        rollback = load_json(args.rollback_evidence, "rollback evidence")
        record = build_approval_record(packet, raw, review, acceptance, rollback)
        result = build_review_result(record, review)
        _atomic_write_bundle({
            args.record_output: json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            args.review_json_output: json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            args.review_markdown_output: render_markdown(result, record),
        })
    except (DeploymentApprovalError, OSError) as error:
        _cleanup(outputs)
        print(f"staging deployment approval record failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": result["status"],
        "decision": result["decision"],
        "approvalReference": result["approvalReference"],
        "deploymentPacketSha256": result["deploymentPacketSha256"],
        "recordOutput": str(args.record_output),
        "reviewJsonOutput": str(args.review_json_output),
        "reviewMarkdownOutput": str(args.review_markdown_output),
        "deploymentApproved": result["deploymentApproved"],
        "cloudMutationApproved": result["cloudMutationApproved"],
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def _exact(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    missing, unknown = sorted(expected - set(value)), sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise DeploymentApprovalError(f"{label} keys are invalid: {'; '.join(details)}")


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise DeploymentApprovalError(f"{label}.{key} must be an object")
    return item


def _string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise DeploymentApprovalError(f"{label}.{key} must be a non-empty string")
    return item


def _positive_int(value: dict[str, Any], key: str, label: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise DeploymentApprovalError(f"{label}.{key} must be a positive integer")
    return item


def _nonempty_unique_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value) and len(value) == len(set(value))


def _reject_sensitive(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child = f"{path}.{key}"
            if any(marker in normalized for marker in SENSITIVE_MARKERS):
                raise DeploymentApprovalError(f"sensitive key is not allowed at {child}")
            _reject_sensitive(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, f"{path}[{index}]")
    elif isinstance(value, str) and ("-----BEGIN PRIVATE KEY-----" in value or value.startswith("Bearer ")):
        raise DeploymentApprovalError(f"sensitive value is not allowed at {path}")


def _atomic_write_bundle(contents: dict[Path, str]) -> None:
    temporary: list[Path] = []
    try:
        for path, content in contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            temporary.append(tmp)
        for path in contents:
            path.with_name(path.name + ".tmp").replace(path)
    except OSError:
        for path in temporary:
            path.unlink(missing_ok=True)
        raise


def _cleanup(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
