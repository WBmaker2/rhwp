from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.staging_worker_bootstrap import WorkerBootstrapError, main, render_worker_manifest


PROJECT_ID = "rhwp-collaboration-staging-001"
PROJECT_NUMBER = "598693744358"
SOURCE_SHA = "a" * 40
ARTIFACT_DIGEST = "sha256:" + "b" * 64
WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github/workflows/staging-runtime-worker-bootstrap.yml"


def evidence() -> dict[str, object]:
    return {
        "schemaVersion": "rhwp.staging-release-candidate/v1",
        "sourceCommitSha": SOURCE_SHA,
        "workflowRunId": "30725848106",
        "workflowRunAttempt": 1,
        "deploymentStage": "initial",
        "project": {"number": PROJECT_NUMBER},
        "firebase": {
            "webAppId": "1:598693744358:web:ef670ba1365f30a8117527",
            "apiKeyReference": "firebase-web-config/staging",
        },
        "cloudRun": {
            "collaboration": {
                "image": f"asia-northeast3-docker.pkg.dev/{PROJECT_ID}/rhwp-staging/collaboration",
                "digest": "c" * 64,
            },
            "documentApi": {
                "image": f"asia-northeast3-docker.pkg.dev/{PROJECT_ID}/rhwp-staging/document-api",
                "digest": "d" * 64,
            },
            "documentWorker": {
                "image": f"asia-northeast3-docker.pkg.dev/{PROJECT_ID}/rhwp-staging/document-worker",
                "digest": "e" * 64,
            },
        },
        "rollbackRevisionIds": [None, None, None],
    }


class WorkerBootstrapTest(unittest.TestCase):
    def test_renders_digest_pinned_private_worker_without_mutation(self) -> None:
        raw = json.dumps(evidence(), indent=2) + "\n"
        manifest, summary = render_worker_manifest(
            evidence(),
            expected_source_commit=SOURCE_SHA,
            expected_run_id="30725848106",
            expected_run_attempt=1,
            expected_project_number=PROJECT_NUMBER,
            project_id=PROJECT_ID,
            region="asia-northeast3",
            storage_bucket="rhwp-collaboration-staging-001.firebasestorage.app",
            service_account=f"rhwp-document-worker-staging@{PROJECT_ID}.iam.gserviceaccount.com",
            expected_artifact_digest=ARTIFACT_DIGEST,
            evidence_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        )

        self.assertIn("run.googleapis.com/ingress: internal", manifest)
        self.assertIn("document-worker@sha256:" + "e" * 64, manifest)
        self.assertIn("timeoutSeconds: 900", manifest)
        self.assertEqual(summary["deploymentStage"], "initial")
        self.assertEqual(summary["cloudMutationApproved"], False)
        self.assertEqual(summary["deploymentApproved"], False)
        self.assertEqual(summary["mutationCommands"], [])

    def test_rejects_planned_placeholder_bucket(self) -> None:
        with self.assertRaisesRegex(WorkerBootstrapError, "Storage bucket"):
            render_worker_manifest(
                evidence(),
                expected_source_commit=SOURCE_SHA,
                expected_run_id="30725848106",
                expected_run_attempt=1,
                expected_project_number=PROJECT_NUMBER,
                project_id=PROJECT_ID,
                region="asia-northeast3",
                storage_bucket="${FIREBASE_STORAGE_BUCKET}",
                service_account=f"rhwp-document-worker-staging@{PROJECT_ID}.iam.gserviceaccount.com",
                expected_artifact_digest=ARTIFACT_DIGEST,
                evidence_sha256="f" * 64,
            )

    def test_rejects_source_or_artifact_binding_mismatch(self) -> None:
        invalid = copy.deepcopy(evidence())
        invalid["sourceCommitSha"] = "f" * 40
        with self.assertRaisesRegex(WorkerBootstrapError, "source commit"):
            render_worker_manifest(
                invalid,
                expected_source_commit=SOURCE_SHA,
                expected_run_id="30725848106",
                expected_run_attempt=1,
                expected_project_number=PROJECT_NUMBER,
                project_id=PROJECT_ID,
                region="asia-northeast3",
                storage_bucket="rhwp-collaboration-staging-001.firebasestorage.app",
                service_account=f"rhwp-document-worker-staging@{PROJECT_ID}.iam.gserviceaccount.com",
                expected_artifact_digest=ARTIFACT_DIGEST,
                evidence_sha256="f" * 64,
            )

        with self.assertRaisesRegex(WorkerBootstrapError, "artifact digest"):
            render_worker_manifest(
                evidence(),
                expected_source_commit=SOURCE_SHA,
                expected_run_id="30725848106",
                expected_run_attempt=1,
                expected_project_number=PROJECT_NUMBER,
                project_id=PROJECT_ID,
                region="asia-northeast3",
                storage_bucket="rhwp-collaboration-staging-001.firebasestorage.app",
                service_account=f"rhwp-document-worker-staging@{PROJECT_ID}.iam.gserviceaccount.com",
                expected_artifact_digest="not-a-digest",
                evidence_sha256="f" * 64,
            )

    def test_cli_does_not_leave_outputs_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path = root / "evidence.json"
            manifest_path = root / "worker.yaml"
            summary_path = root / "summary.json"
            evidence_path.write_text(json.dumps(evidence()))
            result = main([
                "--release-evidence", str(evidence_path),
                "--expected-source-commit", SOURCE_SHA,
                "--expected-release-run-id", "30725848106",
                "--expected-release-run-attempt", "1",
                "--expected-project-number", PROJECT_NUMBER,
                "--project-id", PROJECT_ID,
                "--region", "asia-northeast3",
                "--storage-bucket", "${FIREBASE_STORAGE_BUCKET}",
                "--service-account", f"rhwp-document-worker-staging@{PROJECT_ID}.iam.gserviceaccount.com",
                "--release-artifact-digest", ARTIFACT_DIGEST,
                "--manifest-output", str(manifest_path),
                "--summary-output", str(summary_path),
            ])
            self.assertEqual(result, 1)
            self.assertFalse(manifest_path.exists())
            self.assertFalse(summary_path.exists())

    def test_workflow_keeps_prepare_uncredentialed_and_bootstrap_worker_only(self) -> None:
        workflow = WORKFLOW_PATH.read_text()
        self.assertIn("environment: staging-runtime-bootstrap", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("id-token: none", workflow)
        self.assertIn("gh run download \"$RELEASE_RUN_ID\"", workflow)
        self.assertIn("release_artifact_digest", workflow)
        self.assertIn("actions/download-artifact@v7", workflow)
        self.assertIn("gcloud run services replace", workflow)
        self.assertNotIn("gcloud tasks queues create", workflow)
        self.assertNotIn("firebase deploy", workflow)
        self.assertNotIn("member='allUsers'", workflow)

        prepare = workflow.split("\n  bootstrap:\n", 1)[0]
        self.assertNotIn("google-github-actions/auth@v3", prepare)
        bootstrap = workflow.split("\n  bootstrap:\n", 1)[1]
        self.assertLess(
            bootstrap.index("Render digest-pinned worker manifest before authentication"),
            bootstrap.index("Authenticate with Workload Identity Federation"),
        )
        self.assertLess(
            bootstrap.index("Authenticate with Workload Identity Federation"),
            bootstrap.index("Replace document worker service"),
        )


if __name__ == "__main__":
    unittest.main()
