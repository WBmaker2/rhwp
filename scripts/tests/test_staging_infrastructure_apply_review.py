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

from scripts.staging_infrastructure_actions import build_execution_manifest
from scripts.tests.test_staging_infrastructure_actions import (
    canonical_plan_and_approval,
    plan_bytes,
)

from scripts.staging_infrastructure_apply_review import (
    ApplyReviewError,
    build_apply_review_package,
    main,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_COMMIT = "a" * 40
ELIGIBLE_STAGES = {
    "api-baseline",
    "service-accounts",
    "artifact-registry",
    "secret-metadata",
}


class ApplyReviewPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.approval = canonical_plan_and_approval()
        self.raw = plan_bytes(self.plan)
        self.execution = build_execution_manifest(
            self.plan,
            self.approval,
            plan_bytes=self.raw,
        )

    def build(
        self,
        *,
        plan: dict[str, object] | None = None,
        approval: dict[str, object] | None = None,
        execution: dict[str, object] | None = None,
        raw: bytes | None = None,
        commit: str = EXECUTOR_COMMIT,
    ) -> dict[str, object]:
        return build_apply_review_package(
            plan or self.plan,
            approval or self.approval,
            execution or self.execution,
            plan_bytes=raw or self.raw,
            executor_commit_sha=commit,
        )

    def test_builds_deterministic_non_mutating_review_package(self) -> None:
        package = self.build()

        self.assertEqual(package["schemaVersion"], "rhwp.staging-infrastructure-apply-review/v2")
        self.assertEqual(package["status"], "ready-for-apply-review")
        self.assertEqual(package["executorCommit"]["sha"], EXECUTOR_COMMIT)
        self.assertEqual(
            package["executorCommit"]["provenance"], "caller-declared-unverified"
        )
        self.assertFalse(package["executorCommit"]["immutableVerifiedProvenance"])
        self.assertIn(
            "verify-commit-membership-in-approved-branch",
            package["executorCommit"]["independentVerificationRequired"],
        )
        self.assertEqual(package["projectId"], self.plan["projectId"])
        self.assertEqual(package["sourceEvidence"]["planSha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(
            package["sourceEvidence"]["actionSetSha256"],
            self.execution["sourceEvidence"]["actionSetSha256"],
        )
        self.assertEqual(
            {item["stageId"] for item in package["canonicalMutationSubset"]},
            ELIGIBLE_STAGES,
        )
        self.assertTrue(package["canonicalMutationSubset"])
        self.assertEqual(package["cloudMutationApproved"], False)
        self.assertEqual(package["deploymentApproved"], False)
        self.assertEqual(package["mutationCommands"], [])
        self.assertEqual(package, self.build())
        self.assertIn("ready-for-apply-review", render_markdown(package))

    def test_subset_has_only_structured_non_executable_candidates(self) -> None:
        package = self.build()
        encoded = json.dumps(package, ensure_ascii=False)

        for candidate in package["canonicalMutationSubset"]:
            self.assertEqual(
                set(candidate),
                {
                    "actionId",
                    "stageId",
                    "resourceKind",
                    "resourceIdentifier",
                    "desiredState",
                    "preconditionEvidence",
                    "rollbackDisposition",
                },
            )
        self.assertNotRegex(
            encoded.lower(),
            r'"(?:command|argv|shell|accesstoken|idtoken|authorization|privatekey|secretvalue)"',
        )

    def test_environment_and_wif_are_review_specs_not_applied_values(self) -> None:
        package = self.build()
        environment = package["protectedEnvironmentSpec"]
        identity = package["wifIdentityAndIamDiff"]

        self.assertEqual(environment["name"], "staging-infrastructure-apply")
        self.assertEqual(environment["requiredReviewerCountMinimum"], 1)
        self.assertFalse(environment["preventSelfReview"])
        branch_policy = environment["deploymentBranchPolicy"]
        self.assertFalse(branch_policy["protectedBranches"])
        self.assertTrue(branch_policy["customBranchPolicies"])
        self.assertEqual(
            branch_policy["branchPolicies"],
            [{"name": "feat/firebase-collaboration-mvp-v1", "type": "branch"}],
        )
        self.assertEqual(branch_policy["tagPolicies"], [])
        self.assertEqual(environment["secrets"], [])
        self.assertEqual(environment["longLivedCloudCredentials"], [])
        self.assertEqual(environment["currentReviewJobPermissions"]["id-token"], "none")
        self.assertEqual(environment["currentReviewJobPermissions"]["actions"], "read")
        self.assertEqual(environment["futureApplyJobPermissions"]["id-token"], "write")
        self.assertEqual(
            environment["variableNames"],
            [
                "GCP_WORKLOAD_IDENTITY_PROVIDER",
                "GCP_DEPLOYER_SERVICE_ACCOUNT",
                "STAGING_PROJECT_ID",
                "STAGING_APPROVED_REPOSITORY",
                "STAGING_APPROVED_REPOSITORY_ID",
                "STAGING_APPROVED_REPOSITORY_OWNER_ID",
                "STAGING_APPROVED_REF",
                "STAGING_APPROVED_WORKFLOW_REF",
                "STAGING_APPROVED_WORKFLOW_SHA",
                "STAGING_APPROVED_WORKFLOW_CONTENT_SHA256",
                "STAGING_APPROVED_EXECUTOR_TREE_SHA",
                "STAGING_APPROVED_APPLY_READY_PACKAGE_JSON",
                "STAGING_APPROVED_MUTATION_APPROVAL_JSON",
            ],
        )
        self.assertEqual(identity["status"], "proposed-diff-requires-live-review")
        roles = {
            binding["role"]
            for binding in identity["candidateBindings"]
            if "role" in binding
        }
        self.assertNotIn("roles/owner", roles)
        self.assertNotIn("roles/editor", roles)
        self.assertTrue(identity["serviceAccountKeysAllowed"] is False)
        self.assertNotIn("providerId", identity)
        self.assertNotIn("serviceAccountEmail", identity)
        self.assertEqual(
            identity["attributeMapping"],
            {
                "google.subject": "assertion.sub",
                "attribute.repository": "assertion.repository",
                "attribute.ref": "assertion.ref",
                "attribute.workflow_ref": "assertion.workflow_ref",
                "attribute.repository_id": "assertion.repository_id",
                "attribute.repository_owner_id": "assertion.repository_owner_id",
                "attribute.workflow_sha": "assertion.workflow_sha",
            },
        )
        self.assertEqual(
            identity["oidcAttributeConditions"]["workflowRef"],
            "WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml"
            "@refs/heads/feat/firebase-collaboration-mvp-v1",
        )
        self.assertFalse(identity["oidcAttributeConditions"]["implemented"])
        self.assertIn(
            ".github/workflows/staging-infrastructure-apply-review.yml",
            identity["oidcAttributeConditions"]["excludedWorkflows"],
        )

        custom_roles = identity["candidateBindings"][1:]
        self.assertTrue(all(role["roleType"] == "custom" for role in custom_roles))
        self.assertEqual({role["roleId"] for role in custom_roles}, {"stagingApiEnableOnly", "stagingServiceAccountCreateReadList", "stagingArtifactRegistryRepositoryCreateRead", "stagingSecretManagerMetadataCreateReadList"})
        permissions = {
            role["roleId"]: role["includedPermissions"] for role in custom_roles
        }
        self.assertEqual(permissions["stagingApiEnableOnly"], ["serviceusage.services.enable"])
        self.assertEqual(permissions["stagingServiceAccountCreateReadList"], ["iam.serviceAccounts.create", "iam.serviceAccounts.get", "iam.serviceAccounts.list", "iam.serviceAccountKeys.list"])
        self.assertEqual(
            permissions["stagingArtifactRegistryRepositoryCreateRead"],
            [
                "artifactregistry.repositories.create",
                "artifactregistry.repositories.get",
                "artifactregistry.repositories.list",
            ],
        )
        self.assertEqual(
            permissions["stagingSecretManagerMetadataCreateReadList"],
            [
                "secretmanager.secrets.create",
                "secretmanager.secrets.get",
                "secretmanager.secrets.list",
            ],
        )
        excluded_permissions = json.dumps(
            [role["excludedPermissions"] for role in custom_roles]
        )
        self.assertIn("serviceusage.services.disable", excluded_permissions)
        self.assertIn("iam.serviceAccountKeys.create", excluded_permissions)
        self.assertIn("artifactregistry.repositories.delete", excluded_permissions)
        self.assertIn("secretmanager.versions.access", excluded_permissions)
        self.assertTrue(identity["liveProjectScopeBindingDiffRequired"])
        self.assertEqual(
            identity["projectScopeTruth"],
            {
                "createEnablePermissionsRequireProjectScope": True,
                "iamScopeConstrainsResourceIdentifiers": False,
                "independentExecutorAllowlistRequired": True,
            },
        )
        self.assertTrue(
            all(role["scope"] == "staging-project" for role in custom_roles)
        )
        allowlist = package["executorActionAllowlistEnforcement"]
        self.assertTrue(allowlist["implemented"])
        self.assertFalse(allowlist["iamScopeAloneSufficient"])
        self.assertTrue(allowlist["independentExecutorEnforcementRequired"])
        self.assertTrue(allowlist["liveProjectScopeBindingDiffRequired"])
        self.assertEqual(
            {entry["actionId"] for entry in allowlist["approvedActions"]},
            {entry["actionId"] for entry in package["canonicalMutationSubset"]},
        )

    def test_rejects_plan_bytes_execution_tamper_and_bad_executor_commit(self) -> None:
        with self.assertRaisesRegex(ApplyReviewError, "digest|bytes|plan"):
            self.build(raw=json.dumps(self.plan, separators=(",", ":")).encode())

        tampered = copy.deepcopy(self.execution)
        tampered["actions"][0], tampered["actions"][1] = (
            tampered["actions"][1],
            tampered["actions"][0],
        )
        with self.assertRaisesRegex(ApplyReviewError, "execution manifest"):
            self.build(execution=tampered)

        with self.assertRaisesRegex(ApplyReviewError, "executor commit"):
            self.build(commit="main")

    def test_rejects_cloud_approval_production_and_sensitive_values(self) -> None:
        approval = copy.deepcopy(self.approval)
        approval["cloudMutationApproved"] = True
        approval["status"] = "cloud-mutation-approved"
        with self.assertRaises(ApplyReviewError):
            self.build(approval=approval)

        plan = copy.deepcopy(self.plan)
        plan["projectId"] = "rhwp-production-001"
        with self.assertRaises(ApplyReviewError):
            self.build(plan=plan)

        execution = copy.deepcopy(self.execution)
        execution["privateKey"] = "must-not-leak"
        with self.assertRaises(ApplyReviewError) as caught:
            self.build(execution=execution)
        self.assertNotIn("must-not-leak", str(caught.exception))

    def test_cli_publishes_pair_and_completion_marker(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            execution_path = root / "execution.json"
            json_output = root / "review.json"
            markdown_output = root / "review.md"
            plan_path.write_bytes(self.raw)
            approval_path.write_text(json.dumps(self.approval) + "\n")
            execution_path.write_text(json.dumps(self.execution) + "\n")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--approval-result",
                        str(approval_path),
                        "--execution-manifest",
                        str(execution_path),
                        "--executor-commit-sha",
                        EXECUTOR_COMMIT,
                        "--json-output",
                        str(json_output),
                        "--markdown-output",
                        str(markdown_output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue(json_output.exists())
            self.assertTrue(markdown_output.exists())
            self.assertTrue((root / "review.json.complete").exists())
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ready-for-apply-review")

    def test_cli_fails_closed_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            approval_path = root / "approval.json"
            execution_path = root / "execution.json"
            plan_path.write_bytes(self.raw)
            approval_path.write_text(json.dumps(self.approval) + "\n")
            tampered = copy.deepcopy(self.execution)
            tampered["actions"].reverse()
            execution_path.write_text(json.dumps(tampered) + "\n")

            with redirect_stderr(io.StringIO()):
                result = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--approval-result",
                        str(approval_path),
                        "--execution-manifest",
                        str(execution_path),
                        "--executor-commit-sha",
                        EXECUTOR_COMMIT,
                        "--json-output",
                        str(root / "review.json"),
                        "--markdown-output",
                        str(root / "review.md"),
                    ]
                )
            self.assertEqual(result, 1)
            self.assertFalse((root / "review.json").exists())
            self.assertFalse((root / "review.md").exists())

    def test_subprocess_rejects_input_output_aliases_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            inputs = {
                "--plan": root / "plan.json",
                "--approval-result": root / "approval.json",
                "--execution-manifest": root / "execution.json",
            }
            inputs["--plan"].write_bytes(self.raw)
            inputs["--approval-result"].write_text(json.dumps(self.approval))
            inputs["--execution-manifest"].write_text(json.dumps(self.execution))
            original = {flag: path.read_bytes() for flag, path in inputs.items()}
            script = ROOT / "scripts" / "staging_infrastructure_apply_review.py"
            for flag, input_path in inputs.items():
                with self.subTest(input_flag=flag):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(script),
                            "--plan", str(inputs["--plan"]),
                            "--approval-result", str(inputs["--approval-result"]),
                            "--execution-manifest", str(inputs["--execution-manifest"]),
                            "--executor-commit-sha", EXECUTOR_COMMIT,
                            "--json-output", str(input_path),
                            "--markdown-output", str(root / "review.md"),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(input_path.read_bytes(), original[flag])
                    self.assertFalse((root / "review.md").exists())
                    self.assertFalse((root / f"{input_path.name}.complete").exists())

    def test_rejects_marker_temp_parent_child_and_special_file_hazards(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            plan_path, approval_path, execution_path = (
                root / "plan.json",
                root / "approval.json",
                root / "execution.json",
            )
            plan_path.write_bytes(self.raw)
            approval_path.write_text(json.dumps(self.approval))
            execution_path.write_text(json.dumps(self.execution))
            original = {
                path: path.read_bytes()
                for path in (plan_path, approval_path, execution_path)
            }
            marker_input = root / "review.json.complete"
            marker_input.write_bytes(self.raw)
            temp_input = root / "other.json.tmp"
            temp_input.write_text(json.dumps(self.approval))
            original.update(
                {
                    marker_input: marker_input.read_bytes(),
                    temp_input: temp_input.read_bytes(),
                }
            )
            cases = [
                (marker_input, approval_path, execution_path, root / "review.json", root / "review.md"),
                (plan_path, temp_input, execution_path, root / "other.json", root / "review.md"),
                (plan_path, approval_path, execution_path, root, root / "review.md"),
            ]
            for plan, approval, execution, json_output, markdown_output in cases:
                with self.subTest(json_output=json_output, markdown_output=markdown_output):
                    with redirect_stderr(io.StringIO()):
                        result = main([
                            "--plan", str(plan),
                            "--approval-result", str(approval),
                            "--execution-manifest", str(execution),
                            "--executor-commit-sha", EXECUTOR_COMMIT,
                            "--json-output", str(json_output),
                            "--markdown-output", str(markdown_output),
                        ])
                    self.assertEqual(result, 1)
                    self.assertEqual(
                        {path: path.read_bytes() for path in original}, original
                    )
            fifo = root / "review.json.tmp"
            os.mkfifo(fifo)
            with redirect_stderr(io.StringIO()):
                result = main([
                    "--plan", str(plan_path),
                    "--approval-result", str(approval_path),
                    "--execution-manifest", str(execution_path),
                    "--executor-commit-sha", EXECUTOR_COMMIT,
                    "--json-output", str(root / "review.json"),
                    "--markdown-output", str(root / "review.md"),
                ])
            self.assertEqual(result, 1)
            self.assertTrue(fifo.exists())
            self.assertEqual(marker_input.read_bytes(), original[marker_input])


class ApplyReviewRepositoryContractTest(unittest.TestCase):
    def test_runbook_labels_executor_commit_as_unverified_and_requires_future_verification(self) -> None:
        runbook = (ROOT / "docs" / "runbooks" / "staging-infrastructure-bootstrap.md").read_text()

        self.assertIn(
            "<CALLER_DECLARED_UNVERIFIED_EXECUTOR_COMMIT_SHA>", runbook
        )
        self.assertNotIn("<REVIEWED_EXECUTOR_COMMIT_SHA>", runbook)
        self.assertNotIn("immutable executor commit", runbook)
        self.assertIn("commit object/tree", runbook)
        self.assertIn("독립 검증", runbook)

    def test_pending_mutation_approval_example_is_not_authority(self) -> None:
        path = (
            ROOT
            / "docs"
            / "approvals"
            / "staging-infrastructure-mutation-approval-record.example.json"
        )
        payload = json.loads(path.read_text())

        self.assertEqual(
            payload["schemaVersion"],
            "rhwp.staging-infrastructure-mutation-approval/v3",
        )
        self.assertEqual(payload["decision"], "pending")
        self.assertIsNone(payload["approvedAt"])
        self.assertEqual(payload["approvedBy"], [])
        self.assertFalse(payload["cloudMutationApproved"])
        self.assertFalse(payload["deploymentApproved"])
        self.assertEqual(payload["approvedActionIds"], [])

    def test_workflow_only_builds_review_artifact_without_cloud_authority(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "staging-infrastructure-apply-review.yml"
        ).read_text()
        lowered = workflow.lower()

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("mode:", workflow)
        self.assertIn("review-package", workflow)
        self.assertIn("staging-infrastructure-apply-review", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("id-token: write", lowered)
        self.assertNotIn("environment: staging-infrastructure-apply", lowered)
        self.assertNotIn("google-github-actions/auth", lowered)
        self.assertNotRegex(lowered, r"\b(?:gcloud|firebase)\b")
        self.assertNotIn("mode=apply", lowered)
        self.assertNotIn("cloudmutationapproved=true", lowered)
        self.assertIn("scripts/staging_infrastructure_synthetic_fixture.py", workflow)
        self.assertNotIn("from scripts.tests", workflow)


if __name__ == "__main__":
    unittest.main()
