from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTUAL_CLI_MODULES = (
    "staging_infrastructure_actions",
    "staging_infrastructure_apply_executor",
    "staging_infrastructure_apply_ready",
    "staging_infrastructure_apply_review",
    "staging_infrastructure_approval",
    "staging_infrastructure_environment_attestation",
    "staging_infrastructure_execution_gate",
    "staging_infrastructure_plan",
    "staging_infrastructure_wif_attestation",
)
COMMAND_SOURCES = (
    ROOT / ".github/workflows/staging-infrastructure-apply.yml",
    ROOT / ".github/workflows/staging-infrastructure-apply-review.yml",
    ROOT / ".github/workflows/staging-config-validate.yml",
    ROOT / "docs/runbooks/staging-infrastructure-bootstrap.md",
)


class StagingInfrastructureCliInvocationTest(unittest.TestCase):
    def test_actual_clis_support_root_module_help(self) -> None:
        for module in ACTUAL_CLI_MODULES:
            with self.subTest(module=module):
                completed = subprocess.run(
                    [sys.executable, "-m", f"scripts.{module}", "--help"],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_workflows_and_runbook_use_module_invocation(self) -> None:
        source_text = "\n".join(path.read_text() for path in COMMAND_SOURCES)
        self.assertNotIn("python3 scripts/staging_infrastructure_", source_text)
        for module in (
            "staging_infrastructure_apply_executor",
            "staging_infrastructure_apply_review",
            "staging_infrastructure_plan",
            "staging_infrastructure_approval",
            "staging_infrastructure_actions",
            "staging_infrastructure_execution_gate",
            "staging_infrastructure_apply_ready",
        ):
            self.assertIn(f"python3 -m scripts.{module}", source_text)


if __name__ == "__main__":
    unittest.main()
