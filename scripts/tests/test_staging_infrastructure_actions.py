from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.staging_infrastructure_approval import validate_infrastructure_approval
from scripts.staging_infrastructure_plan import build_infrastructure_plan
from scripts.tests.test_staging_infrastructure_plan import (
    approved_record as bootstrap_approval_record,
    manifest_and_packet,
    packet_text_and_digest,
)

# RED: this import intentionally precedes the executor implementation.
from scripts.staging_infrastructure_actions import (  # type: ignore[import-not-found]
    InfrastructureActionsError,
    build_execution_manifest,
    main,
    render_markdown,
)


def canonical_plan_and_approval() -> tuple[dict[str, object], dict[str, object]]:
    manifest, packet = manifest_and_packet()
    packet_text, packet_digest = packet_text_and_digest(packet)
    plan = build_infrastructure_plan(
        manifest, packet, bootstrap_approval_record(packet, packet_digest), packet_digest
    )
    raw = (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode()
    approval = {
        "schemaVersion": "rhwp.staging-infrastructure-approval/v1",
        "decision": "approved",
        "approvedAt": "2026-07-27T00:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": plan["sourceEvidence"]["commitSha"],  # type: ignore[index]
        "planSha256": hashlib.sha256(raw).hexdigest(),
        "projectId": plan["projectId"],
        "billingAccount": plan["billingAccount"],
        "approvedStageIds": [stage["id"] for stage in plan["stages"]],  # type: ignore[index]
        "maximumMonthlyBudgetKrw": next(
            stage["resources"]["amount"] for stage in plan["stages"]  # type: ignore[index]
            if stage["id"] == "budget-guardrails"
        ),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "rollbackReviewed": True,
    }
    result = validate_infrastructure_approval(plan, raw, approval, require_cloud_mutation=False)
    return plan, result


def plan_bytes(plan: dict[str, object]) -> bytes:
    return (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode()


class InfrastructureActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.approval_result = canonical_plan_and_approval()

    def build(self, plan: dict[str, object], approval: dict[str, object], raw: bytes | None = None) -> dict[str, object]:
        return build_execution_manifest(plan, approval, plan_bytes=raw or plan_bytes(plan))

    def test_canonical_plan_generates_all_ordered_safe_actions(self) -> None:
        execution = self.build(self.plan, self.approval_result)

        self.assertEqual(execution["schemaVersion"], "rhwp.staging-infrastructure-execution/v1")
        self.assertEqual(execution["status"], "awaiting-cloud-mutation-approval")
        self.assertEqual(execution["projectId"], self.plan["projectId"])
        self.assertEqual(execution["billingAccount"], self.plan["billingAccount"])
        self.assertEqual(execution["sourceEvidence"]["planSha256"], self.approval_result["planSha256"])
        self.assertEqual(execution["security"], {
            "secretValuesIncluded": False,
            "productionResourcesAllowed": False,
            "deploymentAuthorized": False,
            "containsMutationCommands": False,
            "mutationCommands": [],
        })
        expected = {
            "project-billing": ("observation-only", ["verify-project", "verify-billing-link", "verify-production-separation"]),
            "api-baseline": ("eligible-mutation", ["ensure-api-enabled"] * 11),
            "firebase-foundation": ("irreversible-manual-decision", ["verify-firebase-project", "verify-firestore-location", "verify-storage-bucket", "verify-hosting-site"]),
            "service-accounts": ("eligible-mutation", ["ensure-service-account"] * 4),
            "artifact-registry": ("eligible-mutation", ["ensure-artifact-repository"]),
            "secret-metadata": ("eligible-mutation", ["ensure-secret-container"] * len(next(stage["resources"] for stage in self.plan["stages"] if stage["id"] == "secret-metadata"))),  # type: ignore[index]
            "iam-bindings": ("deferred-resource-specific", ["review-iam-binding"] * len(next(stage["resources"] for stage in self.plan["stages"] if stage["id"] == "iam-bindings"))),  # type: ignore[index]
            "budget-guardrails": ("irreversible-manual-decision", ["verify-budget", "verify-notification-channel"] * 1),
            "cloud-run-prerequisites": ("blocked-deferred", ["record-cloud-run-prerequisite"] * 3),
            "cloud-tasks-prerequisites": ("blocked-deferred", ["record-cloud-tasks-prerequisite"] * 2),
            "post-bootstrap-evidence": ("observation-only", ["collect-resource-evidence"] * len(self.plan["postBootstrapRequiredValues"])),
        }
        by_stage: dict[str, list[dict[str, object]]] = {}
        for action in execution["actions"]:
            by_stage.setdefault(action["stageId"], []).append(action)
            self.assertEqual(set(action), {"id", "stageId", "classification", "kind", "resource", "dependencies", "desiredState", "rollbackBoundary", "evidenceQuery"})
            self.assertNotRegex(json.dumps(action).lower(), r'"(command|argv|shell|secretvalue|credentialvalue|tokenvalue)"')
        self.assertEqual(list(by_stage), list(expected))
        for stage_id, (classification, kinds) in expected.items():
            self.assertEqual([action["classification"] for action in by_stage[stage_id]], [classification] * len(kinds))
            self.assertEqual([action["kind"] for action in by_stage[stage_id]], kinds)

    def test_output_is_deterministic_and_safe_to_render(self) -> None:
        first = self.build(self.plan, self.approval_result)
        second = self.build(copy.deepcopy(self.plan), copy.deepcopy(self.approval_result))
        self.assertEqual(first, second)
        markdown = render_markdown(first)
        self.assertIn("does not authorize deployment", markdown)
        self.assertNotIn("Bearer ", markdown)

    def test_rejects_plan_and_approval_binding_sensitive_data_and_contract_breaks(self) -> None:
        cases = (
            ("missing stage", lambda plan, approval: plan.__setitem__("stages", plan["stages"][1:]), "stage"),
            ("out of order", lambda plan, approval: plan["stages"].__setitem__(0, plan["stages"][1]), "stage"),
            ("production project", lambda plan, approval: plan.__setitem__("projectId", "rhwp-production-001"), "staging"),
            ("inline command", lambda plan, approval: plan["stages"][0]["resources"].__setitem__("command", "must-not-run"), "command"),
            ("secret value", lambda plan, approval: plan["stages"][5]["resources"].__setitem__("secretValue", "must-not-leak"), "sensitive"),
            ("bad approval", lambda plan, approval: approval.__setitem__("projectId", "other-staging-project"), "match"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                plan, approval = copy.deepcopy(self.plan), copy.deepcopy(self.approval_result)
                mutate(plan, approval)
                with self.assertRaisesRegex(InfrastructureActionsError, pattern):
                    self.build(plan, approval)

    def test_dependencies_must_only_reference_prior_actions(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["stages"][1]["dependsOn"] = ["post-bootstrap-evidence"]  # type: ignore[index]
        with self.assertRaisesRegex(InfrastructureActionsError, "later"):
            self.build(plan, self.approval_result)

    def test_cli_writes_both_outputs_or_neither_and_rejects_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, approval_path = root / "plan.json", root / "approval.json"
            json_output, markdown_output = root / "execution.json", root / "execution.md"
            plan_path.write_text(json.dumps(self.plan, ensure_ascii=False, indent=2) + "\n")
            approval_path.write_text(json.dumps(self.approval_result, ensure_ascii=False, indent=2) + "\n")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--plan", str(plan_path), "--approval", str(approval_path), "--json-output", str(json_output), "--markdown-output", str(markdown_output)]), 0)
            self.assertTrue(json_output.exists())
            self.assertTrue(markdown_output.exists())
            original = plan_path.read_bytes()
            alias = root / "plan-alias.json"
            alias.symlink_to(plan_path)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["--plan", str(plan_path), "--approval", str(approval_path), "--json-output", str(alias), "--markdown-output", str(markdown_output)]), 1)
            self.assertEqual(plan_path.read_bytes(), original)

    def test_rejects_temp_aliases_before_any_input_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, approval_path = root / "execution.json.tmp", root / "approval.json"
            json_output, markdown_output = root / "execution.json", root / "execution.md"
            plan_path.write_text(json.dumps(self.plan))
            approval_path.write_text(json.dumps(self.approval_result))
            original = plan_path.read_bytes()
            with redirect_stderr(io.StringIO()):
                result = main(["--plan", str(plan_path), "--approval", str(approval_path), "--json-output", str(json_output), "--markdown-output", str(markdown_output)])
            self.assertEqual(result, 1)
            self.assertEqual(plan_path.read_bytes(), original)
            self.assertFalse(json_output.exists())
            plan_path = root / "plan.json"
            approval_path = root / "execution.md.tmp"
            plan_path.write_text(json.dumps(self.plan))
            approval_path.write_text(json.dumps(self.approval_result))
            original = approval_path.read_bytes()
            with redirect_stderr(io.StringIO()):
                result = main(["--plan", str(plan_path), "--approval", str(approval_path), "--json-output", str(root / "other.json"), "--markdown-output", str(root / "execution.md")])
            self.assertEqual(result, 1)
            self.assertEqual(approval_path.read_bytes(), original)

    def test_second_publication_failure_restores_outputs_without_partial_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, approval_path = root / "plan.json", root / "approval.json"
            json_output, markdown_output = root / "execution.json", root / "execution.md"
            plan_path.write_text(json.dumps(self.plan, ensure_ascii=False, indent=2) + "\n")
            approval_path.write_text(json.dumps(self.approval_result, ensure_ascii=False, indent=2) + "\n")
            original_replace = Path.replace
            def fail_markdown_publish(path: Path, target: Path) -> Path:
                if path == markdown_output.with_name(markdown_output.name + ".tmp"):
                    raise OSError("simulated markdown publish failure")
                return original_replace(path, target)
            with patch("scripts.staging_infrastructure_actions.Path.replace", autospec=True, side_effect=fail_markdown_publish), redirect_stderr(io.StringIO()):
                result = main(["--plan", str(plan_path), "--approval", str(approval_path), "--json-output", str(json_output), "--markdown-output", str(markdown_output)])
            self.assertEqual(result, 1)
            self.assertFalse(json_output.exists())
            self.assertFalse(markdown_output.exists())

    def test_rejects_cross_binding_and_nested_contract_tampering(self) -> None:
        cases = (
            ("approval digest", lambda plan, approval: approval.__setitem__("planSha256", "0" * 64), "digest"),
            ("approval status", lambda plan, approval: approval.__setitem__("cloudMutationApproved", True), "status"),
            ("project stage mismatch", lambda plan, approval: plan["stages"][0]["resources"].__setitem__("projectId", "other-staging-project"), "project"),
            ("forbidden empty", lambda plan, approval: plan["stages"][0]["resources"].__setitem__("forbiddenProjectIds", []), "forbidden"),
            ("cloud run state", lambda plan, approval: plan["stages"][8]["resources"]["collaboration"].__setitem__("state", "ready"), "cloud-run"),
            ("cloud tasks setting", lambda plan, approval: plan["stages"][9]["resources"]["parse"].pop("retry"), "cloud-tasks"),
            ("evidence malformed", lambda plan, approval: plan["stages"][10]["resources"].append({"path": "x"}), "evidence"),
            ("evidence duplicate", lambda plan, approval: plan["stages"][10]["resources"].append(copy.deepcopy(plan["stages"][10]["resources"][0])), "duplicate"),
            ("bare token", lambda plan, approval: plan.__setitem__("token", "must-not-leak"), "sensitive"),
            ("bare secret", lambda plan, approval: plan.__setitem__("secret", "must-not-leak"), "sensitive"),
            ("api key", lambda plan, approval: plan.__setitem__("api_key", "must-not-leak"), "sensitive"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                plan, approval = copy.deepcopy(self.plan), copy.deepcopy(self.approval_result)
                mutate(plan, approval)
                with self.assertRaisesRegex(InfrastructureActionsError, pattern):
                    self.build(plan, approval)

    def test_requires_exact_plan_bytes_and_canonical_mutation_flags(self) -> None:
        compact = json.dumps(self.plan, ensure_ascii=False, separators=(",", ":")).encode()
        approval = copy.deepcopy(self.approval_result)
        approval["planSha256"] = hashlib.sha256(compact).hexdigest()
        self.build(self.plan, approval, compact)
        with self.assertRaisesRegex(InfrastructureActionsError, "digest"):
            self.build(self.plan, approval, plan_bytes(self.plan))
        self.assertEqual(
            build_execution_manifest(self.plan, self.approval_result)["projectId"],
            self.plan["projectId"],
        )
        plan = copy.deepcopy(self.plan)
        plan["stages"][0]["mutationApprovalRequired"] = False
        with self.assertRaisesRegex(InfrastructureActionsError, "mutationApprovalRequired"):
            self.build(plan, self.approval_result)

    def test_rejects_empty_required_resources_and_firebase_project_mismatch(self) -> None:
        cases = (
            ("firebase project", lambda plan: plan["stages"][2]["resources"].__setitem__("projectId", "other-staging"), "firebase"),
            ("api", lambda plan: plan["stages"][1].__setitem__("resources", [""]), "API"),
            ("identity", lambda plan: plan["stages"][3]["resources"].__setitem__("collaboration", None), "service-account"),
            ("artifact", lambda plan: plan["stages"][4]["resources"].__setitem__("repository", None), "artifact"),
            ("secret", lambda plan: next(iter(plan["stages"][5]["resources"].values())).__setitem__("name", ""), "secret"),
            ("iam", lambda plan: plan["stages"][6]["resources"][0].__setitem__("principal", None), "iam"),
            ("budget", lambda plan: plan["stages"][7]["resources"].__setitem__("notificationChannels", []), "budget"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                plan = copy.deepcopy(self.plan)
                mutate(plan)
                with self.assertRaisesRegex(InfrastructureActionsError, pattern):
                    self.build(plan, self.approval_result)

    def test_rejects_sensitive_values_and_executable_key_variants(self) -> None:
        cases = (
            ("bearer", lambda plan: plan["stages"][0].__setitem__("rollbackBoundary", "Bearer must-not-leak"), "sensitive value"),
            ("private key", lambda plan: plan["stages"][0].__setitem__("intent", "-----BEGIN PRIVATE KEY-----"), "sensitive value"),
            ("command variant", lambda plan: plan["stages"][0]["resources"].__setitem__("commandString", "not-run"), "executable"),
            ("shell variant", lambda plan: plan["stages"][0]["resources"].__setitem__("shell_command", "not-run"), "executable"),
        )
        for label, mutate, pattern in cases:
            with self.subTest(label=label):
                plan = copy.deepcopy(self.plan)
                mutate(plan)
                with self.assertRaisesRegex(InfrastructureActionsError, pattern):
                    self.build(plan, self.approval_result)

    def test_actions_retain_budget_and_cloud_run_prerequisite_details(self) -> None:
        execution = self.build(self.plan, self.approval_result)
        actions = {action["id"]: action for action in execution["actions"]}
        budget = next(stage["resources"] for stage in self.plan["stages"] if stage["id"] == "budget-guardrails")
        budget_action = actions["budget-guardrails.verify-budget"]
        self.assertEqual(budget_action["resource"], {"currency": budget["currency"], "amount": budget["amount"], "thresholds": budget["thresholds"]})
        self.assertEqual(budget_action["desiredState"]["thresholds"], budget["thresholds"])
        notification = actions["budget-guardrails.verify-notification-channel"]
        self.assertEqual(notification["resource"]["notificationChannels"], budget["notificationChannels"])
        cloud_run = next(stage["resources"] for stage in self.plan["stages"] if stage["id"] == "cloud-run-prerequisites")
        action = actions["cloud-run-prerequisites.record-collaboration"]
        self.assertEqual(action["resource"], {"service": cloud_run["collaboration"]["name"], "serviceAccount": cloud_run["collaboration"]["serviceAccount"], "ingress": cloud_run["collaboration"]["ingress"], "runtime": cloud_run["collaboration"]["runtime"], "state": "blocked-pending-image-digest"})
