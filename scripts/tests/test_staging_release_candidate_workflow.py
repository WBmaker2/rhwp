from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/staging-release-candidate.yml"


class StagingReleaseCandidateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text()

    def test_workflow_exists_and_has_dispatch_source_ref(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("source_ref:", self.text)
        self.assertIn("default: feat/firebase-collaboration-mvp-v1", self.text)

    def test_prepare_is_non_cloud_and_build_is_protected_oidc(self) -> None:
        prepare = self.text.split("  build-push:\n", 1)[0]
        build = self.text.split("  build-push:\n", 1)[1]
        self.assertIn("id-token: none", prepare)
        self.assertNotIn('test "$(git branch --show-current)" = ""', prepare)
        self.assertIn("environment: staging-release", build)
        self.assertIn("id-token: write", build)
        self.assertLess(
            build.index("Verify source commit binding before authentication"),
            build.index("Authenticate with Workload Identity Federation"),
        )

    def test_builds_all_three_immutable_images_and_uploads_candidate(self) -> None:
        for dockerfile in (
            "services/collaboration-server/Dockerfile",
            "services/document-api/Dockerfile",
            "services/document-worker/Dockerfile",
        ):
            self.assertIn(f"--file {dockerfile}", self.text)
        self.assertEqual(len(re.findall(r"\n\s+--push\s+\\", self.text)), 3)
        self.assertIn("name: staging-release-candidate-evidence", self.text)
        self.assertIn("'deploymentStage': 'initial'", self.text)
        self.assertIn("'rollbackRevisionIds': [None, None, None]", self.text)

    def test_runtime_mutations_are_not_in_release_candidate_workflow(self) -> None:
        forbidden = (
            "gcloud run deploy",
            "gcloud tasks queues create",
            "firebase deploy",
            "terraform apply",
        )
        for marker in forbidden:
            self.assertNotIn(marker, self.text)

    def test_digest_values_are_exported_before_evidence_generation(self) -> None:
        resolve = self.text.split("Resolve immutable image digests and Firebase app identity", 1)[1]
        self.assertLess(resolve.index('export PROJECT_NUMBER='), resolve.index("python3 - <<'PY'"))
        self.assertNotIn("steps.resolve.outputs", resolve)
        self.assertIn("firebase-web-apps.json", resolve)
        self.assertIn(".get('apps', [])", resolve)


if __name__ == "__main__":
    unittest.main()
