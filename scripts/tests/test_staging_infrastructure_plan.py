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
from scripts.staging_bootstrap_materializer import materialize_bootstrap_manifest
from scripts.staging_infrastructure_plan import (
    InfrastructurePlanError,
    build_infrastructure_plan,
    main,
    render_markdown,
    validate_bootstrap_approval_record,
)
from scripts.tests.test_staging_approval_packet import static_report
from scripts.tests.test_staging_bootstrap_materializer import repository_manifest, valid_values

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"
APPROVAL_EXAMPLES = (
    ROOT / "docs/approvals/staging-bootstrap-approval-record.example.json",
    ROOT / "docs/approvals/staging-infrastructure-approval-record.example.json",
    ROOT / "docs/approvals/staging-deployment-approval-record.example.json",
)


def manifest_and_packet() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = materialize_bootstrap_manifest(repository_manifest(), valid_values())
    packet = build_approval_packet(
        manifest,
        static_report(manifest),
        phase="bootstrap",
    )
    return manifest, packet


def packet_text_and_digest(packet: dict[str, Any]) -> tuple[str, str]:
    text = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
    return text, hashlib.sha256(text.encode()).hexdigest()


def approved_record(packet: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "schemaVersion": "rhwp.staging-bootstrap-approval/v1",
        "decision": "approved",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": "1" * 40,
        "workflowRunId": 30202041336,
        "packetSha256": digest,
        "projectId": packet["project"]["id"],
        "billingAccount": packet["project"]["billingAccount"],
        "acceptedDeferredPaths": sorted(
            entry["path"] for entry in packet["deferredValues"]
        ),
        "securityExceptions": ["mvp-staging-internal-token"],
        "deploymentApproved": False,
        "cloudMutationApproved": False,
    }


def contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, target) for item in value)
    return False


