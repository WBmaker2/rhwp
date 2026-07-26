from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts.staging_bootstrap_approval_record import (
    build_approval_record,
    packet_sha256,
)
from scripts.staging_bootstrap_operator import (
    BootstrapOperatorError,
    build_pending_review_draft,
    evaluate_operator_status,
    main,
    render_markdown,
)
from scripts.tests.test_staging_bootstrap_approval_record import (
    approved_review,
    bootstrap_packet,
    packet_bytes,
)
from scripts.tests.test_staging_bootstrap_readiness import COMMIT_SHA, ready_payload

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"


def packet_evidence() -> dict[str, Any]:
    return {
        "workflowRunId": 9005,
        "commitSha": COMMIT_SHA,
        "artifactName": "staging-approval-packet-bootstrap",
    }


def approved_review_for_operator(packet: dict[str, Any], raw: bytes) -> dict[str, Any]:
    review = approved_review(packet, packet_sha256(raw))
    review["commitSha"] = COMMIT_SHA
    review["workflowRunId"] = packet_evidence()["workflowRunId"]
    return review


class OperatorLifecycleStatusTest(unittest.TestCase):
    def assert_safe(self, report: dict[str, Any]) -> None:
        self.assertFalse(report["cloudMutationApproved"])
        self.assertFalse(report["deploymentApproved"])
        self.assertEqual(report["mutationCommands"], [])

    def test_missing_readiness_collects_operating_values_without_invention(self) -> None:
        report = evaluate_operator_status(None)

        self.assertEqual(report["schemaVersion"], "rhwp.staging-bootstrap-operator-status/v1")
        self.assertEqual(report["status"], "collect-operating-values")
        self.assertEqual(report["nextAction"]["id"], "collect-operating-values")
        self.assertIsNone(report["projectId"])
        self.assertIsNone(report["billingAccountMasked"])
        self.assert_safe(report)

    def test_environment_pending_maps_to_environment_configuration(self) -> None:
        readiness = ready_payload()
        environment = readiness["protectedEnvironment"]
        environment["configured"] = False
        environment["requiredReviewerCount"] = 0
        environment["branchRestricted"] = False
        environment["variableNames"] = []

        report = evaluate_operator_status(readiness)

        self.assertEqual(report["status"], "configure-staging-bootstrap-environment")
        self.assertEqual(report["readinessStatus"], "ready-for-protected-environment")
        self.assertEqual(report["nextAction"]["id"], "configure-staging-bootstrap-environment")
        self.assert_safe(report)

    def test_ready_readiness_without_packet_requests_actual_packet(self) -> None:
        report = evaluate_operator_status(ready_payload())

        self.assertEqual(report["status"], "generate-actual-bootstrap-packet")
        self.assertEqual(report["readinessStatus"], "ready-for-bootstrap-packet")
        self.assertEqual(report["nextAction"]["workflow"]["approvalPhase"], "bootstrap")
        self.assertFalse(report["nextAction"]["workflow"]["liveCheck"])
        self.assert_safe(report)

    def test_valid_packet_requests_human_review_and_builds_pending_draft(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        evidence = packet_evidence()

        report = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=evidence["workflowRunId"],
            packet_commit_sha=evidence["commitSha"],
        )
        draft = build_pending_review_draft(
            packet,
            raw,
            commit_sha=evidence["commitSha"],
            workflow_run_id=evidence["workflowRunId"],
        )

        self.assertEqual(report["status"], "review-actual-bootstrap-packet")
        self.assertEqual(report["packetSha256"], packet_sha256(raw))
        self.assertEqual(report["nextAction"]["id"], "review-actual-bootstrap-packet")
        self.assertEqual(draft["decision"], "pending")
        self.assertIsNone(draft["approvedAt"])
        self.assertEqual(draft["approvedBy"], [])
        self.assertEqual(draft["commitSha"], COMMIT_SHA)
        self.assertEqual(draft["workflowRunId"], evidence["workflowRunId"])
        self.assertEqual(draft["expectedPacketSha256"], packet_sha256(raw))
        self.assertTrue(all(value is False for value in draft["acknowledgements"].values()))
        self.assert_safe(report)

    def test_approved_review_requests_approval_record_generation(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        evidence = packet_evidence()
        review = approved_review_for_operator(packet, raw)

        report = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=evidence["workflowRunId"],
            packet_commit_sha=evidence["commitSha"],
            review=review,
        )

        self.assertEqual(report["status"], "generate-bootstrap-approval-record")
        self.assertEqual(report["nextAction"]["id"], "generate-bootstrap-approval-record")
        self.assertEqual(report["nextAction"]["workflow"]["approvalPhase"], "bootstrap-review")
        self.assert_safe(report)

    def test_valid_approval_record_is_ready_for_infrastructure_plan(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        evidence = packet_evidence()
        review = approved_review_for_operator(packet, raw)
        record = build_approval_record(packet, review, packet_sha256(raw))

        report = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=evidence["workflowRunId"],
            packet_commit_sha=evidence["commitSha"],
            review=review,
            approval_record=record,
        )

        self.assertEqual(report["status"], "ready-for-infrastructure-plan")
        self.assertEqual(report["nextAction"]["id"], "generate-infrastructure-plan")
        self.assertEqual(report["approvalRecordSchema"], "rhwp.staging-bootstrap-approval/v1")
        self.assert_safe(report)


