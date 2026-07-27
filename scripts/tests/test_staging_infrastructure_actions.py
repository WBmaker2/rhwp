from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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


class InfrastructureActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.approval_result = canonical_plan_and_approval()

    def test_canonical_plan_generates_all_ordered_safe_actions(self) -> None:
        execution = build_execution_manifest(self.plan, self.approval_result)

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
        first = build_execution_manifest(self.plan, self.approval_result)
        second = build_execution_manifest(copy.deepcopy(self.plan), copy.deepcopy(self.approval_result))
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
                    build_execution_manifest(plan, approval)

    def test_dependencies_must_only_reference_prior_actions(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["stages"][1]["dependsOn"] = ["post-bootstrap-evidence"]  # type: ignore[index]
        with self.assertRaisesRegex(InfrastructureActionsError, "later"):
            build_execution_manifest(plan, self.approval_result)

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
