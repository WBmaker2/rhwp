from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts.staging_approval_packet import build_approval_packet
from scripts.staging_bootstrap_materializer import materialize_bootstrap_manifest
from scripts.staging_bootstrap_readiness import (
    BootstrapReadinessError,
    REQUIRED_ENVIRONMENT_VARIABLES,
    REQUIRED_WORKFLOWS,
    evaluate_readiness,
    main,
    normalize_materializer_values,
    render_markdown,
)
from scripts.staging_preflight import build_preflight_report
from scripts.tests.test_staging_bootstrap_materializer import repository_manifest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"
EXAMPLE_PATH = ROOT / "deploy/staging/staging-bootstrap-readiness.example.json"
COMMIT_SHA = "7" * 40


def ready_payload() -> dict[str, Any]:
    workflows = [
        ("CI", 403),
        ("CodeQL", 402),
        ("Render Diff", 285),
        ("Staging configuration", 228),
    ]
    return {
        "schemaVersion": "rhwp.staging-bootstrap-readiness-input/v1",
        "repository": {
            "fullName": "WBmaker2/rhwp",
            "branch": "feat/firebase-collaboration-mvp-v1",
            "prNumber": 1,
            "commitSha": COMMIT_SHA,
        },
        "workflows": [
            {
                "name": name,
                "runNumber": run_number,
                "commitSha": COMMIT_SHA,
                "status": "completed",
                "conclusion": "success",
            }
            for name, run_number in workflows
        ],
        "governance": {
            "decisionStatus": "approved",
            "checklistComplete": True,
            "billingOwnerConfirmed": True,
            "budgetApprovedKrw": True,
            "notificationRecipientsConfirmed": True,
            "privacyRetentionReviewed": True,
            "internalFlushExceptionAccepted": True,
        },
        "protectedEnvironment": {
            "name": "staging-bootstrap",
            "configured": True,
            "requiredReviewerCount": 1,
            "branchRestricted": True,
            "secretNames": [],
            "cloudCredentialsPresent": False,
            "idTokenWrite": False,
            "variableNames": sorted(REQUIRED_ENVIRONMENT_VARIABLES),
        },
        "values": {
            "schemaVersion": "rhwp.staging-bootstrap-values/v1",
            "project": {
                "id": "rhwp-collaboration-staging-123",
                "billingAccount": "000000-111111-222222",
                "forbiddenProjectIds": ["rhwp-production"],
            },
            "firebase": {
                "storageBucket": {
                    "planned": "rhwp-collaboration-staging-123.firebasestorage.app",
                    "observed": None,
                }
            },
            "budget": {
                "amountKrw": 50000,
                "notificationChannels": ["billing-admins@example.com"],
            },
            "operations": {
                "dataRetentionDays": 14,
                "approvalReference": "staging-bootstrap-approval-2026-07-26-001",
                "internalFlushSecurityDecision": "mvp-staging-internal-token",
            },
        },
    }