class OperatorBlockingTest(unittest.TestCase):
    def assert_blocked(self, report: dict[str, Any], expected: str) -> None:
        self.assertEqual(report["status"], "blocked")
        self.assertIn(expected.lower(), " ".join(report["blockedReasons"]).lower())
        self.assertFalse(report["cloudMutationApproved"])
        self.assertFalse(report["deploymentApproved"])
        self.assertEqual(report["mutationCommands"], [])

    def test_blocked_readiness_is_preserved(self) -> None:
        readiness = ready_payload()
        readiness["workflows"][0]["conclusion"] = "cancelled"

        self.assert_blocked(evaluate_operator_status(readiness), "workflow")

    def test_packet_requires_matching_source_commit_and_positive_run(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)

        wrong_commit = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=9005,
            packet_commit_sha="8" * 40,
        )
        self.assert_blocked(wrong_commit, "commit")

        zero_run = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=0,
            packet_commit_sha=COMMIT_SHA,
        )
        self.assert_blocked(zero_run, "workflow run")

    def test_review_digest_mismatch_is_blocked(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        review = approved_review_for_operator(packet, raw)
        review["expectedPacketSha256"] = "a" * 64

        report = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=9005,
            packet_commit_sha=COMMIT_SHA,
            review=review,
        )

        self.assert_blocked(report, "digest")

    def test_tampered_approval_record_is_blocked(self) -> None:
        packet = bootstrap_packet()
        raw = packet_bytes(packet)
        review = approved_review_for_operator(packet, raw)
        record = build_approval_record(packet, review, packet_sha256(raw))
        record["packetSha256"] = "b" * 64

        report = evaluate_operator_status(
            ready_payload(),
            packet=packet,
            packet_bytes=raw,
            packet_workflow_run_id=9005,
            packet_commit_sha=COMMIT_SHA,
            review=review,
            approval_record=record,
        )

        self.assert_blocked(report, "digest")

    def test_sensitive_readiness_key_is_blocked_without_leaking_value(self) -> None:
        readiness = ready_payload()
        readiness["accessToken"] = "must-never-leak"

        report = evaluate_operator_status(readiness)
        serialized = json.dumps(report)

        self.assert_blocked(report, "sensitive")
        self.assertNotIn("must-never-leak", serialized)

    def test_review_or_record_without_packet_is_blocked(self) -> None:
        review_only = evaluate_operator_status(ready_payload(), review={})
        self.assert_blocked(review_only, "packet")

        record_only = evaluate_operator_status(ready_payload(), approval_record={})
        self.assert_blocked(record_only, "packet")


