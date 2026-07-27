from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.staging_infrastructure_approval import (
    InfrastructureApprovalError,
    load_json_with_bytes,
    main,
    render_markdown,
    validate_infrastructure_approval,
)
from scripts.staging_infrastructure_plan import build_infrastructure_plan
from scripts.staging_infrastructure_validation import MAX_JSON_BYTES
from scripts.tests.test_staging_infrastructure_plan import (
    approved_record as bootstrap_approval_record,
    manifest_and_packet,
    packet_text_and_digest,
)


def plan_bytes(plan: dict[str, object]) -> bytes:
    return (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def plan_fixture() -> dict[str, object]:
    return {
        "schemaVersion": "rhwp.staging-infrastructure-plan/v1",
        "status": "ready-for-infrastructure-approval",
        "projectId": "rhwp-collaboration-staging-001",
        "billingAccount": "123456-ABCDEF-123456",
        "sourceEvidence": {"commitSha": "1" * 40},
        "stages": [
            {"id": "project-billing"},
            {"id": "budget-guardrails", "resources": {"amount": 50000, "metadata": 1}},
        ],
    }


def approval_fixture(plan: dict[str, object], raw: bytes) -> dict[str, object]:
    return {
        "schemaVersion": "rhwp.staging-infrastructure-approval/v1",
        "decision": "approved",
        "approvedAt": "2026-07-27T00:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": plan["sourceEvidence"]["commitSha"],  # type: ignore[index]
        "planSha256": hashlib.sha256(raw).hexdigest(),
        "projectId": plan["projectId"],
        "billingAccount": plan["billingAccount"],
        "approvedStageIds": [stage["id"] for stage in plan["stages"]],  # type: ignore[index]
        "maximumMonthlyBudgetKrw": 50000,
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "rollbackReviewed": True,
    }


class InfrastructureApprovalValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan_fixture()
        self.raw = plan_bytes(self.plan)
        self.approval = approval_fixture(self.plan, self.raw)

    def test_accepts_exact_plan_bound_approval_awaiting_cloud_mutation(self) -> None:
        result = validate_infrastructure_approval(
            self.plan, self.raw, self.approval, require_cloud_mutation=False
        )

        self.assertEqual(result["status"], "awaiting-cloud-mutation-approval")
        self.assertFalse(result["cloudMutationApproved"])
        self.assertFalse(result["deploymentApproved"])
        self.assertEqual(result["mutationCommands"], [])
        self.assertNotIn("approvedBy", result)

    def test_accepts_true_mutation_boundary_only_when_requested(self) -> None:
        candidate = copy.deepcopy(self.approval)
        candidate["cloudMutationApproved"] = True

        result = validate_infrastructure_approval(
            self.plan, self.raw, candidate, require_cloud_mutation=True
        )

        self.assertEqual(result["status"], "cloud-mutation-approved")
        self.assertTrue(result["cloudMutationApproved"])

    def test_rejects_invalid_contract_values_and_mismatches(self) -> None:
        cases = (
            ("pending", lambda item: item.__setitem__("decision", "pending"), "decision"),
            ("timestamp", lambda item: item.__setitem__("approvedAt", "2026-07-27"), "approvedAt"),
            ("approvers", lambda item: item.__setitem__("approvedBy", ["a", "a"]), "duplicate"),
            ("commit", lambda item: item.__setitem__("commitSha", "A" * 40), "commitSha"),
            ("plan digest", lambda item: item.__setitem__("planSha256", "0" * 64), "digest"),
            ("project", lambda item: item.__setitem__("projectId", "rhwp-prod-001"), "projectId"),
            ("billing", lambda item: item.__setitem__("billingAccount", "bad"), "billingAccount"),
            ("stages", lambda item: item.__setitem__("approvedStageIds", ["budget-guardrails", "project-billing"]), "approvedStageIds"),
            ("budget", lambda item: item.__setitem__("maximumMonthlyBudgetKrw", True), "maximumMonthlyBudgetKrw"),
            ("deployment", lambda item: item.__setitem__("deploymentApproved", True), "deploymentApproved"),
            ("rollback", lambda item: item.__setitem__("rollbackReviewed", False), "rollbackReviewed"),
            ("mutation required", lambda item: item.__setitem__("cloudMutationApproved", False), "cloudMutationApproved"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.approval)
                mutate(candidate)
                with self.assertRaisesRegex(InfrastructureApprovalError, pattern):
                    validate_infrastructure_approval(
                        self.plan,
                        self.raw,
                        candidate,
                        require_cloud_mutation=label == "mutation required",
                    )

    def test_rejects_impossible_timestamp_and_padded_evidence_identifiers(self) -> None:
        cases = (
            ("timestamp", "approvedAt", "2026-02-30T25:61:61Z", "approvedAt"),
            ("commit", "commitSha", " " + "1" * 40, "commitSha"),
            ("digest", "planSha256", " " + hashlib.sha256(self.raw).hexdigest(), "planSha256"),
            ("project", "projectId", " rhwp-collaboration-staging-001", "projectId"),
            ("billing", "billingAccount", " 123456-ABCDEF-123456", "billingAccount"),
            ("stage", "approvedStageIds", [" project-billing", "budget-guardrails"], "approvedStageIds"),
        )
        for label, key, value, pattern in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.approval)
                candidate[key] = value
                with self.assertRaisesRegex(InfrastructureApprovalError, pattern):
                    validate_infrastructure_approval(
                        self.plan, self.raw, candidate, require_cloud_mutation=False
                    )

    def test_rejects_approvers_with_surrounding_whitespace(self) -> None:
        for approvers in (["owner", " owner"], ["owner", "owner "]):
            with self.subTest(approvers=approvers):
                candidate = copy.deepcopy(self.approval)
                candidate["approvedBy"] = approvers
                with self.assertRaisesRegex(InfrastructureApprovalError, "approvedBy"):
                    validate_infrastructure_approval(
                        self.plan, self.raw, candidate, require_cloud_mutation=False
                    )

    def test_rejects_plan_object_that_does_not_match_exact_plan_bytes(self) -> None:
        candidate = copy.deepcopy(self.plan)
        candidate["stages"][1]["resources"]["amount"] = 60000  # type: ignore[index]

        with self.assertRaisesRegex(InfrastructureApprovalError, "plan object"):
            validate_infrastructure_approval(
                candidate, self.raw, self.approval, require_cloud_mutation=False
            )

        type_changed = copy.deepcopy(self.plan)
        type_changed["stages"][1]["resources"]["metadata"] = True  # type: ignore[index]
        with self.assertRaisesRegex(InfrastructureApprovalError, "plan object"):
            validate_infrastructure_approval(
                type_changed, self.raw, self.approval, require_cloud_mutation=False
            )

    def test_binds_budget_to_one_budget_guardrails_stage(self) -> None:
        mismatched_approval = copy.deepcopy(self.approval)
        mismatched_approval["maximumMonthlyBudgetKrw"] = 60000
        with self.assertRaisesRegex(InfrastructureApprovalError, "budget"):
            validate_infrastructure_approval(
                self.plan, self.raw, mismatched_approval, require_cloud_mutation=False
            )

        for label, mutate in (
            ("missing", lambda plan: plan.__setitem__("stages", plan["stages"][:1])),
            ("duplicate", lambda plan: plan["stages"].append(copy.deepcopy(plan["stages"][1]))),
            ("malformed", lambda plan: plan["stages"][1].__setitem__("resources", {"amount": True})),
        ):
            with self.subTest(label=label):
                candidate_plan = copy.deepcopy(self.plan)
                mutate(candidate_plan)
                candidate_raw = plan_bytes(candidate_plan)
                candidate_approval = approval_fixture(candidate_plan, candidate_raw)
                with self.assertRaisesRegex(InfrastructureApprovalError, "budget"):
                    validate_infrastructure_approval(
                        candidate_plan,
                        candidate_raw,
                        candidate_approval,
                        require_cloud_mutation=False,
                    )

    def test_markdown_replaces_line_breaking_control_characters(self) -> None:
        result = validate_infrastructure_approval(
            self.plan, self.raw, self.approval, require_cloud_mutation=False
        )
        result["approvedStageIds"] = ["project-billing\r\n- injected"]

        markdown = render_markdown(result)

        self.assertNotIn("\r", markdown)
        self.assertIn("`project-billing  - injected`", markdown)

    def test_rejects_unknown_missing_sensitive_and_non_staging_data_without_values(self) -> None:
        cases = (
            ("unknown", lambda item: item.__setitem__("unexpected", True), "unknown"),
            ("missing", lambda item: item.pop("decision"), "missing"),
            ("sensitive", lambda item: item.__setitem__("privateKey", "must-not-leak"), "sensitive"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.approval)
                mutate(candidate)
                with self.assertRaises(InfrastructureApprovalError) as caught:
                    validate_infrastructure_approval(
                        self.plan, self.raw, candidate, require_cloud_mutation=False
                    )
                self.assertRegex(str(caught.exception), pattern)
                self.assertNotIn("must-not-leak", str(caught.exception))

        production_plan = copy.deepcopy(self.plan)
        production_plan["projectId"] = "rhwp-production-001"
        raw = plan_bytes(production_plan)
        approval = approval_fixture(production_plan, raw)
        with self.assertRaisesRegex(InfrastructureApprovalError, "staging"):
            validate_infrastructure_approval(
                production_plan, raw, approval, require_cloud_mutation=False
            )

    def test_rejects_firebase_api_key_and_internal_flush_token_key_paths(self) -> None:
        for key, value in (
            ("firebaseApiKeyRaw", "firebase-value-must-not-leak"),
            ("internalFlushTokenValue", "flush-value-must-not-leak"),
        ):
            with self.subTest(key=key):
                candidate = copy.deepcopy(self.approval)
                candidate[key] = value
                with self.assertRaises(InfrastructureApprovalError) as caught:
                    validate_infrastructure_approval(
                        self.plan, self.raw, candidate, require_cloud_mutation=False
                    )
                self.assertIn("sensitive", str(caught.exception).lower())
                self.assertNotIn(value, str(caught.exception))

    def test_rejects_oversized_or_lone_surrogate_direct_plan_bytes_and_generic_token(self) -> None:
        for raw in (b" " * (MAX_JSON_BYTES + 1), b'{"value":"\\ud800"}'):
            with self.subTest(size=len(raw)):
                with self.assertRaises(InfrastructureApprovalError):
                    validate_infrastructure_approval(
                        self.plan, raw, self.approval, require_cloud_mutation=False
                    )
        candidate = copy.deepcopy(self.approval)
        candidate["token"] = "must-not-leak"
        with self.assertRaises(InfrastructureApprovalError) as caught:
            validate_infrastructure_approval(
                self.plan, self.raw, candidate, require_cloud_mutation=False
            )
        self.assertNotIn("must-not-leak", str(caught.exception))

    def test_accepts_canonical_safe_secret_values_declaration_only_when_false(self) -> None:
        manifest, packet = manifest_and_packet()
        _, packet_digest = packet_text_and_digest(packet)
        plan = build_infrastructure_plan(
            manifest,
            packet,
            bootstrap_approval_record(packet, packet_digest),
            packet_digest,
        )
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)

        result = validate_infrastructure_approval(
            plan, raw, approval, require_cloud_mutation=False
        )
        self.assertEqual(result["status"], "awaiting-cloud-mutation-approval")

        for unsafe_value in (True, "false"):
            with self.subTest(unsafe_value=unsafe_value):
                candidate_plan = copy.deepcopy(plan)
                candidate_plan["security"]["secretValuesIncluded"] = unsafe_value
                candidate_raw = plan_bytes(candidate_plan)
                candidate_approval = approval_fixture(candidate_plan, candidate_raw)
                with self.assertRaisesRegex(InfrastructureApprovalError, "sensitive"):
                    validate_infrastructure_approval(
                        candidate_plan,
                        candidate_raw,
                        candidate_approval,
                        require_cloud_mutation=False,
                    )


class InfrastructureApprovalCliTest(unittest.TestCase):
    def test_cli_rejects_fifo_promptly_without_partial_outputs(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        script = Path(__file__).resolve().parents[1] / "staging_infrastructure_approval.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo, approval_path = root / "plan.fifo", root / "approval.json"
            output, markdown = root / "result.json", root / "result.md"
            os.mkfifo(fifo)
            approval_path.write_text(json.dumps(approval))
            completed = subprocess.run(
                [
                    sys.executable, str(script), "--plan", str(fifo),
                    "--approval", str(approval_path), "--json-output", str(output),
                    "--markdown-output", str(markdown),
                ],
                capture_output=True, text=True, timeout=2,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertFalse(output.exists())
            self.assertFalse(markdown.exists())
            self.assertFalse((root / "result.json.complete").exists())

    def test_cli_writes_atomic_sanitized_json_and_markdown(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            json_output = root / "nested/result.json"
            markdown_output = root / "nested/result.md"
            plan_path.write_bytes(raw)
            approval_path.write_text(json.dumps(approval))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main([
                    "--plan", str(plan_path),
                    "--approval", str(approval_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(exit_code, 0, stderr.getvalue())
            result = json.loads(json_output.read_text())
            self.assertEqual(result["mutationCommands"], [])
            self.assertFalse(result["deploymentApproved"])
            self.assertNotIn("repository-owner", json_output.read_text())
            self.assertIn("awaiting-cloud-mutation-approval", markdown_output.read_text())
            self.assertIn("mutationCommands", stdout.getvalue())
            marker = root / "nested/result.json.complete"
            self.assertTrue(marker.is_file())
            first_marker = marker.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([
                    "--plan", str(plan_path), "--approval", str(approval_path),
                    "--json-output", str(json_output), "--markdown-output", str(markdown_output),
                ]), 0)
            self.assertEqual(marker.read_bytes(), first_marker)

    def test_cli_rejects_oversized_and_lone_surrogate_files_without_partial_outputs(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(approval))
            for name, content in (
                ("oversized.json", b" " * (MAX_JSON_BYTES + 1)),
                ("surrogate.json", b'{"value":"\\ud800"}'),
            ):
                plan_path = root / name
                output, markdown = root / f"{name}.out", root / f"{name}.md"
                plan_path.write_bytes(content)
                with redirect_stderr(io.StringIO()):
                    result = main([
                        "--plan", str(plan_path), "--approval", str(approval_path),
                        "--json-output", str(output), "--markdown-output", str(markdown),
                    ])
                self.assertEqual(result, 1)
                self.assertFalse(output.exists())
                self.assertFalse(markdown.exists())
                self.assertFalse(output.with_name(output.name + ".complete").exists())

    def test_strict_json_loading_rejects_duplicate_keys_and_non_finite_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            non_finite = root / "non-finite.json"
            duplicate.write_text('{"schemaVersion":"one","schemaVersion":"two"}')
            non_finite.write_text('{"value":NaN}')

            for path in (duplicate, non_finite):
                with self.subTest(path=path.name):
                    with self.assertRaisesRegex(InfrastructureApprovalError, "valid JSON"):
                        load_json_with_bytes(path, "fixture")

    def test_cli_rejects_overlapping_outputs_and_leaves_no_partial_files(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            plan_path.write_bytes(raw)
            approval_path.write_text(json.dumps(approval))
            same = root / "result"
            nested = root / "nested/result.json"
            bad_approval = root / "bad-approval.json"
            bad_approval.write_text("{}")

            same_exit = main([
                "--plan", str(plan_path), "--approval", str(approval_path),
                "--json-output", str(same), "--markdown-output", str(same),
            ])
            overlap_exit = main([
                "--plan", str(plan_path), "--approval", str(approval_path),
                "--json-output", str(root / "nested"), "--markdown-output", str(nested),
            ])
            failed_exit = main([
                "--plan", str(plan_path), "--approval", str(bad_approval),
                "--json-output", str(nested), "--markdown-output", str(root / "nested/result.md"),
            ])

            self.assertEqual(same_exit, 1)
            self.assertEqual(overlap_exit, 1)
            self.assertEqual(failed_exit, 1)
            self.assertFalse(same.exists())
            self.assertFalse(nested.exists())
            self.assertFalse((root / "nested/result.md").exists())

    def test_cli_rejects_input_output_aliases_before_writing(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            markdown_output = root / "result.md"
            approval_alias = root / "approval-alias.json"
            plan_path.write_bytes(raw)
            approval_path.write_text(json.dumps(approval))
            approval_alias.symlink_to(approval_path)
            original_plan, original_approval = plan_path.read_bytes(), approval_path.read_bytes()

            plan_exit = main([
                "--plan", str(plan_path), "--approval", str(approval_path),
                "--json-output", str(plan_path), "--markdown-output", str(markdown_output),
            ])
            approval_exit = main([
                "--plan", str(plan_path), "--approval", str(approval_path),
                "--json-output", str(approval_alias), "--markdown-output", str(markdown_output),
            ])

            self.assertEqual(plan_exit, 1)
            self.assertEqual(approval_exit, 1)
            self.assertEqual(plan_path.read_bytes(), original_plan)
            self.assertEqual(approval_path.read_bytes(), original_approval)
            self.assertFalse(markdown_output.exists())

    def test_cli_rolls_back_first_final_output_when_second_publish_fails(self) -> None:
        plan = plan_fixture()
        raw = plan_bytes(plan)
        approval = approval_fixture(plan, raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            json_output = root / "result.json"
            markdown_output = root / "result.md"
            plan_path.write_bytes(raw)
            approval_path.write_text(json.dumps(approval))
            original_replace = Path.replace

            def fail_markdown_publish(path: Path, target: Path) -> Path:
                if target == markdown_output:
                    raise OSError("simulated markdown publish failure")
                return original_replace(path, target)

            with patch.object(Path, "replace", fail_markdown_publish):
                exit_code = main([
                    "--plan", str(plan_path), "--approval", str(approval_path),
                    "--json-output", str(json_output), "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(exit_code, 1)
            self.assertFalse(json_output.exists())
            self.assertFalse(markdown_output.exists())
            self.assertFalse((root / "result.json.tmp").exists())
            self.assertFalse((root / "result.md.tmp").exists())
            self.assertFalse((root / "result.json.complete").exists())
