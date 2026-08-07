from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts.staging_approval_packet import build_approval_packet
from scripts.staging_bootstrap_approval_record import (
    ApprovalRecordError,
    build_approval_record,
    build_review_result,
    main,
    packet_sha256,
    render_markdown,
    validate_packet_for_approval,
    validate_review_declaration,
)
from scripts.staging_bootstrap_materializer import materialize_bootstrap_manifest
from scripts.staging_infrastructure_plan import validate_bootstrap_approval_record
from scripts.tests.test_staging_approval_packet import static_report
from scripts.tests.test_staging_bootstrap_materializer import repository_manifest, valid_values

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"


def bootstrap_packet() -> dict[str, Any]:
    manifest = materialize_bootstrap_manifest(repository_manifest(), valid_values())
    return build_approval_packet(
        manifest,
        static_report(manifest),
        phase="bootstrap",
    )


def packet_bytes(packet: dict[str, Any]) -> bytes:
    return (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def approved_review(packet: dict[str, Any], digest: str) -> dict[str, Any]:
    approval = packet["approval"]
    assert isinstance(approval, dict)
    return {
        "schemaVersion": "rhwp.staging-bootstrap-packet-review/v1",
        "decision": "approved",
        "approvedAt": "2026-07-27T00:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": "1" * 40,
        "workflowRunId": 123456789,
        "artifactName": "staging-approval-packet-bootstrap",
        "expectedPacketSha256": digest,
        "expectedApprovalReference": approval["reference"],
        "acknowledgements": {
            "packetReviewed": True,
            "deferredPathsAccepted": True,
            "billingAndBudgetReviewed": True,
            "internalFlushExceptionAccepted": True,
            "cloudMutationNotApproved": True,
            "deploymentNotApproved": True,
        },
        "notes": ["documentation-safe synthetic approval fixture"],
    }


class PacketDigestAndValidationTest(unittest.TestCase):
    def test_hashes_exact_packet_bytes_without_reserializing(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        compact = json.dumps(packet, separators=(",", ":")).encode("utf-8")

        self.assertEqual(packet_sha256(raw), hashlib.sha256(raw).hexdigest())
        self.assertEqual(packet_sha256(compact), hashlib.sha256(compact).hexdigest())
        self.assertNotEqual(packet_sha256(raw), packet_sha256(compact))

    def test_accepts_only_safe_bootstrap_packet(self) -> None:
        packet = bootstrap_packet()
        validate_packet_for_approval(packet)

        cases = (
            (
                "phase",
                lambda value: value.__setitem__("phase", "deployment"),
                "phase",
            ),
            (
                "status",
                lambda value: value.__setitem__("status", "review-required"),
                "status",
            ),
            (
                "cloud mutation approval",
                lambda value: value["approval"].__setitem__("cloudMutationApproved", True),
                "cloudMutationApproved",
            ),
            (
                "deployment approval",
                lambda value: value["approval"].__setitem__("packetIsDeploymentApproval", True),
                "packetIsDeploymentApproval",
            ),
            (
                "mutation commands flag",
                lambda value: value["security"].__setitem__(
                    "containsCloudMutationCommands", True
                ),
                "containsCloudMutationCommands",
            ),
            (
                "mutation commands",
                lambda value: value["security"].__setitem__(
                    "mutationCommands", ["gcloud projects create forbidden"]
                ),
                "mutationCommands",
            ),
            (
                "preflight mode",
                lambda value: value["preflight"].__setitem__("comparisonMode", "live"),
                "comparisonMode",
            ),
            (
                "live evidence",
                lambda value: value["preflight"].__setitem__("live", {"status": "pass"}),
                "live",
            ),
            (
                "budget currency",
                lambda value: value["budget"].__setitem__("currency", "USD"),
                "KRW",
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(packet)
                mutate(candidate)
                with self.assertRaisesRegex(ApprovalRecordError, pattern):
                    validate_packet_for_approval(candidate)

    def test_rejects_duplicate_or_unknown_deferred_paths(self) -> None:
        packet = bootstrap_packet()
        deferred = packet["deferredValues"]
        assert isinstance(deferred, list)

        duplicate = copy.deepcopy(packet)
        duplicate["deferredValues"].append(copy.deepcopy(duplicate["deferredValues"][0]))
        with self.assertRaisesRegex(ApprovalRecordError, "duplicate"):
            validate_packet_for_approval(duplicate)

        unknown = copy.deepcopy(packet)
        unknown["deferredValues"].append(
            {"path": "manifest.iam.forbidden", "reason": "must not be accepted"}
        )
        with self.assertRaisesRegex(ApprovalRecordError, "deferred"):
            validate_packet_for_approval(unknown)


class ReviewDeclarationValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = bootstrap_packet()
        self.digest = packet_sha256(packet_bytes(self.packet))
        self.review = approved_review(self.packet, self.digest)

    def test_accepts_exact_approved_review_contract(self) -> None:
        validate_review_declaration(self.review, self.packet)

    def test_rejects_pending_malformed_or_unacknowledged_review(self) -> None:
        cases = (
            (
                "pending decision",
                lambda value: value.__setitem__("decision", "pending"),
                "decision",
            ),
            (
                "bad timestamp",
                lambda value: value.__setitem__("approvedAt", "2026-07-27"),
                "approvedAt",
            ),
            (
                "empty approvers",
                lambda value: value.__setitem__("approvedBy", []),
                "approvedBy",
            ),
            (
                "duplicate approvers",
                lambda value: value.__setitem__(
                    "approvedBy", ["repository-owner", "repository-owner"]
                ),
                "duplicate",
            ),
            (
                "bad commit",
                lambda value: value.__setitem__("commitSha", "bad"),
                "commitSha",
            ),
            (
                "bad run",
                lambda value: value.__setitem__("workflowRunId", 0),
                "workflowRunId",
            ),
            (
                "wrong artifact",
                lambda value: value.__setitem__("artifactName", "different-artifact"),
                "artifactName",
            ),
            (
                "bad digest format",
                lambda value: value.__setitem__("expectedPacketSha256", "bad"),
                "expectedPacketSha256",
            ),
            (
                "wrong approval reference",
                lambda value: value.__setitem__(
                    "expectedApprovalReference", "different-approval"
                ),
                "approvalReference",
            ),
            (
                "false acknowledgement",
                lambda value: value["acknowledgements"].__setitem__(
                    "deferredPathsAccepted", False
                ),
                "deferredPathsAccepted",
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.review)
                mutate(candidate)
                with self.assertRaisesRegex(ApprovalRecordError, pattern):
                    validate_review_declaration(candidate, self.packet)

    def test_rejects_sensitive_key_without_leaking_value(self) -> None:
        candidate = copy.deepcopy(self.review)
        candidate["credential"] = "must-never-appear"

        with self.assertRaises(ApprovalRecordError) as caught:
            validate_review_declaration(candidate, self.packet)

        self.assertIn("sensitive", str(caught.exception).lower())
        self.assertNotIn("must-never-appear", str(caught.exception))


class ApprovalRecordBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = bootstrap_packet()
        self.raw = packet_bytes(self.packet)
        self.digest = packet_sha256(self.raw)
        self.review = approved_review(self.packet, self.digest)

    def test_derives_planner_compatible_record_from_packet(self) -> None:
        record = build_approval_record(self.packet, self.review, self.digest)

        self.assertEqual(record["schemaVersion"], "rhwp.staging-bootstrap-approval/v1")
        self.assertEqual(record["decision"], "approved")
        self.assertEqual(record["packetSha256"], self.digest)
        self.assertEqual(record["projectId"], self.packet["project"]["id"])
        self.assertEqual(
            record["billingAccount"], self.packet["project"]["billingAccount"]
        )
        expected_paths = sorted(
            entry["path"] for entry in self.packet["deferredValues"]
        )
        self.assertEqual(record["acceptedDeferredPaths"], expected_paths)
        self.assertEqual(
            record["securityExceptions"], ["mvp-staging-internal-token"]
        )
        self.assertFalse(record["deploymentApproved"])
        self.assertFalse(record["cloudMutationApproved"])

        validate_bootstrap_approval_record(record, self.packet, self.digest)

    def test_rejects_packet_tampering_after_review_digest_was_recorded(self) -> None:
        tampered_raw = self.raw + b" "
        tampered_digest = packet_sha256(tampered_raw)

        with self.assertRaisesRegex(ApprovalRecordError, "digest"):
            build_approval_record(self.packet, self.review, tampered_digest)

    def test_builds_sanitized_review_result_and_markdown(self) -> None:
        record = build_approval_record(self.packet, self.review, self.digest)
        result = build_review_result(self.packet, self.review, record)
        markdown = render_markdown(result)

        self.assertEqual(
            result["schemaVersion"],
            "rhwp.staging-bootstrap-packet-review-result/v1",
        )
        self.assertEqual(result["status"], "approved-record-generated")
        self.assertEqual(result["packetSha256"], self.digest)
        self.assertEqual(result["budget"]["currency"], "KRW")
        self.assertEqual(result["budget"]["amount"], 50000)
        self.assertFalse(result["cloudMutationApproved"])
        self.assertFalse(result["deploymentApproved"])
        self.assertEqual(result["mutationCommands"], [])
        self.assertIn(self.digest, markdown)
        self.assertIn("does not authorize infrastructure mutation", markdown)
        self.assertNotIn("000000-111111-222222", markdown)


class ApprovalRecordCliTest(unittest.TestCase):
    def test_cli_writes_atomic_record_and_review_outputs(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        digest = packet_sha256(raw)
        review = approved_review(packet, digest)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "packet.json"
            review_path = root / "review.json"
            record_path = root / "nested/approval-record.json"
            result_path = root / "nested/review-result.json"
            markdown_path = root / "nested/review-result.md"
            packet_path.write_bytes(raw)
            review_path.write_text(json.dumps(review))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main([
                    "--packet", str(packet_path),
                    "--review", str(review_path),
                    "--record-output", str(record_path),
                    "--review-json-output", str(result_path),
                    "--review-markdown-output", str(markdown_path),
                ])

            self.assertEqual(exit_code, 0, stderr.getvalue())
            self.assertTrue(record_path.exists())
            self.assertTrue(result_path.exists())
            self.assertTrue(markdown_path.exists())
            for path in (record_path, result_path, markdown_path):
                self.assertFalse(path.with_name(path.name + ".tmp").exists())
            record = json.loads(record_path.read_text())
            validate_bootstrap_approval_record(record, packet, digest)
            self.assertIn('"mutationCommands": []', stdout.getvalue())

    def test_cli_leaves_no_partial_output_on_digest_mismatch(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        review = approved_review(packet, "0" * 64)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "packet.json"
            review_path = root / "review.json"
            outputs = (
                root / "record.json",
                root / "review-result.json",
                root / "review-result.md",
            )
            packet_path.write_bytes(raw)
            review_path.write_text(json.dumps(review))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main([
                    "--packet", str(packet_path),
                    "--review", str(review_path),
                    "--record-output", str(outputs[0]),
                    "--review-json-output", str(outputs[1]),
                    "--review-markdown-output", str(outputs[2]),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("digest", stderr.getvalue().lower())
            for path in outputs:
                self.assertFalse(path.exists())
                self.assertFalse(path.with_name(path.name + ".tmp").exists())


class ApprovalRecordWorkflowContractTest(unittest.TestCase):
    def test_workflow_has_protected_non_mutating_bootstrap_review_job(self) -> None:
        workflow = WORKFLOW_PATH.read_text()

        self.assertIn("- bootstrap-review", workflow)
        self.assertIn("bootstrap_review_path:", workflow)
        self.assertIn("bootstrap_review:", workflow)
        self.assertIn("environment: staging-bootstrap-approval", workflow)
        self.assertIn("staging-bootstrap-approval-review", workflow)
        self.assertIn("scripts/staging_bootstrap_approval_record.py", workflow)

        review_job = workflow.split("  bootstrap_review:", 1)[1].split("\n  infrastructure_plan:", 1)[0]
        self.assertIn("contents: read", review_job)
        self.assertNotIn("id-token: write", review_job)
        self.assertNotIn("google-github-actions/auth", review_job)
        self.assertNotIn("setup-gcloud", review_job)
        self.assertNotIn("firebase-tools", review_job)
        self.assertNotIn("gcloud ", review_job)


if __name__ == "__main__":
    unittest.main()
