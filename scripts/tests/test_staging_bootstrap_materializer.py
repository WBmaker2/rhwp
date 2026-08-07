from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.staging_approval_packet import (
    BOOTSTRAP_DEFERRED_PATHS,
    _find_placeholder_paths,
    build_approval_packet,
)
from scripts.staging_bootstrap_materializer import (
    BootstrapMaterializerError,
    load_values_from_environment,
    main,
    materialize_bootstrap_manifest,
    validate_bootstrap_values,
)
from scripts.staging_preflight import build_preflight_report, validate_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "deploy/staging/staging-manifest.json"
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"
EXAMPLE_VALUES_PATH = ROOT / "deploy/staging/staging-bootstrap-values.example.json"


def repository_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text())


def valid_values() -> dict[str, object]:
    return {
        "schemaVersion": "rhwp.staging-bootstrap-values/v1",
        "project": {
            "id": "rhwp-collaboration-staging-123",
            "billingAccount": "000000-111111-222222",
            "forbiddenProjectIds": ["rhwp-production"],
        },
        "firebase": {
            "storageBucket": "rhwp-collaboration-staging-123.firebasestorage.app",
        },
        "budget": {
            "amountKrw": 50000,
            "notificationChannels": ["billing-admins@example.com"],
        },
        "operations": {
            "dataRetentionDays": 14,
            "approvalReference": "approval-2026-07-26-001",
            "internalFlushSecurityDecision": "mvp-staging-internal-token",
        },
    }


def valid_environment() -> dict[str, str]:
    return {
        "STAGING_PROJECT_ID": "rhwp-collaboration-staging-123",
        "STAGING_BILLING_ACCOUNT": "000000-111111-222222",
        "STAGING_FORBIDDEN_PROJECT_IDS_JSON": '["rhwp-production"]',
        "STAGING_STORAGE_BUCKET": "rhwp-collaboration-staging-123.firebasestorage.app",
        "STAGING_MONTHLY_BUDGET_KRW": "50000",
        "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON": '["billing-admins@example.com"]',
        "STAGING_DATA_RETENTION_DAYS": "14",
        "STAGING_APPROVAL_REFERENCE": "approval-2026-07-26-001",
        "STAGING_INTERNAL_FLUSH_DECISION": "mvp-staging-internal-token",
    }