class ApprovalRecordContractTest(unittest.TestCase):
    def test_examples_remain_pending_and_non_mutating(self) -> None:
        for path in APPROVAL_EXAMPLES:
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text())
                self.assertEqual(payload["decision"], "pending")
                self.assertFalse(payload["cloudMutationApproved"])
                self.assertNotIn("token", path.read_text().lower())
                self.assertNotIn("privatekey", path.read_text().lower())

    def test_approved_record_binds_packet_digest_project_and_deferred_paths(self) -> None:
        _, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        record = approved_record(packet, digest)

        validate_bootstrap_approval_record(record, packet, digest)

    def test_rejects_pending_mismatches_and_mutation_flags(self) -> None:
        _, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        cases = (
            ("pending", lambda record: record.__setitem__("decision", "pending"), "approved"),
            ("digest", lambda record: record.__setitem__("packetSha256", "0" * 64), "digest|SHA"),
            ("project", lambda record: record.__setitem__("projectId", "different-staging-project"), "project"),
            ("billing", lambda record: record.__setitem__("billingAccount", "AAAAAA-BBBBBB-CCCCCC"), "billing"),
            (
                "deferred",
                lambda record: record.__setitem__("acceptedDeferredPaths", []),
                "deferred",
            ),
            (
                "deployment",
                lambda record: record.__setitem__("deploymentApproved", True),
                "deploymentApproved",
            ),
            (
                "mutation",
                lambda record: record.__setitem__("cloudMutationApproved", True),
                "cloudMutationApproved",
            ),
            ("unknown", lambda record: record.__setitem__("unexpected", True), "unknown"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                record = approved_record(packet, digest)
                mutate(record)
                with self.assertRaisesRegex(InfrastructurePlanError, pattern):
                    validate_bootstrap_approval_record(record, packet, digest)

    def test_rejects_sensitive_keys_without_leaking_values(self) -> None:
        _, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        record = approved_record(packet, digest)
        record["privateKey"] = "must-never-appear"

        with self.assertRaises(InfrastructurePlanError) as caught:
            validate_bootstrap_approval_record(record, packet, digest)

        self.assertIn("sensitive", str(caught.exception).lower())
        self.assertNotIn("must-never-appear", str(caught.exception))


class InfrastructurePlanGenerationTest(unittest.TestCase):
    def test_builds_ordered_plan_without_commands(self) -> None:
        manifest, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        record = approved_record(packet, digest)

        plan = build_infrastructure_plan(manifest, packet, record, digest)

        self.assertEqual(plan["schemaVersion"], "rhwp.staging-infrastructure-plan/v1")
        self.assertEqual(plan["status"], "ready-for-infrastructure-approval")
        self.assertEqual(plan["projectId"], packet["project"]["id"])
        self.assertEqual(plan["billingAccount"], packet["project"]["billingAccount"])
        self.assertEqual(plan["sourceEvidence"]["packetSha256"], digest)
        self.assertEqual(
            [stage["id"] for stage in plan["stages"]],
            [
                "project-billing",
                "api-baseline",
                "firebase-foundation",
                "service-accounts",
                "artifact-registry",
                "secret-metadata",
                "iam-bindings",
                "budget-guardrails",
                "cloud-run-prerequisites",
                "cloud-tasks-prerequisites",
                "post-bootstrap-evidence",
            ],
        )
        self.assertFalse(plan["security"]["containsCloudMutationCommands"])
        self.assertEqual(plan["security"]["mutationCommands"], [])
        self.assertFalse(contains_key(plan, "command"))
        self.assertFalse(contains_key(plan, "commands"))

    def test_preserves_all_deferred_paths_with_resolution_phases(self) -> None:
        manifest, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        plan = build_infrastructure_plan(
            manifest,
            packet,
            approved_record(packet, digest),
            digest,
        )

        expected = {entry["path"] for entry in packet["deferredValues"]}
        actual = {entry["path"] for entry in plan["postBootstrapRequiredValues"]}
        self.assertEqual(actual, expected)
        self.assertTrue(all(entry["resolutionPhase"] in {
            "infrastructure-bootstrap",
            "image-build",
            "initial-deployment",
        } for entry in plan["postBootstrapRequiredValues"]))

        iam_stage = next(stage for stage in plan["stages"] if stage["id"] == "iam-bindings")
        self.assertEqual(iam_stage["resources"], manifest["iam"]["bindings"])
        budget_stage = next(stage for stage in plan["stages"] if stage["id"] == "budget-guardrails")
        self.assertEqual(budget_stage["resources"]["currency"], "KRW")
        self.assertEqual(budget_stage["resources"]["amount"], 50000)

    def test_rendered_markdown_states_approval_boundary(self) -> None:
        manifest, packet = manifest_and_packet()
        _, digest = packet_text_and_digest(packet)
        plan = build_infrastructure_plan(
            manifest,
            packet,
            approved_record(packet, digest),
            digest,
        )

        markdown = render_markdown(plan)

        self.assertIn("# rhwp Staging Infrastructure Bootstrap Plan", markdown)
        self.assertIn("ready-for-infrastructure-approval", markdown)
        self.assertIn("does not authorize cloud mutation", markdown)
        self.assertIn("## Ordered stages", markdown)
        self.assertNotIn("gcloud ", markdown)
        self.assertNotIn("firebase deploy", markdown)


class InfrastructurePlanCliAndWorkflowTest(unittest.TestCase):
    def test_cli_writes_atomic_json_and_markdown(self) -> None:
        manifest, packet = manifest_and_packet()
        packet_text, digest = packet_text_and_digest(packet)
        record = approved_record(packet, digest)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            packet_path = root / "packet.json"
            approval_path = root / "approval.json"
            json_output = root / "nested/plan.json"
            markdown_output = root / "nested/plan.md"
            manifest_path.write_text(json.dumps(manifest))
            packet_path.write_text(packet_text)
            approval_path.write_text(json.dumps(record))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--manifest", str(manifest_path),
                    "--bootstrap-packet", str(packet_path),
                    "--bootstrap-approval-record", str(approval_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertTrue(json_output.exists())
            self.assertTrue(markdown_output.exists())
            self.assertFalse(json_output.with_name(json_output.name + ".tmp").exists())
            self.assertFalse(markdown_output.with_name(markdown_output.name + ".tmp").exists())
            payload = json.loads(json_output.read_text())
            self.assertEqual(payload["status"], "ready-for-infrastructure-approval")
            self.assertIn('"mutationCommands": []', stdout.getvalue())

    def test_cli_rejects_tampered_packet_without_partial_output(self) -> None:
        manifest, packet = manifest_and_packet()
        packet_text, digest = packet_text_and_digest(packet)
        record = approved_record(packet, digest)
        tampered = copy.deepcopy(packet)
        tampered["budget"]["amount"] = 999999

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            packet_path = root / "packet.json"
            approval_path = root / "approval.json"
            json_output = root / "plan.json"
            markdown_output = root / "plan.md"
            manifest_path.write_text(json.dumps(manifest))
            packet_path.write_text(json.dumps(tampered, indent=2) + "\n")
            approval_path.write_text(json.dumps(record))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main([
                    "--manifest", str(manifest_path),
                    "--bootstrap-packet", str(packet_path),
                    "--bootstrap-approval-record", str(approval_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 1)
            self.assertFalse(json_output.exists())
            self.assertFalse(markdown_output.exists())
            self.assertIn("digest", stderr.getvalue().lower())

    def test_workflow_has_protected_plan_only_job_without_cloud_auth(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        self.assertIn("infrastructure-plan", workflow)
        self.assertIn("bootstrap_packet_path", workflow)
        self.assertIn("bootstrap_approval_record_path", workflow)
        self.assertIn("environment: staging-infrastructure", workflow)
        self.assertIn("python3 scripts/staging_infrastructure_plan.py", workflow)
        self.assertIn("staging-infrastructure-bootstrap-plan", workflow)

        start = workflow.index("  infrastructure_plan:")
        end = workflow.index("  live:", start)
        job = workflow[start:end]
        for forbidden in (
            "google-github-actions/auth",
            "setup-gcloud",
            "firebase-tools",
            "id-token: write",
            "gcloud ",
            "firebase deploy",
        ):
            self.assertNotIn(forbidden, job)


if __name__ == "__main__":
    unittest.main()