class ReadinessStatusTest(unittest.TestCase):
    def test_ready_payload_is_ready_for_bootstrap_packet(self) -> None:
        report = evaluate_readiness(ready_payload())

        self.assertEqual(report["schemaVersion"], "rhwp.staging-bootstrap-readiness/v1")
        self.assertEqual(report["status"], "ready-for-bootstrap-packet")
        self.assertEqual(report["blockedReasons"], [])
        self.assertFalse(report["cloudMutationApproved"])
        self.assertFalse(report["deploymentApproved"])
        self.assertEqual(report["mutationCommands"], [])
        self.assertEqual(set(report["requiredWorkflows"]), set(REQUIRED_WORKFLOWS))

    def test_incomplete_environment_stops_at_protected_environment_gate(self) -> None:
        payload = ready_payload()
        environment = payload["protectedEnvironment"]
        environment["configured"] = False
        environment["requiredReviewerCount"] = 0
        environment["branchRestricted"] = False
        environment["variableNames"] = []

        report = evaluate_readiness(payload)

        self.assertEqual(report["status"], "ready-for-protected-environment")
        self.assertEqual(report["blockedReasons"], [])
        self.assertTrue(report["environmentPending"])

    def test_incomplete_ci_is_blocked(self) -> None:
        payload = ready_payload()
        ci = next(item for item in payload["workflows"] if item["name"] == "CI")
        ci["status"] = "in_progress"
        ci["conclusion"] = None

        report = evaluate_readiness(payload)

        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("CI" in reason for reason in report["blockedReasons"]))

    def test_rejects_missing_duplicate_and_wrong_commit_workflows(self) -> None:
        cases = (
            (
                "missing",
                lambda payload: payload["workflows"].pop(),
                "required workflow",
            ),
            (
                "duplicate",
                lambda payload: payload["workflows"].append(copy.deepcopy(payload["workflows"][0])),
                "duplicate",
            ),
            (
                "commit",
                lambda payload: payload["workflows"][0].__setitem__("commitSha", "8" * 40),
                "commit",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                payload = ready_payload()
                mutate(payload)
                report = evaluate_readiness(payload)
                self.assertEqual(report["status"], "blocked")
                self.assertIn(expected, " ".join(report["blockedReasons"]).lower())

    def test_governance_failure_is_blocked(self) -> None:
        payload = ready_payload()
        payload["governance"]["billingOwnerConfirmed"] = False

        report = evaluate_readiness(payload)

        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("billingOwnerConfirmed" in item for item in report["blockedReasons"]))


class PlannedObservedResourceTest(unittest.TestCase):
    def test_planned_bucket_is_selected_without_manufacturing_observed_value(self) -> None:
        payload = ready_payload()

        report = evaluate_readiness(payload)
        normalized = normalize_materializer_values(payload)
        evidence = report["resources"]["firebaseStorageBucket"]

        self.assertEqual(evidence["planned"], "rhwp-collaboration-staging-123.firebasestorage.app")
        self.assertIsNone(evidence["observed"])
        self.assertEqual(evidence["effective"], evidence["planned"])
        self.assertEqual(evidence["source"], "planned")
        self.assertEqual(normalized["firebase"]["storageBucket"], evidence["planned"])

    def test_observed_bucket_is_selected_and_must_match_planned(self) -> None:
        payload = ready_payload()
        bucket = payload["values"]["firebase"]["storageBucket"]
        bucket["observed"] = bucket["planned"]

        report = evaluate_readiness(payload)
        normalized = normalize_materializer_values(payload)

        evidence = report["resources"]["firebaseStorageBucket"]
        self.assertEqual(evidence["source"], "observed")
        self.assertEqual(normalized["firebase"]["storageBucket"], bucket["observed"])

    def test_mismatched_observed_bucket_is_blocked(self) -> None:
        payload = ready_payload()
        payload["values"]["firebase"]["storageBucket"]["observed"] = (
            "rhwp-collaboration-staging-123.appspot.com"
        )

        report = evaluate_readiness(payload)

        self.assertEqual(report["status"], "blocked")
        self.assertIn("planned and observed", " ".join(report["blockedReasons"]))

    def test_rejects_invalid_resource_shape_and_production_bucket(self) -> None:
        cases = (
            (
                "shape",
                lambda payload: payload["values"]["firebase"].__setitem__(
                    "storageBucket", "legacy-string"
                ),
                "storageBucket",
            ),
            (
                "production",
                lambda payload: payload["values"]["firebase"]["storageBucket"].__setitem__(
                    "planned", "rhwp-production.firebasestorage.app"
                ),
                "project",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                payload = ready_payload()
                mutate(payload)
                report = evaluate_readiness(payload)
                self.assertEqual(report["status"], "blocked")
                self.assertIn(expected.lower(), " ".join(report["blockedReasons"]).lower())


class ProtectedEnvironmentEvidenceTest(unittest.TestCase):
    def test_requires_exact_variable_allowlist_and_no_privileged_material(self) -> None:
        cases = (
            (
                "missing variable",
                lambda env: env["variableNames"].pop(),
                "variable",
            ),
            (
                "secret",
                lambda env: env["secretNames"].append("GCP_KEY"),
                "secret",
            ),
            (
                "credential",
                lambda env: env.__setitem__("cloudCredentialsPresent", True),
                "credential",
            ),
            (
                "id token",
                lambda env: env.__setitem__("idTokenWrite", True),
                "id-token",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                payload = ready_payload()
                mutate(payload["protectedEnvironment"])
                report = evaluate_readiness(payload)
                self.assertEqual(report["status"], "blocked")
                self.assertIn(expected, " ".join(report["blockedReasons"]).lower())

    def test_rejects_sensitive_keys_without_leaking_values(self) -> None:
        payload = ready_payload()
        payload["governance"]["privateKey"] = "must-never-appear"

        with self.assertRaises(BootstrapReadinessError) as caught:
            evaluate_readiness(payload)

        self.assertIn("sensitive", str(caught.exception).lower())
        self.assertNotIn("must-never-appear", str(caught.exception))


class ReadinessIntegrationAndCliTest(unittest.TestCase):
    def test_normalized_values_feed_existing_materializer_preflight_and_packet(self) -> None:
        payload = ready_payload()
        normalized = normalize_materializer_values(payload)
        manifest = materialize_bootstrap_manifest(repository_manifest(), normalized)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            static = build_preflight_report(manifest_path, live=False)
            packet = build_approval_packet(manifest, static, phase="bootstrap")

        self.assertEqual(packet["status"], "ready-for-bootstrap-approval")
        self.assertFalse(packet["approval"]["packetIsDeploymentApproval"])
        self.assertEqual(packet["security"]["mutationCommands"], [])

    def test_cli_writes_atomic_report_markdown_and_normalized_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            json_output = root / "nested/readiness.json"
            markdown_output = root / "nested/readiness.md"
            normalized_output = root / "nested/values.json"
            input_path.write_text(json.dumps(ready_payload()))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--input", str(input_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                    "--normalized-values-output", str(normalized_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertEqual(json.loads(json_output.read_text())["status"], "ready-for-bootstrap-packet")
            self.assertIn("ready-for-bootstrap-packet", markdown_output.read_text())
            self.assertEqual(
                json.loads(normalized_output.read_text())["firebase"]["storageBucket"],
                "rhwp-collaboration-staging-123.firebasestorage.app",
            )
            self.assertIn('"mutationCommands": []', stdout.getvalue())
            for path in (json_output, markdown_output, normalized_output):
                self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_cli_does_not_emit_normalized_values_when_environment_is_pending(self) -> None:
        payload = ready_payload()
        payload["protectedEnvironment"]["configured"] = False
        payload["protectedEnvironment"]["requiredReviewerCount"] = 0
        payload["protectedEnvironment"]["branchRestricted"] = False
        payload["protectedEnvironment"]["variableNames"] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            json_output = root / "readiness.json"
            markdown_output = root / "readiness.md"
            normalized_output = root / "values.json"
            input_path.write_text(json.dumps(payload))

            result = main([
                "--input", str(input_path),
                "--json-output", str(json_output),
                "--markdown-output", str(markdown_output),
                "--normalized-values-output", str(normalized_output),
            ])

            self.assertEqual(result, 0)
            self.assertEqual(json.loads(json_output.read_text())["status"], "ready-for-protected-environment")
            self.assertFalse(normalized_output.exists())

    def test_cli_blocked_input_fails_without_partial_outputs(self) -> None:
        payload = ready_payload()
        payload["workflows"][0]["status"] = "in_progress"
        payload["workflows"][0]["conclusion"] = None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            outputs = [root / "readiness.json", root / "readiness.md", root / "values.json"]
            input_path.write_text(json.dumps(payload))

            result = main([
                "--input", str(input_path),
                "--json-output", str(outputs[0]),
                "--markdown-output", str(outputs[1]),
                "--normalized-values-output", str(outputs[2]),
            ])

            self.assertEqual(result, 1)
            self.assertTrue(outputs[0].exists())
            self.assertTrue(outputs[1].exists())
            self.assertFalse(outputs[2].exists())
            self.assertTrue(all(not path.with_name(path.name + ".tmp").exists() for path in outputs))

    def test_markdown_and_example_contract(self) -> None:
        report = evaluate_readiness(ready_payload())
        markdown = render_markdown(report)
        example = json.loads(EXAMPLE_PATH.read_text())

        self.assertIn("# rhwp Staging Bootstrap Readiness", markdown)
        self.assertIn("planned", markdown)
        self.assertIn("observed", markdown)
        self.assertFalse(example["protectedEnvironment"]["configured"])
        self.assertIsNone(example["values"]["firebase"]["storageBucket"]["observed"])

    def test_workflow_generates_non_mutating_readiness_test_evidence(self) -> None:
        workflow = WORKFLOW_PATH.read_text()

        self.assertIn("scripts/staging_bootstrap_readiness.py", workflow)
        self.assertIn("staging-bootstrap-readiness-test-evidence", workflow)
        self.assertIn("staging-bootstrap-readiness-test.json", workflow)
        self.assertIn("staging-bootstrap-readiness-test.md", workflow)
        self.assertIn("staging-bootstrap-values-normalized-test.json", workflow)


if __name__ == "__main__":
    unittest.main()
