from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.staging_deployment_manifest import DeploymentManifestError, build_deployment_manifest, main
from scripts.tests.test_staging_approval_packet import concrete_manifest

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github/workflows/staging-config-validate.yml"


def bootstrap_manifest() -> dict[str, object]:
    manifest = copy.deepcopy(concrete_manifest())
    manifest["project"]["number"] = "${GCP_PROJECT_NUMBER}"
    manifest["firebase"]["webAppId"] = "${FIREBASE_WEB_APP_ID}"
    manifest["firebase"]["apiKeyReference"] = "${FIREBASE_WEB_API_KEY_REFERENCE}"
    for key in ("collaboration", "documentApi", "documentWorker"):
        manifest["cloudRun"][key]["image"] = f"${{{key.upper()}_IMAGE}}"
        manifest["cloudRun"][key]["digest"] = f"${{{key.upper()}_IMAGE_DIGEST}}"
    manifest["tasks"]["parse"]["targetUrl"] = "https://${DOCUMENT_WORKER_HOST}/run/parse"
    manifest["tasks"]["export"]["targetUrl"] = "https://${DOCUMENT_WORKER_HOST}/run/export"
    manifest["operations"]["rollbackRevisionIds"] = [
        "${COLLABORATION_ROLLBACK_REVISION}",
        "${DOCUMENT_API_ROLLBACK_REVISION}",
        "${DOCUMENT_WORKER_ROLLBACK_REVISION}",
    ]
    return manifest


def release_metadata() -> dict[str, object]:
    return {
        "schemaVersion": "rhwp.staging-deployment-release/v1",
        "sourceCommitSha": "d" * 40,
        "workflowRunId": "123456",
        "workflowRunAttempt": 1,
        "deploymentStage": "upgrade",
        "project": {"number": "812048192442"},
        "firebase": {
            "webAppId": "1:812048192442:web:abcdef123456",
            "apiKeyReference": "firebase-web-config/staging",
        },
        "cloudRun": {
            "collaboration": {
                "image": "asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-123/rhwp-staging/collaboration",
                "digest": "1" * 64,
            },
            "documentApi": {
                "image": "asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-123/rhwp-staging/document-api",
                "digest": "2" * 64,
            },
            "documentWorker": {
                "image": "asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-123/rhwp-staging/document-worker",
                "digest": "3" * 64,
            },
        },
        "tasks": {
            "parse": {"targetUrl": "https://worker.example/run/parse"},
            "export": {"targetUrl": "https://worker.example/run/export"},
        },
        "rollbackRevisionIds": [
            "collaboration-revision-00002",
            "document-api-revision-00002",
            "document-worker-revision-00002",
        ],
    }


