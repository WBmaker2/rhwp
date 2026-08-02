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


ROOT = Path(__file__).resolve().parents[2]
RELEASE_PATH = ROOT / "artifacts/actual-release-candidate/run-30728891585-attempt-1/staging-release-candidate-evidence.json"
WORKER_PATH = ROOT / "artifacts/actual-worker-bootstrap/run-30729199234-attempt-2/staging-worker-bootstrap-evidence.json"
SOURCE = "71f084d9fad18bf3514da9dcd50d5d833b79b739"


class RuntimeReleaseMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.release = json.loads(RELEASE_PATH.read_text())
        self.worker = json.loads(WORKER_PATH.read_text())

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
        release_raw = RELEASE_PATH.read_bytes()
        worker_raw = WORKER_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release-metadata.json"
            result = main([
                "--release-evidence", str(RELEASE_PATH),
                "--worker-evidence", str(WORKER_PATH),
                "--expected-source-commit", SOURCE,
                "--expected-release-evidence-sha256", hashlib.sha256(release_raw).hexdigest(),
                "--expected-worker-evidence-sha256", hashlib.sha256(worker_raw).hexdigest(),
                "--expected-release-artifact-digest",
                "sha256:6dbb723eb367f5304747259ce85c551c9eebe5cb55e7263b7160c7f7053b25df",
                "--output", str(output),
            ])
            self.assertEqual(result, 0)
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes().count(b"AIza"), 0)


if __name__ == "__main__":
    unittest.main()