class BootstrapMaterializerValidationTest(unittest.TestCase):
    def test_materializes_governance_values_and_deterministic_names(self) -> None:
        result = materialize_bootstrap_manifest(repository_manifest(), valid_values())
        project_id = "rhwp-collaboration-staging-123"

        self.assertEqual(result["project"]["id"], project_id)
        self.assertEqual(result["project"]["billingAccount"], "000000-111111-222222")
        self.assertEqual(result["project"]["forbiddenProjectIds"], ["rhwp-production"])
        self.assertEqual(result["firebase"]["authDomain"], f"{project_id}.firebaseapp.com")
        self.assertEqual(
            result["firebase"]["authorizedDomains"],
            [f"{project_id}.firebaseapp.com", f"{project_id}.web.app"],
        )
        self.assertEqual(result["firebase"]["hostingSite"], project_id)
        self.assertEqual(
            result["firebase"]["storageBucket"],
            f"{project_id}.firebasestorage.app",
        )
        self.assertEqual(result["budget"]["currency"], "KRW")
        self.assertEqual(result["budget"]["amount"], 50000)
        self.assertEqual(result["budget"]["thresholds"], [0.5, 0.8, 1.0])
        self.assertEqual(result["operations"]["dataRetentionDays"], 14)
        self.assertEqual(
            result["operations"]["approvalReference"],
            "approval-2026-07-26-001",
        )
        self.assertFalse(result["operations"]["cloudMutationApproved"])

        expected_accounts = {
            "collaboration": f"rhwp-collaboration-staging@{project_id}.iam.gserviceaccount.com",
            "documentApi": f"rhwp-document-api-staging@{project_id}.iam.gserviceaccount.com",
            "documentWorker": f"rhwp-document-worker-staging@{project_id}.iam.gserviceaccount.com",
        }
        for key, email in expected_accounts.items():
            self.assertEqual(result["cloudRun"][key]["serviceAccount"], email)
        self.assertEqual(
            result["tasks"]["callerServiceAccount"],
            f"rhwp-tasks-staging@{project_id}.iam.gserviceaccount.com",
        )

        serialized_iam = json.dumps(result["iam"], sort_keys=True)
        for placeholder in (
            "${COLLABORATION_SERVICE_ACCOUNT}",
            "${DOCUMENT_API_SERVICE_ACCOUNT}",
            "${DOCUMENT_WORKER_SERVICE_ACCOUNT}",
            "${TASKS_SERVICE_ACCOUNT_EMAIL}",
            "${FIREBASE_STORAGE_BUCKET}",
        ):
            self.assertNotIn(placeholder, serialized_iam)
        for email in (*expected_accounts.values(), result["tasks"]["callerServiceAccount"]):
            self.assertIn(email, serialized_iam)

    def test_preserves_inputs_and_only_approved_deferred_values(self) -> None:
        manifest = repository_manifest()
        values = valid_values()
        original_manifest = copy.deepcopy(manifest)
        original_values = copy.deepcopy(values)

        result = materialize_bootstrap_manifest(manifest, values)

        self.assertEqual(manifest, original_manifest)
        self.assertEqual(values, original_values)
        self.assertEqual(set(_find_placeholder_paths(result)), {
            "manifest.project.number",
            "manifest.firebase.webAppId",
            "manifest.firebase.apiKeyReference",
            "manifest.cloudRun.collaboration.image",
            "manifest.cloudRun.collaboration.digest",
            "manifest.cloudRun.documentApi.image",
            "manifest.cloudRun.documentApi.digest",
            "manifest.cloudRun.documentWorker.image",
            "manifest.cloudRun.documentWorker.digest",
            "manifest.tasks.parse.targetUrl",
            "manifest.tasks.export.targetUrl",
            "manifest.operations.rollbackRevisionIds[0]",
            "manifest.operations.rollbackRevisionIds[1]",
            "manifest.operations.rollbackRevisionIds[2]",
        })
        self.assertIn("manifest.tasks.parse.targetUrl", BOOTSTRAP_DEFERRED_PATHS)
        self.assertIn("manifest.tasks.export.targetUrl", BOOTSTRAP_DEFERRED_PATHS)
        validate_manifest(result)

    def test_rejects_unknown_and_governance_override_keys(self) -> None:
        cases = (
            ("top-level", lambda values: values.__setitem__("unexpected", "value")),
            ("nested", lambda values: values["budget"].__setitem__("currency", "USD")),
            (
                "cloudMutationApproved",
                lambda values: values["operations"].__setitem__("cloudMutationApproved", True),
            ),
            ("iam", lambda values: values.__setitem__("iam", {"roles": ["roles/owner"]})),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                values = valid_values()
                mutate(values)
                with self.assertRaisesRegex(BootstrapMaterializerError, "unknown|not allowed"):
                    validate_bootstrap_values(values)

    def test_rejects_invalid_project_billing_bucket_budget_and_retention(self) -> None:
        cases = (
            (
                "production project",
                lambda values: values["project"].__setitem__("id", "rhwp-production"),
                "production|prod",
            ),
            (
                "forbidden project",
                lambda values: values["project"].__setitem__(
                    "forbiddenProjectIds", ["rhwp-collaboration-staging-123"]
                ),
                "forbidden",
            ),
            (
                "billing",
                lambda values: values["project"].__setitem__("billingAccount", "bad"),
                "billingAccount",
            ),
            (
                "forbidden empty",
                lambda values: values["project"].__setitem__("forbiddenProjectIds", []),
                "forbiddenProjectIds",
            ),
            (
                "bucket",
                lambda values: values["firebase"].__setitem__(
                    "storageBucket", "different-project.firebasestorage.app"
                ),
                "storageBucket",
            ),
            (
                "amount zero",
                lambda values: values["budget"].__setitem__("amountKrw", 0),
                "amountKrw",
            ),
            (
                "amount bool",
                lambda values: values["budget"].__setitem__("amountKrw", True),
                "amountKrw",
            ),
            (
                "channels empty",
                lambda values: values["budget"].__setitem__("notificationChannels", []),
                "notificationChannels",
            ),
            (
                "retention",
                lambda values: values["operations"].__setitem__("dataRetentionDays", 0),
                "dataRetentionDays",
            ),
            (
                "decision",
                lambda values: values["operations"].__setitem__(
                    "internalFlushSecurityDecision", "public-no-token"
                ),
                "internalFlushSecurityDecision",
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                values = valid_values()
                mutate(values)
                with self.assertRaisesRegex(BootstrapMaterializerError, pattern):
                    validate_bootstrap_values(values)

    def test_rejects_sensitive_keys_without_leaking_values(self) -> None:
        for key in (
            "accessToken",
            "credential",
            "password",
            "privateKey",
            "authorization",
            "secretValue",
        ):
            with self.subTest(key=key):
                values = valid_values()
                values["operations"][key] = "must-never-appear"
                with self.assertRaises(BootstrapMaterializerError) as caught:
                    validate_bootstrap_values(values)
                self.assertNotIn("must-never-appear", str(caught.exception))
                self.assertIn("sensitive", str(caught.exception).lower())


class BootstrapEnvironmentAdapterTest(unittest.TestCase):
    def test_builds_values_schema_from_exact_environment_variables(self) -> None:
        values = load_values_from_environment(valid_environment())

        self.assertEqual(values, valid_values())

    def test_rejects_missing_malformed_and_non_integer_environment_values(self) -> None:
        cases = (
            (
                "missing",
                lambda environment: environment.pop("STAGING_PROJECT_ID"),
                "STAGING_PROJECT_ID",
            ),
            (
                "forbidden json",
                lambda environment: environment.__setitem__(
                    "STAGING_FORBIDDEN_PROJECT_IDS_JSON", "not-json"
                ),
                "STAGING_FORBIDDEN_PROJECT_IDS_JSON",
            ),
            (
                "channels type",
                lambda environment: environment.__setitem__(
                    "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON", '"not-an-array"'
                ),
                "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON",
            ),
            (
                "amount",
                lambda environment: environment.__setitem__(
                    "STAGING_MONTHLY_BUDGET_KRW", "50,000"
                ),
                "STAGING_MONTHLY_BUDGET_KRW",
            ),
            (
                "retention",
                lambda environment: environment.__setitem__(
                    "STAGING_DATA_RETENTION_DAYS", "fourteen"
                ),
                "STAGING_DATA_RETENTION_DAYS",
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                environment = valid_environment()
                mutate(environment)
                with self.assertRaisesRegex(BootstrapMaterializerError, pattern):
                    load_values_from_environment(environment)


class BootstrapMaterializerCliAndIntegrationTest(unittest.TestCase):
    def test_cli_file_mode_writes_atomic_materialized_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values_path = root / "values.json"
            output_path = root / "nested/bootstrap-manifest.json"
            values_path.write_text(json.dumps(valid_values()))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--manifest", str(MANIFEST_PATH),
                    "--values", str(values_path),
                    "--output", str(output_path),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertTrue(output_path.exists())
            self.assertFalse(output_path.with_name(output_path.name + ".tmp").exists())
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["project"]["id"], valid_values()["project"]["id"])
            self.assertIn('"mutationCommands": []', stdout.getvalue())

    def test_cli_environment_mode_fails_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "bootstrap-manifest.json"
            environment = valid_environment()
            environment.pop("STAGING_BILLING_ACCOUNT")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main([
                    "--manifest", str(MANIFEST_PATH),
                    "--from-environment",
                    "--output", str(output_path),
                ], environ=environment)

            self.assertEqual(result, 1)
            self.assertFalse(output_path.exists())
            self.assertFalse(output_path.with_name(output_path.name + ".tmp").exists())
            self.assertIn("STAGING_BILLING_ACCOUNT", stderr.getvalue())

    def test_cli_json_stdin_mode_materializes_without_environment_log_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "bootstrap-manifest.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(valid_environment()))):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main([
                        "--manifest", str(MANIFEST_PATH),
                        "--from-json-stdin",
                        "--output", str(output_path),
                    ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertEqual(
                json.loads(output_path.read_text())["project"]["id"],
                valid_environment()["STAGING_PROJECT_ID"],
            )
            self.assertNotIn(valid_environment()["STAGING_INTERNAL_FLUSH_DECISION"], stdout.getvalue())
            self.assertNotIn(valid_environment()["STAGING_INTERNAL_FLUSH_DECISION"], stderr.getvalue())

    def test_materialized_manifest_generates_static_preflight_and_bootstrap_packet(self) -> None:
        manifest = materialize_bootstrap_manifest(repository_manifest(), valid_values())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "staging-manifest-bootstrap.json"
            report_path = root / "staging-preflight-static.json"
            manifest_path.write_text(json.dumps(manifest))

            report = build_preflight_report(
                manifest_path,
                live=False,
                report_path=report_path,
            )
            packet = build_approval_packet(
                manifest,
                report,
                phase="bootstrap",
            )

        self.assertEqual(packet["phase"], "bootstrap")
        self.assertEqual(packet["status"], "ready-for-bootstrap-approval")
        self.assertEqual(packet["project"]["id"], valid_values()["project"]["id"])
        self.assertEqual(packet["budget"]["currency"], "KRW")
        self.assertEqual(packet["budget"]["amount"], 50000)
        self.assertEqual(packet["security"]["mutationCommands"], [])
        deferred = {entry["path"] for entry in packet["deferredValues"]}
        self.assertIn("manifest.tasks.parse.targetUrl", deferred)
        self.assertIn("manifest.tasks.export.targetUrl", deferred)

    def test_example_values_file_matches_the_public_schema(self) -> None:
        values = json.loads(EXAMPLE_VALUES_PATH.read_text())
        validate_bootstrap_values(values)
        self.assertEqual(values["budget"]["amountKrw"], 50000)


class BootstrapWorkflowContractTest(unittest.TestCase):
    def test_bootstrap_job_uses_protected_environment_variables_and_materializer(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        for marker in (
            "environment: staging-bootstrap",
            "STAGING_PROJECT_ID: ${{ vars.STAGING_PROJECT_ID }}",
            "STAGING_BILLING_ACCOUNT: ${{ vars.STAGING_BILLING_ACCOUNT }}",
            "STAGING_FORBIDDEN_PROJECT_IDS_JSON: ${{ vars.STAGING_FORBIDDEN_PROJECT_IDS_JSON }}",
            "STAGING_STORAGE_BUCKET: ${{ vars.STAGING_STORAGE_BUCKET }}",
            "STAGING_MONTHLY_BUDGET_KRW: ${{ vars.STAGING_MONTHLY_BUDGET_KRW }}",
            "STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON: ${{ vars.STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON }}",
            "STAGING_DATA_RETENTION_DAYS: ${{ vars.STAGING_DATA_RETENTION_DAYS }}",
            "STAGING_APPROVAL_REFERENCE: ${{ vars.STAGING_APPROVAL_REFERENCE }}",
            "STAGING_INTERNAL_FLUSH_DECISION: ${{ vars.STAGING_INTERNAL_FLUSH_DECISION }}",
            "python3 scripts/staging_bootstrap_materializer.py",
            "--from-environment",
            "--output artifacts/staging-manifest-bootstrap.json",
            "--manifest artifacts/staging-manifest-bootstrap.json",
            "staging-approval-packet-bootstrap",
        ):
            self.assertIn(marker, workflow)

        bootstrap_section = workflow.split("\n  bootstrap:\n", 1)[1].split("\n  live:\n", 1)[0]
        for forbidden in (
            "id-token: write",
            "google-github-actions/auth",
            "setup-gcloud",
            "firebase-tools",
            "gcloud ",
            "firebase ",
        ):
            self.assertNotIn(forbidden, bootstrap_section)

    def test_workflow_still_contains_no_direct_cloud_mutation(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        self.assertNotRegex(
            workflow,
            r"(?:gcloud|firebase)[^\n]*(?:\bcreate\b|\bdelete\b|\bdeploy\b|\benable\b|\bdisable\b|\bupdate\b|add-iam-policy-binding|set-iam-policy)",
        )

    def test_live_deployment_preflight_materializes_environment_values_before_cloud_auth(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        live_section = workflow.split("\n  live:\n", 1)[1]

        for marker in (
            "environment: staging-preflight",
            "id-token: write",
            "STAGING_PROJECT_ID: ${{ vars.STAGING_PROJECT_ID }}",
            "STAGING_INTERNAL_FLUSH_DECISION: ${{ vars.STAGING_INTERNAL_FLUSH_DECISION }}",
            "python3 - <<'PY'",
            "python3 scripts/staging_bootstrap_materializer.py",
            "--from-json-stdin",
            "--output artifacts/staging-manifest-deployment-preflight.json",
            "--manifest artifacts/staging-manifest-deployment-preflight.json",
            "artifacts/staging-manifest-deployment-preflight.json",
        ):
            self.assertIn(marker, live_section)

        self.assertNotIn("environments/staging-preflight/variables?per_page=100", live_section)
        self.assertNotIn("gh api", live_section.split("Materialize approved deployment preflight manifest", 1)[1].split("Resolve immutable deployment manifest", 1)[0])

        self.assertLess(
            live_section.index("Materialize approved deployment preflight manifest"),
            live_section.index("Authenticate with Workload Identity Federation"),
        )
        self.assertLess(
            live_section.index("Generate static preflight report for deployment approval"),
            live_section.index("Authenticate with Workload Identity Federation"),
        )


if __name__ == "__main__":
    unittest.main()