class OperatorRenderingAndCliTest(unittest.TestCase):
    def test_markdown_states_current_boundary(self) -> None:
        report = evaluate_operator_status(ready_payload())
        markdown = render_markdown(report)

        self.assertIn("# rhwp Staging Bootstrap Operator Status", markdown)
        self.assertIn("generate-actual-bootstrap-packet", markdown)
        self.assertIn("does not authorize cloud mutation", markdown)
        self.assertNotIn("gcloud ", markdown)
        self.assertNotIn("firebase deploy", markdown)

    def test_cli_writes_atomic_status_outputs_and_pending_review_draft(self) -> None:
        readiness = ready_payload()
        packet = bootstrap_packet()
        raw = packet_bytes(packet)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readiness_path = root / "readiness.json"
            packet_path = root / "packet.json"
            json_output = root / "nested/status.json"
            markdown_output = root / "nested/status.md"
            review_draft_output = root / "nested/review-draft.json"
            readiness_path.write_text(json.dumps(readiness))
            packet_path.write_bytes(raw)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--readiness-input", str(readiness_path),
                    "--packet", str(packet_path),
                    "--packet-workflow-run-id", "9005",
                    "--packet-commit-sha", COMMIT_SHA,
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                    "--review-draft-output", str(review_draft_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertTrue(json_output.exists())
            self.assertTrue(markdown_output.exists())
            self.assertTrue(review_draft_output.exists())
            self.assertFalse(json_output.with_name(json_output.name + ".tmp").exists())
            self.assertFalse(markdown_output.with_name(markdown_output.name + ".tmp").exists())
            self.assertFalse(review_draft_output.with_name(review_draft_output.name + ".tmp").exists())
            self.assertEqual(json.loads(json_output.read_text())["status"], "review-actual-bootstrap-packet")
            self.assertEqual(json.loads(review_draft_output.read_text())["decision"], "pending")
            self.assertIn('"mutationCommands": []', stdout.getvalue())

    def test_cli_missing_readiness_path_writes_collect_values_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_output = root / "status.json"
            markdown_output = root / "status.md"
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main([
                    "--readiness-input", str(root / "missing.json"),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertEqual(json.loads(json_output.read_text())["status"], "collect-operating-values")

    def test_cli_failure_leaves_no_partial_output(self) -> None:
        readiness = ready_payload()
        readiness["credential"] = "must-never-leak"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readiness_path = root / "readiness.json"
            json_output = root / "status.json"
            markdown_output = root / "status.md"
            readiness_path.write_text(json.dumps(readiness))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main([
                    "--readiness-input", str(readiness_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                    "--strict-blocked-exit",
                ])

            self.assertEqual(result, 1)
            self.assertFalse(json_output.exists())
            self.assertFalse(markdown_output.exists())
            self.assertNotIn("must-never-leak", stderr.getvalue())


class OperatorWorkflowContractTest(unittest.TestCase):
    def test_static_workflow_generates_test_labelled_operator_evidence(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        for marker in (
            "scripts/staging_bootstrap_operator.py",
            "docs/runbooks/staging-bootstrap-operator.md",
            "Generate deterministic staging bootstrap operator test evidence",
            "staging-bootstrap-operator-test-evidence",
            "staging-bootstrap-packet-review-draft-test.json",
        ):
            self.assertIn(marker, workflow)

    def test_operator_static_step_contains_no_cloud_auth_or_mutation(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        start = workflow.index("Generate deterministic staging bootstrap operator test evidence")
        end = workflow.index("Generate static preflight report", start)
        section = workflow[start:end]
        for forbidden in (
            "google-github-actions/auth",
            "setup-gcloud",
            "firebase-tools",
            "id-token: write",
            "gcloud ",
            "firebase deploy",
        ):
            self.assertNotIn(forbidden, section)


if __name__ == "__main__":
    unittest.main()
