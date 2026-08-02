#!/usr/bin/env python3
"""Prepare a same-run, approval-bound deployment input artifact.

This command is intentionally cloud-free.  It verifies the raw deployment packet,
review declaration, evidence, and generated approval record before copying the
input bytes unchanged into a private workflow artifact.  The protected deploy job
must consume that artifact rather than re-reading arbitrary workflow inputs.
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
    from scripts.staging_deployment_approval_record import (
        PACKET_ARTIFACT,
        DeploymentApprovalError,
        build_approval_record,
        load_json_with_bytes,
        packet_sha256,
    )
else:
    from staging_deployment_approval_record import (
        PACKET_ARTIFACT,
        DeploymentApprovalError,
        build_approval_record,
        load_json_with_bytes,
        packet_sha256,
    )


PREPARED_SCHEMA = "rhwp.staging-deployment-input/v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class DeploymentPrepareError(RuntimeError):
    """Raised when a deployment input cannot be bound exactly to approval."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_commit(value: str, label: str) -> str:
    if not COMMIT_RE.fullmatch(value):
        raise DeploymentPrepareError(f"{label} must be a lowercase commit SHA")
    return value


def _require_sha(value: str, label: str) -> str:
    if not SHA_RE.fullmatch(value):
        raise DeploymentPrepareError(f"{label} must be a lowercase SHA-256")
    return value


