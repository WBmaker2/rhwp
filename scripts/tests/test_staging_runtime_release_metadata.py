from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.staging_runtime_release_metadata import (
    RuntimeMetadataError,
    build_release_metadata,
    main,
)


SOURCE = "71f084d9fad18bf3514da9dcd50d5d833b79b739"


def _fixture_pair() -> tuple[dict, dict, bytes, bytes]:
    """Build self-contained evidence fixtures; never depend on local artifacts."""
    release = {
        "schemaVersion": "rhwp.staging-release-candidate/v1",
        "sourceCommitSha": SOURCE,
        "workflowRunId": "30728891585",
        "workflowRunAttempt": 1,
        "deploymentStage": "initial",
        "project": {"number": "598693744358"},
        "firebase": {
            "webAppId": "1:598693744358:web:ef670ba1365f30a8117527",
            "apiKeyReference": "firebase-web-config/staging",
        },
        "cloudRun": {
            name: {
                "image": f"asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-001/rhwp-staging/{name}",
                "digest": digest,
            }
            for name, digest in {
                "collaboration": "1" * 64,
                "documentApi": "2" * 64,
                "documentWorker": "3" * 64,
            }.items()
        },
        "rollbackRevisionIds": [None, None, None],
    }
    release_raw = (json.dumps(release, ensure_ascii=False, indent=2) + "\n").encode()
    worker = {
        "schemaVersion": "rhwp.staging-worker-bootstrap/v1",
        "sourceCommitSha": SOURCE,
        "releaseWorkflowRunId": "30728891585",
        "releaseWorkflowRunAttempt": 1,
        "releaseArtifactDigest": "sha256:" + "4" * 64,
        "releaseEvidenceSha256": hashlib.sha256(release_raw).hexdigest(),
        "bootstrapWorkflowRunId": "30729199234",
        "bootstrapWorkflowRunAttempt": 2,
        "project": {"number": "598693744358"},
        "firebase": {"webAppId": "1:598693744358:web:ef670ba1365f30a8117527"},
        "worker": {
            "service": "rhwp-document-worker-staging",
            "image": release["cloudRun"]["documentWorker"]["image"],
            "digest": "3" * 64,
            "storageBucket": "rhwp-collaboration-staging-001.firebasestorage.app",
            "serviceAccount": "rhwp-document-worker-staging@rhwp-collaboration-staging-001.iam.gserviceaccount.com",
            "url": "https://rhwp-document-worker-staging-zfwxigwhha-du.a.run.app",
            "revision": "rhwp-document-worker-staging-00002-4p2",
        },
        "deploymentStage": "initial",
        "rollbackRevisionId": None,
    }
    worker_raw = (json.dumps(worker, ensure_ascii=False, indent=2) + "\n").encode()
    return release, worker, release_raw, worker_raw


class RuntimeReleaseMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.release, self.worker, self.release_raw, self.worker_raw = _fixture_pair()

    def test_derives_task_targets_from_observed_worker_url(self) -> None:
        metadata = build_release_metadata(self.release, self.worker, expected_source_commit=SOURCE)
        worker_url = self.worker["worker"]["url"]
        self.assertEqual(metadata["tasks"]["parse"]["targetUrl"], worker_url + "/run/parse")
        self.assertEqual(metadata["tasks"]["export"]["targetUrl"], worker_url + "/run/export")
        self.assertEqual(metadata["deploymentStage"], "initial")
        self.assertEqual(metadata["rollbackRevisionIds"], [None, None, None])

    def test_rejects_worker_url_change_before_output(self) -> None:
        worker = copy.deepcopy(self.worker)
        worker["worker"]["url"] = "https://invented.example/run/parse"
        with self.assertRaisesRegex(RuntimeMetadataError, "Cloud Run host"):
            build_release_metadata(self.release, worker, expected_source_commit=SOURCE)

    def test_rejects_cross_commit_binding(self) -> None:
        worker = copy.deepcopy(self.worker)
        worker["sourceCommitSha"] = "0" * 40
        with self.assertRaisesRegex(RuntimeMetadataError, "source"):
            build_release_metadata(self.release, worker, expected_source_commit=SOURCE)

    def test_cli_checks_exact_input_bytes_and_reports_output_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release_path = Path(directory) / "release-evidence.json"
            worker_path = Path(directory) / "worker-evidence.json"
            release_path.write_bytes(self.release_raw)
            worker_path.write_bytes(self.worker_raw)
            output = Path(directory) / "release-metadata.json"
            result = main([
                "--release-evidence", str(release_path),
                "--worker-evidence", str(worker_path),
                "--expected-source-commit", SOURCE,
                "--expected-release-evidence-sha256", hashlib.sha256(self.release_raw).hexdigest(),
                "--expected-worker-evidence-sha256", hashlib.sha256(self.worker_raw).hexdigest(),
                "--expected-release-artifact-digest",
                "sha256:" + "4" * 64,
                "--output", str(output),
            ])
            self.assertEqual(result, 0)
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes().count(b"AIza"), 0)


if __name__ == "__main__":
    unittest.main()
