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


if __name__ == "__main__":
    unittest.main()
