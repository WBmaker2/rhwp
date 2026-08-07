from __future__ import annotations

import copy
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.staging_preflight import (
    PreflightError,
    _collect_resource_names,
    _expected_resource_names,
    build_preflight_report,
    load_manifest,
    run_read_only,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "deploy/staging/staging-manifest.json"
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"


class StagingManifestTest(unittest.TestCase):
    def test_repository_manifest_matches_the_staging_contract(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        self.assertEqual(manifest["schemaVersion"], "rhwp.staging/v1")
        self.assertEqual(manifest["environment"], "staging")
        self.assertEqual(manifest["project"]["region"], "asia-northeast3")
        self.assertEqual(manifest["tasks"]["parse"]["dispatchDeadlineSeconds"], 900)
        self.assertEqual(manifest["tasks"]["export"]["dispatchDeadlineSeconds"], 900)
        self.assertEqual(manifest["budget"]["currency"], "KRW")
        self.assertEqual(manifest["budget"]["thresholds"], [0.5, 0.8, 1.0])

    def test_manifest_rejects_production_like_project_and_broad_runtime_roles(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        production = copy.deepcopy(manifest)
        production["project"]["id"] = "rhwp-production"
        with self.assertRaisesRegex(PreflightError, "placeholder|forbidden|production"):
            validate_manifest(production)

        broad_role = copy.deepcopy(manifest)
        broad_role["iam"]["bindings"].append(
            {
                "principal": "serviceAccount:${DOCUMENT_API_SERVICE_ACCOUNT}",
                "role": "roles/editor",
                "resource": "project",
            }
        )
        with self.assertRaisesRegex(PreflightError, "roles/editor"):
            validate_manifest(broad_role)

    def test_manifest_rejects_invalid_deadline_currency_and_secret_value(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        bad_deadline = copy.deepcopy(manifest)
        bad_deadline["tasks"]["parse"]["dispatchDeadlineSeconds"] = 600
        with self.assertRaisesRegex(PreflightError, "dispatchDeadlineSeconds"):
            validate_manifest(bad_deadline)

        bad_currency = copy.deepcopy(manifest)
        bad_currency["budget"]["currency"] = "USD"
        with self.assertRaisesRegex(PreflightError, "KRW"):
            validate_manifest(bad_currency)

        secret_value = copy.deepcopy(manifest)
        secret_value["secrets"]["collaborationInternal"]["value"] = "do-not-store"
        with self.assertRaisesRegex(PreflightError, "secret value"):
            validate_manifest(secret_value)

    def test_manifest_distinguishes_initial_and_upgrade_rollback_contracts(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        initial = copy.deepcopy(manifest)
        initial["operations"]["deploymentStage"] = "initial"
        initial["operations"]["rollbackRevisionIds"] = [None, None, None]
        validate_manifest(initial)

        upgrade = copy.deepcopy(manifest)
        upgrade["operations"]["deploymentStage"] = "upgrade"
        upgrade["operations"]["rollbackRevisionIds"] = [
            "collaboration-revision-00002",
            "document-api-revision-00002",
            "document-worker-revision-00002",
        ]
        validate_manifest(upgrade)

        mixed = copy.deepcopy(initial)
        mixed["operations"]["rollbackRevisionIds"] = [None, "revision", None]
        with self.assertRaisesRegex(PreflightError, "initial.*rollbackRevisionIds"):
            validate_manifest(mixed)


class ReadOnlyPreflightTest(unittest.TestCase):
    def test_read_only_runner_rejects_mutating_commands_before_execution(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "{}", "")

        with self.assertRaisesRegex(PreflightError, "read-only"):
            run_read_only(["gcloud", "run", "deploy", "service"], runner=runner)
        self.assertEqual(calls, [])

    def test_read_only_runner_allows_describe_and_list_commands(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "{}", "")

        result = run_read_only(
            ["gcloud", "projects", "describe", "staging-project", "--format=json"],
            runner=runner,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [[
            "gcloud", "projects", "describe", "staging-project", "--format=json"
        ]])

    def test_static_report_contains_no_cloud_or_mutation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            report = build_preflight_report(
                MANIFEST_PATH,
                live=False,
                report_path=report_path,
            )

            self.assertEqual(report["mode"], "static")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["cloudQueries"], [])
            self.assertEqual(report["mutationCommands"], [])
            self.assertEqual(json.loads(report_path.read_text()), report)

    def test_resource_name_collector_handles_nested_cloud_run_metadata(self) -> None:
        names = _collect_resource_names([
            {"metadata": {"name": "rhwp-document-api-staging"}},
            {"name": "projects/demo/locations/asia-northeast3/queues/rhwp-parse-staging"},
            {"email": "rhwp-tasks-staging@demo.iam.gserviceaccount.com"},
        ])

        self.assertEqual(names, {
            "rhwp-document-api-staging",
            "rhwp-parse-staging",
            "rhwp-tasks-staging@demo.iam.gserviceaccount.com",
        })

    def test_platform_service_accounts_are_classified_as_expected_resources(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        expected = _expected_resource_names(manifest)

        self.assertEqual(len(manifest["iam"]["platformServiceAccounts"]), 6)
        self.assertTrue(
            set(manifest["iam"]["platformServiceAccounts"]).issubset(
                expected["serviceAccounts"]
            )
        )

        duplicate = copy.deepcopy(manifest)
        duplicate["iam"]["platformServiceAccounts"].append(
            duplicate["iam"]["platformServiceAccounts"][0]
        )
        with self.assertRaisesRegex(PreflightError, "duplicates"):
            validate_manifest(duplicate)


class StagingWorkflowTest(unittest.TestCase):
    def test_workflow_dispatch_supports_static_and_approved_live_preflight(self) -> None:
        workflow = WORKFLOW_PATH.read_text()

        for marker in (
            "workflow_dispatch:",
            "live_check:",
            "manifest_path:",
            "id-token: write",
            "environment: staging-preflight",
            "google-github-actions/auth@v3",
            "python3 scripts/staging_preflight.py",
            "actions/upload-artifact@v7",
            "staging-preflight-report",
        ):
            self.assertIn(marker, workflow)

    def test_workflow_contains_no_direct_gcloud_or_firebase_mutation(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        mutation = re.compile(
            r"(?:gcloud|firebase)[^\n]*(?:\bcreate\b|\bdelete\b|\bdeploy\b|\benable\b|"
            r"\bdisable\b|\bupdate\b|add-iam-policy-binding|set-iam-policy)"
        )
        self.assertIsNone(mutation.search(workflow))

    def test_live_auth_step_does_not_inherit_operational_environment_variables(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        live_section = workflow.split("\n  live:\n", 1)[1]
        live_job_header, live_steps = live_section.split("\n    steps:\n", 1)

        self.assertNotIn("STAGING_INTERNAL_FLUSH_DECISION:", live_job_header)
        auth_step = live_steps.split(
            "\n      - name: Authenticate with Workload Identity Federation\n", 1
        )[1].split("\n      - name:", 1)[0]
        self.assertNotIn("STAGING_INTERNAL_FLUSH_DECISION", auth_step)


if __name__ == "__main__":
    unittest.main()
