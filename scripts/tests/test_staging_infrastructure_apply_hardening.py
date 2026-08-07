from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.staging_infrastructure_apply_approval import MutationApprovalError, validate_apply_ready_package
from scripts.staging_infrastructure_apply_executor import _observe_fixed, _observe_records
from scripts.tests import test_staging_infrastructure_apply_executor as executor_tests


class ApplyHardeningTest(unittest.TestCase):
    def setUp(self) -> None:
        executor_tests.ApplyExecutorTest.setUp(self)

    def test_credential_shaped_rollback_string_fails_before_approval(self) -> None:
        package = copy.deepcopy(self.package)
        package["reviewPackage"]["canonicalMutationSubset"][0]["rollbackDisposition"] = "Bearer synthetic-token-value"
        with self.assertRaises(MutationApprovalError):
            validate_apply_ready_package(package)

    def test_sensitive_leaf_detector_rejects_key_material_without_echo(self) -> None:
        package = copy.deepcopy(self.package)
        package["wifAttestation"]["serviceAccount"] = "-----BEGIN PRIVATE KEY-----"
        with self.assertRaises(MutationApprovalError) as caught:
            validate_apply_ready_package(package)
        self.assertNotIn("PRIVATE KEY", str(caught.exception))

    def test_service_account_key_presence_is_an_incompatible_observation(self) -> None:
        action = next(item for item in self.review["canonicalMutationSubset"] if item["resourceKind"] == "ensure-service-account")
        result = _observe_records("ensure-service-account", self.review["projectId"], action["resourceIdentifier"], [{"email": action["resourceIdentifier"]["identity"]}])
        self.assertEqual(result["state"], "present")
        self.assertFalse(result["matchesDesired"] is False)

    def test_live_service_account_observation_rejects_user_managed_keys(self) -> None:
        action = next(item for item in self.review["canonicalMutationSubset"] if item["resourceKind"] == "ensure-service-account")
        identity = action["resourceIdentifier"]["identity"]
        replies = iter([
            SimpleNamespace(returncode=0, stdout='[{"email":"' + identity + '"}]'),
            SimpleNamespace(returncode=0, stdout='[{"name":"redacted"}]'),
        ])
        with patch("scripts.staging_infrastructure_apply_executor.subprocess.run", side_effect=lambda *args, **kwargs: next(replies)) as run:
            observed = _observe_fixed(self.review["projectId"], action)
        self.assertEqual(observed["state"], "incompatible")
        self.assertEqual(run.call_count, 2)
        self.assertIn("--managed-by=user", run.call_args_list[1].args[0])

    def test_secret_observation_accepts_numeric_project_resource_name(self) -> None:
        action = next(item for item in self.review["canonicalMutationSubset"] if item["resourceKind"] == "ensure-secret-container")
        name = action["resourceIdentifier"]["name"]
        result = _observe_records(
            "ensure-secret-container",
            self.review["projectId"],
            action["resourceIdentifier"],
            [{"name": f"projects/598693744358/secrets/{name}", "replication": {"automatic": {}}}],
        )
        self.assertEqual(result, {"state": "present", "resourceKind": "ensure-secret-container", "matchesDesired": True})

    def test_secret_observation_requires_numeric_project_resource_and_exact_name(self) -> None:
        action = next(item for item in self.review["canonicalMutationSubset"] if item["resourceKind"] == "ensure-secret-container")
        name = action["resourceIdentifier"]["name"]
        observations = [
            {"name": f"projects/{self.review['projectId']}/secrets/{name}", "replication": {"automatic": {}}},
            {"name": f"projects/598693744358/secrets/other-secret", "replication": {"automatic": {}}},
            {"name": f"projects/598693744358/secrets/{name}", "replication": {"userManaged": {}}},
        ]
        for observation in observations:
            with self.subTest(observation=observation):
                result = _observe_records("ensure-secret-container", self.review["projectId"], action["resourceIdentifier"], [observation])
                self.assertEqual(result["state"], "incompatible")
                self.assertFalse(result["matchesDesired"])

    def test_secret_observation_keeps_project_scoped_list_query(self) -> None:
        action = next(item for item in self.review["canonicalMutationSubset"] if item["resourceKind"] == "ensure-secret-container")
        name = action["resourceIdentifier"]["name"]
        reply = SimpleNamespace(
            returncode=0,
            stdout='[{"name":"projects/598693744358/secrets/' + name + '","replication":{"automatic":{}}}]',
        )
        with patch("scripts.staging_infrastructure_apply_executor.subprocess.run", return_value=reply) as run:
            observed = _observe_fixed(self.review["projectId"], action)
        self.assertEqual(observed["state"], "present")
        argv = run.call_args.args[0]
        self.assertIn("--project", argv)
        self.assertIn(self.review["projectId"], argv)


if __name__ == "__main__":
    unittest.main()