class DeploymentManifestTest(unittest.TestCase):
    def test_resolves_release_fields_and_preserves_non_deployment_authority(self) -> None:
        manifest = build_deployment_manifest(
            bootstrap_manifest(),
            release_metadata(),
            expected_source_commit="d" * 40,
        )

        self.assertEqual(manifest["project"]["number"], "812048192442")
        self.assertEqual(manifest["firebase"]["webAppId"], "1:812048192442:web:abcdef123456")
        self.assertEqual(manifest["cloudRun"]["documentWorker"]["digest"], "3" * 64)
        self.assertEqual(manifest["tasks"]["parse"]["targetUrl"], "https://worker.example/run/parse")
        self.assertEqual(manifest["operations"]["cloudMutationApproved"], False)

    def test_rejects_source_commit_mismatch(self) -> None:
        with self.assertRaisesRegex(DeploymentManifestError, "source commit"):
            build_deployment_manifest(
                bootstrap_manifest(),
                release_metadata(),
                expected_source_commit="e" * 40,
            )

    def test_allows_initial_stage_without_invented_rollback_revisions(self) -> None:
        release = release_metadata()
        release["deploymentStage"] = "initial"
        release["rollbackRevisionIds"] = [None, None, None]

        manifest = build_deployment_manifest(
            bootstrap_manifest(), release, expected_source_commit="d" * 40
        )

        self.assertEqual(manifest["operations"]["deploymentStage"], "initial")
        self.assertEqual(manifest["operations"]["rollbackRevisionIds"], [None, None, None])

    def test_rejects_mixed_or_placeholder_initial_rollback_values(self) -> None:
        release = release_metadata()
        release["deploymentStage"] = "initial"
        release["rollbackRevisionIds"] = [None, "revision", None]
        with self.assertRaisesRegex(DeploymentManifestError, "initial.*rollbackRevisionIds"):
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)

        release = release_metadata()
        release["deploymentStage"] = "upgrade"
        release["rollbackRevisionIds"] = ["${PREVIOUS}", "revision", "revision"]
        with self.assertRaisesRegex(DeploymentManifestError, "concrete"):
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)

    def test_rejects_invalid_digest_and_raw_api_key(self) -> None:
        release = release_metadata()
        release["cloudRun"]["collaboration"]["digest"] = "not-a-digest"
        with self.assertRaisesRegex(DeploymentManifestError, "digest"):
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)

        release = release_metadata()
        release["firebase"]["apiKeyReference"] = "AIza" + "x" * 30
        with self.assertRaisesRegex(DeploymentManifestError, "raw Firebase API key"):
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)

        release = release_metadata()
        release["cloudRun"]["documentApi"]["image"] = (
            "asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-123/rhwp-staging/collaboration:wrong-service"
        )
        with self.assertRaisesRegex(DeploymentManifestError, "canonical staging repository"):
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)

    def test_rejects_sensitive_release_key_without_leaking_value(self) -> None:
        release = release_metadata()
        release["secretValue"] = "do-not-print-this"
        with self.assertRaisesRegex(DeploymentManifestError, "sensitive key") as context:
            build_deployment_manifest(bootstrap_manifest(), release, expected_source_commit="d" * 40)
        self.assertNotIn("do-not-print-this", str(context.exception))

    def test_cli_does_not_leave_partial_output_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bootstrap = root / "bootstrap.json"
            release = root / "release.json"
            output = root / "deployment.json"
            bootstrap.write_text(json.dumps(bootstrap_manifest()))
            invalid = release_metadata()
            invalid["cloudRun"]["documentApi"]["digest"] = "bad"
            release.write_text(json.dumps(invalid))

            result = main([
                "--bootstrap-manifest", str(bootstrap),
                "--release-metadata", str(release),
                "--expected-source-commit", "d" * 40,
                "--output", str(output),
            ])

            self.assertEqual(result, 1)
            self.assertFalse(output.exists())

    def test_cli_writes_exact_bytes_and_reports_their_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bootstrap = root / "bootstrap.json"
            release = root / "release.json"
            output = root / "deployment.json"
            bootstrap.write_text(json.dumps(bootstrap_manifest()))
            release.write_text(json.dumps(release_metadata()))
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main([
                    "--bootstrap-manifest", str(bootstrap),
                    "--release-metadata", str(release),
                    "--expected-source-commit", "d" * 40,
                    "--output", str(output),
                ])

            self.assertEqual(result, 0)
            output_bytes = output.read_bytes()
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["manifestSha256"], hashlib.sha256(output_bytes).hexdigest())
            self.assertEqual(report["mutationCommands"], [])

    def test_deployment_workflow_resolves_release_metadata_before_packet(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        live_section = workflow.split("\n  live:\n", 1)[1]
        for marker in (
            "release_metadata_path:",
            "scripts/staging_deployment_manifest.py",
            "--bootstrap-manifest artifacts/staging-manifest-deployment-preflight-bootstrap.json",
            "--release-metadata \"${RELEASE_METADATA_PATH}\"",
            "--expected-source-commit \"${GITHUB_SHA}\"",
            "Verify release workflow provenance",
            "gh run view",
            "actions: read",
            "artifacts/staging-manifest-deployment-preflight.json",
            "artifacts/staging-manifest-deployment-preflight-bootstrap.json",
        ):
            self.assertIn(marker, workflow)
        self.assertLess(
            live_section.index("Resolve immutable deployment manifest from release metadata"),
            live_section.index("Authenticate with Workload Identity Federation"),
        )
        self.assertLess(
            live_section.index("Resolve immutable deployment manifest from release metadata"),
            live_section.index("Generate deployment staging approval packet"),
        )


if __name__ == "__main__":
    unittest.main()
