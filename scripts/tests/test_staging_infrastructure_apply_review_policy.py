from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.staging_infrastructure_actions import build_execution_manifest
from scripts.staging_infrastructure_apply_review import build_apply_review_package
from scripts.tests.test_staging_infrastructure_actions import (
    canonical_plan_and_approval,
    plan_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40


class ApplyReviewPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.approval = canonical_plan_and_approval()
        self.raw = plan_bytes(self.plan)
        self.execution = build_execution_manifest(
            self.plan, self.approval, plan_bytes=self.raw
        )

    def test_environment_and_wif_require_unresolved_immutable_inputs(self) -> None:
        package = build_apply_review_package(
            self.plan, self.approval, self.execution,
            plan_bytes=self.raw, executor_commit_sha=COMMIT,
        )
        environment = package["protectedEnvironmentSpec"]
        self.assertFalse(environment["canAdminsBypass"])
        self.assertEqual(
            environment["supportVerificationStatus"], "required-before-apply"
        )
        self.assertTrue(environment["unsupportedOrUnverifiedBlocksApprovalApply"])

        identity = package["wifIdentityAndIamDiff"]
        self.assertFalse(identity["applicable"])
        self.assertEqual(
            identity["proposedConditionStatus"],
            "incomplete-until-actual-immutable-claims-approved",
        )
        self.assertEqual(
            identity["requiredActualInputs"],
            {
                "repositoryId": {"value": None, "expectedFormat": "^[0-9]+$"},
                "repositoryOwnerId": {"value": None, "expectedFormat": "^[0-9]+$"},
                "workflowSha": {"value": None, "expectedFormat": "^[0-9a-f]{40}$"},
            },
        )
        self.assertEqual(
            set(identity["finalConditionRequirements"]),
            {"repositoryId", "repositoryOwnerId", "workflowSha", "ref", "workflowRef"},
        )
        self.assertEqual(package["status"], "ready-for-apply-review")
        self.assertFalse(package["cloudMutationApproved"])
        self.assertFalse(package["deploymentApproved"])
        self.assertEqual(package["mutationCommands"], [])

    def test_subprocess_rejects_hardlink_and_direct_ancestor_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            plan, approval, execution = root / "plan.json", root / "approval.json", root / "execution.json"
            plan.write_bytes(self.raw)
            approval.write_text(json.dumps(self.approval))
            execution.write_text(json.dumps(self.execution))
            script = ROOT / "scripts" / "staging_infrastructure_apply_review.py"
            cases: list[tuple[str, Path, Path]] = []
            hardlink = root / "hardlink-plan.json"
            os.link(plan, hardlink)
            cases.append(("hardlink", hardlink, root / "hardlink.md"))
            direct = root / "direct.json"
            direct.symlink_to(plan)
            cases.append(("direct-symlink", direct, root / "direct.md"))
            real_parent = root / "real-output"
            real_parent.mkdir()
            ancestor = root / "linked-output"
            ancestor.symlink_to(real_parent, target_is_directory=True)
            cases.append(("ancestor-symlink", ancestor / "review.json", root / "ancestor.md"))

            for label, output, markdown in cases:
                with self.subTest(label=label):
                    before = plan.read_bytes()
                    result = subprocess.run(
                        [sys.executable, str(script), "--plan", str(plan),
                         "--approval-result", str(approval), "--execution-manifest", str(execution),
                         "--executor-commit-sha", COMMIT, "--json-output", str(output),
                         "--markdown-output", str(markdown)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(plan.read_bytes(), before)
                    self.assertFalse(markdown.exists())
                    self.assertFalse(
                        output.with_name(output.name + ".complete").exists()
                    )


if __name__ == "__main__":
    unittest.main()