def _require_positive(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DeploymentPrepareError(f"{label} must be a positive integer")
    return value


def _load_paths(paths: dict[str, Path]) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    values: dict[str, dict[str, Any]] = {}
    raw_values: dict[str, bytes] = {}
    for label, path in paths.items():
        value, raw = load_json_with_bytes(path, label)
        values[label] = value
        raw_values[label] = raw
    return values, raw_values


def prepare_bundle(
    *,
    packet_path: Path,
    review_path: Path,
    acceptance_path: Path,
    rollback_path: Path,
    record_path: Path,
    expected_source_commit: str,
    expected_workflow_run_id: int,
    expected_workflow_run_attempt: int,
    expected_artifact_name: str,
    expected_artifact_digest: str,
    expected_packet_sha256: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Validate all bindings and return derived metadata plus exact input bytes."""
    expected_source_commit = _require_commit(expected_source_commit, "source commit")
    expected_workflow_run_id = _require_positive(expected_workflow_run_id, "workflow run ID")
    expected_workflow_run_attempt = _require_positive(expected_workflow_run_attempt, "workflow run attempt")
    expected_packet_sha256 = _require_sha(expected_packet_sha256, "packet SHA-256")
    if expected_artifact_name != PACKET_ARTIFACT:
        raise DeploymentPrepareError(f"artifact name must be {PACKET_ARTIFACT}")
    if not ARTIFACT_DIGEST_RE.fullmatch(expected_artifact_digest):
        raise DeploymentPrepareError("artifact digest must be sha256:<64 lowercase hex>")

    paths = {
        "deployment packet": packet_path,
        "deployment review": review_path,
        "acceptance evidence": acceptance_path,
        "rollback evidence": rollback_path,
        "deployment approval record": record_path,
    }
    values, raw_values = _load_paths(paths)
    packet = values["deployment packet"]
    packet_raw = raw_values["deployment packet"]
    review = values["deployment review"]
    acceptance = values["acceptance evidence"]
    rollback = values["rollback evidence"]
    record = values["deployment approval record"]

    actual_packet_sha256 = packet_sha256(packet_raw)
    if actual_packet_sha256 != expected_packet_sha256:
        raise DeploymentPrepareError("packet SHA-256 does not match exact packet bytes")
    rebuilt = build_approval_record(packet, packet_raw, review, acceptance, rollback)
    if record != rebuilt:
        raise DeploymentPrepareError("approval record does not exactly match regenerated record")
    if record.get("decision") != "approved" or record.get("deploymentApproved") is not True:
        raise DeploymentPrepareError("deployment approval record is not approved")
    if record.get("cloudMutationApproved") is not True or record.get("mutationCommands") != []:
        raise DeploymentPrepareError("deployment approval authority or mutationCommands is invalid")

    expected_binding = {
        "commitSha": expected_source_commit,
        "workflowRunId": expected_workflow_run_id,
        "workflowRunAttempt": expected_workflow_run_attempt,
        "artifactName": expected_artifact_name,
        "deploymentPacketSha256": expected_packet_sha256,
    }
    actual_binding = {
        "commitSha": record.get("commitSha"),
        "workflowRunId": record.get("workflowRunId"),
        "workflowRunAttempt": record.get("workflowRunAttempt"),
        "artifactName": record.get("artifactName"),
        "deploymentPacketSha256": record.get("deploymentPacketSha256"),
    }
    if actual_binding != expected_binding:
        raise DeploymentPrepareError("approval source/run/artifact/packet binding does not match inputs")

    prepared = {
        "schemaVersion": PREPARED_SCHEMA,
        "approvalReference": record["approvalReference"],
        "sourceCommitSha": record["commitSha"],
        "packetWorkflowRunId": record["workflowRunId"],
        "packetWorkflowRunAttempt": record["workflowRunAttempt"],
        "packetArtifactName": expected_artifact_name,
        "packetArtifactDigest": expected_artifact_digest,
        "packetSha256": actual_packet_sha256,
        "approvalRecordSha256": _sha256(raw_values["deployment approval record"]),
        "reviewDeclarationSha256": _sha256(raw_values["deployment review"]),
        "acceptanceEvidenceSha256": _sha256(raw_values["acceptance evidence"]),
        "rollbackEvidenceSha256": _sha256(raw_values["rollback evidence"]),
        "project": {
            "id": packet["project"]["id"],
            "number": packet["project"]["number"],
            "region": packet["project"]["region"],
        },
        "cloudRun": packet["cloudRun"],
        "cloudTasks": packet["cloudTasks"],
        "firebase": {
            "webAppId": packet["firebase"]["webAppId"],
            "apiKeyReference": packet["firebase"]["apiKeyReference"],
            "storageBucket": packet["firebase"]["storageBucket"],
        },
        "iamDiff": packet["iamDiff"],
        "rollback": packet["rollback"],
        "approval": {
            "decision": record["decision"],
            "deploymentApproved": record["deploymentApproved"],
            "cloudMutationApproved": record["cloudMutationApproved"],
        },
        "mutationCommands": [],
    }
    exact_bytes = {
        "staging-approval-packet.json": packet_raw,
        "deployment-review.approved.json": raw_values["deployment review"],
        "acceptance-evidence.json": raw_values["acceptance evidence"],
        "rollback-evidence.json": raw_values["rollback evidence"],
        "staging-deployment-approval-record.json": raw_values["deployment approval record"],
    }
    return prepared, exact_bytes


def _write_bundle(output_dir: Path, prepared: dict[str, Any], exact_bytes: dict[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "deployment-input.json"
    temp_json = json_path.with_name(json_path.name + ".tmp")
    temp_json.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_json.replace(json_path)
    for name, content in exact_bytes.items():
        target = output_dir / name
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an exact, approval-bound deployment artifact")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--rollback-evidence", type=Path, required=True)
    parser.add_argument("--approval-record", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-workflow-run-id", type=int, required=True)
    parser.add_argument("--expected-workflow-run-attempt", type=int, required=True)
    parser.add_argument("--expected-artifact-name", required=True)
    parser.add_argument("--expected-artifact-digest", required=True)
    parser.add_argument("--expected-packet-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepared, exact_bytes = prepare_bundle(
            packet_path=args.packet,
            review_path=args.review,
            acceptance_path=args.acceptance_evidence,
            rollback_path=args.rollback_evidence,
            record_path=args.approval_record,
            expected_source_commit=args.expected_source_commit,
            expected_workflow_run_id=args.expected_workflow_run_id,
            expected_workflow_run_attempt=args.expected_workflow_run_attempt,
            expected_artifact_name=args.expected_artifact_name,
            expected_artifact_digest=args.expected_artifact_digest,
            expected_packet_sha256=args.expected_packet_sha256,
        )
        _write_bundle(args.output_dir, prepared, exact_bytes)
    except (DeploymentApprovalError, DeploymentPrepareError, OSError) as error:
        print(f"staging deployment prepare failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "ready-for-protected-deployment",
        "outputDir": str(args.output_dir),
        "sourceCommitSha": prepared["sourceCommitSha"],
        "packetWorkflowRunId": prepared["packetWorkflowRunId"],
        "packetSha256": prepared["packetSha256"],
        "approvalReference": prepared["approvalReference"],
        "deploymentApproved": prepared["approval"]["deploymentApproved"],
        "cloudMutationApproved": prepared["approval"]["cloudMutationApproved"],
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
