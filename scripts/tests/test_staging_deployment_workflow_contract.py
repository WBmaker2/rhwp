from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "staging-deployment.yml"


class StagingDeploymentWorkflowContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_dispatch_inputs_bind_packet_and_approval(self) -> None:
        for name in (
            "source_commit_sha",
            "packet_run_id",
            "packet_run_attempt",
            "packet_artifact_name",
            "packet_artifact_digest",
            "packet_sha256",
            "approval_directory",
            "execute_mutation",
        ):
            self.assertIn(f"      {name}:", self.workflow)
        self.assertIn('test "$GITHUB_REF_NAME" = "feat/firebase-collaboration-mvp-v1"', self.workflow)

    def test_prepare_has_no_oidc_and_uploads_same_run_artifact(self) -> None:
        prepare = self.workflow.split("  deploy:\n", 1)[0]
        self.assertIn("id-token: none", prepare)
        self.assertIn("actions/download-artifact@v8", prepare)
        self.assertIn("actions/upload-artifact@v7", prepare)
        self.assertIn("scripts/staging_deployment_prepare.py", prepare)
        self.assertIn("staging-deployment-approved-input", prepare)

    def test_deploy_is_protected_and_validates_before_mutation_switch(self) -> None:
        deploy = self.workflow.split("  deploy:\n", 1)[1].split("  verify:\n", 1)[0]
        self.assertIn("environment: staging-deployment", deploy)
        self.assertIn("id-token: write", deploy)
        self.assertIn("Checkout protected executor source", deploy)
        self.assertIn("uses: actions/checkout@v5", deploy)
        self.assertIn("Validate same-run approval before any credential step", deploy)
        self.assertIn("scripts.staging_deployment_executor", deploy)
        self.assertIn("Generate bounded deployment plan before authentication", deploy)
        self.assertIn("google-github-actions/auth@v2", deploy)
        self.assertIn("GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER", deploy)
        self.assertIn("GCP_DEPLOY_SERVICE_ACCOUNT", deploy)
        self.assertIn("inputs.execute_mutation == true", deploy)
        self.assertLess(deploy.index("Validate same-run approval before any credential step"), deploy.index("google-github-actions/auth@v2"))
        self.assertLess(deploy.index("google-github-actions/auth@v2"), deploy.index("--apply"))
        self.assertNotIn("service-account-key", deploy)

    def test_packet_and_record_mutation_commands_are_guarded(self) -> None:
        self.assertIn('prepared.get("mutationCommands") != []', self.workflow)
        self.assertIn('record.get("mutationCommands") != []', self.workflow)
        self.assertIn("no evidence is fabricated.", self.workflow)


if __name__ == "__main__":
    unittest.main()
