from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.staging_infrastructure_actions import build_execution_manifest
from scripts.staging_infrastructure_approval import validate_infrastructure_approval
from scripts.staging_infrastructure_execution_gate import (  # type: ignore[import-not-found]
    evaluate_execution_readiness,
    main,
    render_markdown,
)
from scripts.tests.test_staging_infrastructure_actions import canonical_plan_and_approval, plan_bytes


class ExecutionReadinessGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.approval = canonical_plan_and_approval()
        self.manifest = build_execution_manifest(self.plan, self.approval, plan_bytes=plan_bytes(self.plan))

    def evaluate(self, manifest: dict[str, object] | None = None, approval: dict[str, object] | None = None) -> dict[str, object]:
        return evaluate_execution_readiness(manifest or self.manifest, approval or self.approval)

    def test_valid_review_remains_awaiting_and_never_authorizes_mutation(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["status"], "awaiting-cloud-mutation-approval")
        self.assertFalse(result["cloudMutationApproved"])
        self.assertFalse(result["deploymentApproved"])
        self.assertEqual(result["mutationCommands"], [])
        self.assertEqual(result["nextAction"], "review-required-approvals")
        self.assertEqual(result["requiredApprovals"], [
            "mutation-architecture", "actual-evidence-transport", "canonical-mutation-subset",
            "staging-infrastructure-apply-environment", "wif-identity-and-least-privilege-iam-diff",
            "cloud-mutation-approval-record", "apply-workflow-dispatch",
        ])
        self.assertEqual(result["blockedReasons"], [])

    def test_claimed_mutation_approval_still_does_not_report_ready_to_apply(self) -> None:
        approval = copy.deepcopy(self.approval)
        approval["cloudMutationApproved"] = True
        approval["status"] = "cloud-mutation-approved"
        approval["requireCloudMutation"] = True
        result = self.evaluate(build_execution_manifest(self.plan, approval), approval)
        self.assertEqual(result["status"], "awaiting-executor-design-approval")
        self.assertFalse(result["cloudMutationApproved"])
        self.assertIn("mutation-architecture", result["requiredApprovals"])

    def test_evidence_and_approval_boundary_mismatches_are_blocked_without_values(self) -> None:
        cases = (
            ("commit", lambda manifest, approval: manifest["sourceEvidence"].__setitem__("commitSha", "2" * 40)),
            ("plan", lambda manifest, approval: manifest["sourceEvidence"].__setitem__("planSha256", "2" * 64)),
            ("plan object", lambda manifest, approval: manifest["sourceEvidence"].__setitem__("planObjectSha256", "2" * 64)),
            ("action set", lambda manifest, approval: manifest["sourceEvidence"].__setitem__("actionSetSha256", "2" * 64)),
            ("project", lambda manifest, approval: manifest.__setitem__("projectId", "other-staging-project")),
            ("billing", lambda manifest, approval: manifest.__setitem__("billingAccount", "AAAAAA-BBBBBB-CCCCCC")),
            ("stages", lambda manifest, approval: approval.__setitem__("approvedStageIds", list(reversed(approval["approvedStageIds"]))),),
            ("budget", lambda manifest, approval: approval.__setitem__("maximumMonthlyBudgetKrw", 9999)),
            ("rollback", lambda manifest, approval: approval.__setitem__("rollbackReviewed", False)),
            ("deployment", lambda manifest, approval: approval.__setitem__("deploymentApproved", True)),
            ("production", lambda manifest, approval: manifest.__setitem__("projectId", "rhwp-production-001")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest, approval = copy.deepcopy(self.manifest), copy.deepcopy(self.approval)
                mutate(manifest, approval)
                result = self.evaluate(manifest, approval)
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(result["blockedReasons"])
                self.assertNotIn("AAAAAA-BBBBBB-CCCCCC", json.dumps(result))

    def test_rejects_unsafe_unknown_reordered_and_invalid_dependent_actions(self) -> None:
        cases = (
            ("unknown", lambda manifest: manifest["actions"][0].__setitem__("kind", "unknown-action")),
            ("reordered", lambda manifest: manifest["actions"].__setitem__(0, manifest["actions"][3])),
            ("duplicate", lambda manifest: manifest["actions"][1].__setitem__("id", manifest["actions"][0]["id"])),
            ("dependency", lambda manifest: manifest["actions"][0].__setitem__("dependencies", ["future-action"])),
            ("executable", lambda manifest: manifest["actions"][0].__setitem__("command", "must-not-run")),
            ("blocked executable", lambda manifest: next(action for action in manifest["actions"] if action["classification"] == "blocked-deferred")["desiredState"].__setitem__("mutationAuthorized", True)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                self.assertEqual(self.evaluate(manifest)["status"], "blocked")

    def test_requires_exact_canonical_action_shape_and_safe_nested_values(self) -> None:
        cases = (
            ("missing final", lambda manifest: manifest["actions"].pop()),
            ("duplicate resource", lambda manifest: manifest["actions"].append(copy.deepcopy(manifest["actions"][0]))),
            ("missing dependency", lambda manifest: manifest["actions"][1].__setitem__("dependencies", [])),
            ("nested production", lambda manifest: manifest["actions"][0]["resource"].__setitem__("projectId", "rhwp-production-001")),
            ("bad resource type", lambda manifest: manifest["actions"][0].__setitem__("resource", "not-a-map")),
            ("unknown secret key", lambda manifest: manifest["actions"][0]["resource"].__setitem__("superSecret", "must-not-leak")),
            ("AIza", lambda manifest: manifest["actions"][0]["resource"].__setitem__("value", "AIzaMustNotLeak")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                result = self.evaluate(manifest)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["blockedReasons"], ["malformed-input"])
                self.assertNotIn("superSecret", json.dumps(result))
                self.assertNotIn("must-not-leak", json.dumps(result))

    def test_recomputed_action_hash_cannot_bypass_rebuilt_plan_comparison(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["actions"].pop()
        from scripts.staging_infrastructure_execution_gate import _action_set_sha256
        manifest["sourceEvidence"]["actionSetSha256"] = _action_set_sha256(manifest["actions"])
        result = self.evaluate(manifest)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blockedReasons"], ["malformed-input"])

    def test_direct_script_cli_help_and_success(self) -> None:
        script = Path(__file__).resolve().parents[1] / "staging_infrastructure_execution_gate.py"
        self.assertEqual(subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True).returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, approval_path = root / "manifest.json", root / "approval.json"
            manifest_path.write_text(json.dumps(self.manifest)); approval_path.write_text(json.dumps(self.approval))
            completed = subprocess.run([sys.executable, str(script), "--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(root / "gate.json"), "--markdown-output", str(root / "gate.md")], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_sensitive_values_and_malformed_approval_without_leaking_them(self) -> None:
        for target, key in (("manifest", "privateKey"), ("approval", "accessToken")):
            with self.subTest(target=target):
                manifest, approval = copy.deepcopy(self.manifest), copy.deepcopy(self.approval)
                (manifest if target == "manifest" else approval)[key] = "must-not-leak"
                result = self.evaluate(manifest, approval)
                self.assertEqual(result["status"], "blocked")
                self.assertNotIn("must-not-leak", json.dumps(result))

    def test_never_raises_for_non_mapping_untrusted_inputs(self) -> None:
        for manifest, approval in ((None, self.approval), (self.manifest, None), ([], [])):
            with self.subTest(manifest=type(manifest).__name__, approval=type(approval).__name__):
                result = evaluate_execution_readiness(manifest, approval)  # type: ignore[arg-type]
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["blockedReasons"], ["malformed-input"])

    def test_deep_or_nonfinite_untrusted_values_are_blocked_without_echo(self) -> None:
        deep: dict[str, object] = {}
        cursor = deep
        for _ in range(1200):
            child: dict[str, object] = {}
            cursor["next"] = child
            cursor = child
        for manifest in (deep, {"projectId": "AKIA-opaque-value", "value": float("nan")}):
            result = evaluate_execution_readiness(manifest, self.approval)
            self.assertEqual(result["status"], "blocked")
            self.assertIsNone(result["projectId"])
            self.assertNotIn("AKIA-opaque-value", json.dumps(result))

    def test_task1_task2_task3_integration_and_safe_markdown(self) -> None:
        result = self.evaluate()
        markdown = render_markdown(result)
        self.assertIn("review-required-approvals", markdown)
        self.assertNotIn("must-not-leak", markdown)

    def test_compact_plan_bytes_bind_task1_task2_and_task3_object_evidence(self) -> None:
        raw = json.dumps(self.plan, ensure_ascii=False, separators=(",", ":")).encode()
        record = copy.deepcopy(self.approval)
        record["planSha256"] = hashlib.sha256(raw).hexdigest()
        task1 = validate_infrastructure_approval(self.plan, raw, {
            "schemaVersion": "rhwp.staging-infrastructure-approval/v1",
            "decision": "approved", "approvedAt": "2026-07-27T00:00:00Z",
            "approvedBy": ["repository-owner"], "commitSha": self.plan["sourceEvidence"]["commitSha"],
            "planSha256": record["planSha256"], "projectId": self.plan["projectId"],
            "billingAccount": self.plan["billingAccount"], "approvedStageIds": record["approvedStageIds"],
            "maximumMonthlyBudgetKrw": record["maximumMonthlyBudgetKrw"], "cloudMutationApproved": False,
            "deploymentApproved": False, "rollbackReviewed": True,
        }, require_cloud_mutation=False)
        manifest = build_execution_manifest(self.plan, task1, plan_bytes=raw)
        self.assertEqual(manifest["sourceEvidence"]["planObjectSha256"], task1["planObjectSha256"])
        self.assertEqual(evaluate_execution_readiness(manifest, task1)["status"], "awaiting-cloud-mutation-approval")
        manifest["sourceEvidence"]["planObjectSha256"] = "0" * 64
        self.assertEqual(evaluate_execution_readiness(manifest, task1)["status"], "blocked")

    def test_cli_is_atomic_marks_completion_and_strictly_exits_for_blocked_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, approval_path = root / "execution.json", root / "approval.json"
            output, markdown = root / "gate.json", root / "gate.md"
            manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False) + "\n")
            approval_path.write_text(json.dumps(self.approval, ensure_ascii=False) + "\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(output), "--markdown-output", str(markdown)]), 0)
            marker = json.loads((root / "gate.json.complete").read_text())
            self.assertEqual(marker["jsonSha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            bad = copy.deepcopy(self.manifest); bad["projectId"] = "rhwp-production-001"
            manifest_path.write_text(json.dumps(bad))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(output), "--markdown-output", str(markdown), "--strict-blocked-exit"]), 2)
            self.assertEqual(json.loads(output.read_text())["status"], "blocked")
            alias = root / "alias.json"; alias.symlink_to(manifest_path)
            original = manifest_path.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(alias), "--markdown-output", str(markdown)]), 1)
            self.assertEqual(manifest_path.read_bytes(), original)

    def test_second_publication_failure_restores_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, approval_path = root / "execution.json", root / "approval.json"
            output, markdown = root / "gate.json", root / "gate.md"
            manifest_path.write_text(json.dumps(self.manifest)); approval_path.write_text(json.dumps(self.approval))
            self.assertEqual(main(["--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(output), "--markdown-output", str(markdown)]), 0)
            prior = (output.read_bytes(), markdown.read_bytes())
            original_replace = Path.replace
            def fail_markdown(path: Path, target: Path) -> Path:
                if path == markdown.with_name(markdown.name + ".tmp"):
                    raise OSError("simulated failure")
                return original_replace(path, target)
            with patch("scripts.staging_infrastructure_action_io.Path.replace", autospec=True, side_effect=fail_markdown), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--execution-manifest", str(manifest_path), "--approval-result", str(approval_path), "--json-output", str(output), "--markdown-output", str(markdown)]), 1)
            self.assertEqual((output.read_bytes(), markdown.read_bytes()), prior)

    def test_source_contains_no_execution_or_auth_mechanism(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "staging_infrastructure_execution_gate.py").read_text().lower()
        for forbidden in ("import subprocess", "os.system", "gcloud", "firebase cli", "authorization", "privatekey"):
            self.assertNotIn(forbidden, source)
