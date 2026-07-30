from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType
from unittest.mock import patch

from scripts.staging_infrastructure_apply_review_policy import (
    APPLY_BRANCH,
    APPLY_WORKFLOW_REF,
    GITHUB_OIDC_ISSUER,
    wif_attribute_mapping,
    wif_expected_condition,
    wif_expected_principal,
)
from scripts.staging_infrastructure_apply_safety import (
    ApplySafetyError,
    reject_sensitive_string_leaves,
)
from scripts.staging_infrastructure_apply_ready import (
    ApplyReadyError,
    build_apply_ready_package,
    build_operator_apply_ready_package,
)
from scripts.staging_infrastructure_environment_attestation import (
    EnvironmentAttestationError,
    _collect_pages,
    _run_fixed_gh,
    attest_environment,
)
from scripts.staging_infrastructure_operator_attestation import (
    OperatorAttestationError,
    canonical_attestation_bytes,
    issued_attestation_document,
    validate_environment_attestation,
    validate_wif_attestation,
)
from scripts.staging_infrastructure_operator_signature import (
    OperatorSignatureError,
    sign_operator_attestation,
    verify_operator_attestation_envelope,
)
from scripts.staging_infrastructure_wif_attestation import (
    WifAttestationError,
    _run_fixed_gcloud,
    attest_wif,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
PROJECT = "rhwp-collaboration-staging-123"
PROVIDER = "projects/123/locations/global/workloadIdentityPools/staging-pool/providers/staging-provider"
SERVICE_ACCOUNT = "deployer-staging@rhwp-collaboration-staging-123.iam.gserviceaccount.com"
REPOSITORY_ID, OWNER_ID, WORKFLOW_SHA = "11", "22", "a" * 40


@contextmanager
def trusted_test_operator_key():
    """Generate an ephemeral test-only Ed25519 key; it is never serialized."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        private_key, public_key = root / "operator-private.pem", root / "operator-public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.chmod(private_key, 0o600)
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        public_pem = public_key.read_text()
        registry = MappingProxyType({
            "synthetic-operator": MappingProxyType({
                "algorithm": "ed25519",
                "publicKeyPem": public_pem,
                "publicKeySha256": hashlib.sha256(public_pem.encode()).hexdigest(),
            })
        })
        with patch(
            "scripts.staging_infrastructure_operator_signature.TRUSTED_OPERATOR_KEY_REGISTRY",
            registry,
        ):
            yield "synthetic-operator", private_key


class WifOperatorAttestationTest(unittest.TestCase):
    def test_fixed_gcloud_queries_produce_short_lived_sanitized_attestation(self) -> None:
        expected_condition = wif_expected_condition(REPOSITORY_ID, OWNER_ID, WORKFLOW_SHA)
        expected_principal = wif_expected_principal(PROVIDER, REPOSITORY_ID)
        calls: list[tuple[str, ...]] = []

        def runner(argv: tuple[str, ...]) -> bytes:
            calls.append(argv)
            if "providers" in argv:
                return json.dumps({
                    "name": PROVIDER, "state": "ACTIVE", "disabled": False,
                    "attributeMapping": wif_attribute_mapping(),
                    "attributeCondition": expected_condition,
                    "oidc": {"issuerUri": GITHUB_OIDC_ISSUER, "allowedAudiences": []},
                }).encode()
            return json.dumps({"bindings": [{
                "role": "roles/iam.workloadIdentityUser", "members": [expected_principal],
            }]}).encode()

        receipt = attest_wif(
            project_id=PROJECT, provider_resource_name=PROVIDER,
            service_account=SERVICE_ACCOUNT, repository_id=REPOSITORY_ID,
            repository_owner_id=OWNER_ID, workflow_sha=WORKFLOW_SHA,
            runner=runner, now=NOW,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "gcloud")
        self.assertEqual(calls[0][1:5], ("iam", "workload-identity-pools", "providers", "describe"))
        self.assertEqual(calls[1][:4], ("gcloud", "iam", "service-accounts", "get-iam-policy"))
        attestation = receipt.document
        self.assertEqual(attestation["expected"]["attributeCondition"], expected_condition)
        self.assertEqual(attestation["expected"]["workloadIdentityUserPrincipal"], expected_principal)
        self.assertEqual(attestation["observedAt"], "2026-07-30T12:00:00Z")
        self.assertEqual(attestation["expiresAt"], "2026-07-30T12:15:00Z")
        self.assertNotIn("bindings", attestation)
        self.assertNotIn("ya29.", json.dumps(attestation).lower())
        validate_wif_attestation(
            attestation, project_id=PROJECT, workflow_sha=WORKFLOW_SHA, now=NOW
        )

    def test_wif_rejects_self_claimed_mapping_or_non_exact_binding_without_echo(self) -> None:
        expected_condition = wif_expected_condition(REPOSITORY_ID, OWNER_ID, WORKFLOW_SHA)

        def runner(_: tuple[str, ...]) -> bytes:
            return json.dumps({
                "name": PROVIDER, "state": "ACTIVE", "disabled": False,
                "attributeMapping": {"google.subject": "assertion.sub"},
                "attributeCondition": expected_condition,
                "oidc": {"issuerUri": GITHUB_OIDC_ISSUER, "allowedAudiences": []},
            }).encode()

        with self.assertRaises(WifAttestationError):
            attest_wif(
                project_id=PROJECT, provider_resource_name=PROVIDER,
                service_account=SERVICE_ACCOUNT, repository_id=REPOSITORY_ID,
                repository_owner_id=OWNER_ID, workflow_sha=WORKFLOW_SHA,
                runner=runner, now=NOW,
            )

        def leaking_runner(_: tuple[str, ...]) -> bytes:
            raise RuntimeError("ya29.synthetic-access-token-must-not-escape")

        with self.assertRaises(WifAttestationError) as caught:
            attest_wif(
                project_id=PROJECT, provider_resource_name=PROVIDER,
                service_account=SERVICE_ACCOUNT, repository_id=REPOSITORY_ID,
                repository_owner_id=OWNER_ID, workflow_sha=WORKFLOW_SHA,
                runner=leaking_runner, now=NOW,
            )
        self.assertNotIn("ya29", str(caught.exception))

    def test_wif_rejects_an_extra_workload_identity_principal(self) -> None:
        expected_condition = wif_expected_condition(REPOSITORY_ID, OWNER_ID, WORKFLOW_SHA)
        expected_principal = wif_expected_principal(PROVIDER, REPOSITORY_ID)
        responses = iter((
            json.dumps({
                "name": PROVIDER, "state": "ACTIVE", "disabled": False,
                "attributeMapping": wif_attribute_mapping(),
                "attributeCondition": expected_condition,
                "oidc": {"issuerUri": GITHUB_OIDC_ISSUER, "allowedAudiences": []},
            }).encode(),
            json.dumps({"bindings": [{
                "role": "roles/iam.workloadIdentityUser",
                "members": [expected_principal, "principalSet://iam.googleapis.com/extra"],
            }]}).encode(),
        ))
        with self.assertRaises(WifAttestationError):
            attest_wif(
                project_id=PROJECT, provider_resource_name=PROVIDER,
                service_account=SERVICE_ACCOUNT, repository_id=REPOSITORY_ID,
                repository_owner_id=OWNER_ID, workflow_sha=WORKFLOW_SHA,
                runner=lambda _: next(responses), now=NOW,
            )

    def test_fixed_command_adapters_disable_shell_and_redact_stderr(self) -> None:
        completed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"ya29.synthetic-must-not-escape"
        )
        with patch(
            "scripts.staging_infrastructure_wif_attestation.subprocess.run",
            return_value=completed,
        ) as gcloud_run:
            with self.assertRaises(WifAttestationError) as caught:
                _run_fixed_gcloud(("gcloud", "fixed", "read"))
        self.assertFalse(gcloud_run.call_args.kwargs["shell"])
        self.assertNotIn("ya29", str(caught.exception))

        with patch(
            "scripts.staging_infrastructure_environment_attestation.subprocess.run",
            return_value=completed,
        ) as gh_run:
            with self.assertRaises(EnvironmentAttestationError) as caught:
                _run_fixed_gh(("gh", "api", "--method", "GET", "/fixed"))
        self.assertFalse(gh_run.call_args.kwargs["shell"])
        self.assertNotIn("ya29", str(caught.exception))

    def test_wif_rejects_untrusted_oidc_issuer_or_custom_audience(self) -> None:
        expected_condition = wif_expected_condition(REPOSITORY_ID, OWNER_ID, WORKFLOW_SHA)
        for oidc in (
            {"issuerUri": "https://attacker.invalid", "allowedAudiences": []},
            {"issuerUri": GITHUB_OIDC_ISSUER, "allowedAudiences": ["attacker-audience"]},
        ):
            with self.subTest(oidc=oidc):
                with self.assertRaises(WifAttestationError):
                    attest_wif(
                        project_id=PROJECT, provider_resource_name=PROVIDER,
                        service_account=SERVICE_ACCOUNT, repository_id=REPOSITORY_ID,
                        repository_owner_id=OWNER_ID, workflow_sha=WORKFLOW_SHA,
                        runner=lambda _: json.dumps({
                            "name": PROVIDER, "state": "ACTIVE", "disabled": False,
                            "attributeMapping": wif_attribute_mapping(),
                            "attributeCondition": expected_condition, "oidc": oidc,
                        }).encode(),
                        now=NOW,
                    )

class EnvironmentOperatorAttestationTest(unittest.TestCase):
    def _runner(self, *, include_admin_bypass: bool = True):
        variable_names = [
            "GCP_WORKLOAD_IDENTITY_PROVIDER", "GCP_DEPLOYER_SERVICE_ACCOUNT",
            "STAGING_PROJECT_ID", "STAGING_APPROVED_REPOSITORY",
            "STAGING_APPROVED_REPOSITORY_ID", "STAGING_APPROVED_REPOSITORY_OWNER_ID",
            "STAGING_APPROVED_REF", "STAGING_APPROVED_WORKFLOW_REF",
            "STAGING_APPROVED_WORKFLOW_SHA", "STAGING_APPROVED_WORKFLOW_CONTENT_SHA256",
            "STAGING_APPROVED_EXECUTOR_TREE_SHA", "STAGING_APPROVED_APPLY_READY_PACKAGE_JSON",
            "STAGING_APPROVED_MUTATION_APPROVAL_JSON",
        ]
        calls: list[tuple[str, ...]] = []

        def runner(argv: tuple[str, ...]) -> bytes:
            calls.append(argv)
            endpoint = argv[-1]
            if endpoint == "/repos/WBmaker2/rhwp":
                return b'{"id":11,"full_name":"WBmaker2/rhwp","owner":{"id":22}}'
            if endpoint == "/repos/WBmaker2/rhwp/environments/staging-infrastructure-apply":
                value = {
                    "id": 33, "name": "staging-infrastructure-apply",
                    "protection_rules": [{
                        "type": "required_reviewers", "prevent_self_review": True,
                        "reviewers": [{"type": "User", "reviewer": {"login": "redacted"}}],
                    }],
                    "deployment_branch_policy": {
                        "protected_branches": False, "custom_branch_policies": True,
                    },
                }
                if include_admin_bypass:
                    value["can_admins_bypass"] = False
                return json.dumps(value).encode()
            if "deployment-branch-policies" in endpoint:
                return b'{"total_count":1,"branch_policies":[{"id":1,"name":"feat/firebase-collaboration-mvp-v1","type":"branch"}]}'
            if "/variables?" in endpoint:
                return json.dumps({"total_count": len(variable_names), "variables": [
                    {"name": name, "value": "not-recorded"} for name in variable_names
                ]}).encode()
            raise AssertionError(endpoint)

        return runner, calls

    def test_fixed_gh_queries_attest_all_required_fields_without_values_or_reviewer_identity(self) -> None:
        runner, calls = self._runner()
        attestation = attest_environment(runner=runner, now=NOW).document

        self.assertEqual(len(calls), 4)
        self.assertTrue(all(call[:4] == ("gh", "api", "--hostname", "github.com") for call in calls))
        self.assertTrue(all("--method" in call and "GET" in call for call in calls))
        self.assertIn("?per_page=30&page=1", calls[-1][-1])
        self.assertEqual(attestation["repositoryId"], "11")
        self.assertEqual(attestation["observed"]["requiredReviewerCount"], 1)
        encoded = json.dumps(attestation)
        self.assertNotIn("redacted", encoded)
        self.assertNotIn("not-recorded", encoded)
        validate_environment_attestation(attestation, now=NOW)
        receipt = attest_environment(runner=runner, now=NOW)
        receipt.document["status"] = "self-claimed"
        with self.assertRaises(OperatorAttestationError):
            issued_attestation_document(receipt)

    def test_missing_admin_bypass_observation_fails_closed(self) -> None:
        runner, _ = self._runner(include_admin_bypass=False)
        with self.assertRaises(EnvironmentAttestationError):
            attest_environment(runner=runner, now=NOW)

    def test_explicit_page_loop_rejects_incomplete_pagination(self) -> None:
        replies = iter([
            b'{"total_count":31,"variables":[{"name":"one"}]}',
            b'{"total_count":31,"variables":[]}',
        ])
        with self.assertRaises(EnvironmentAttestationError):
            _collect_pages(lambda _: next(replies), "/fixed", "variables")


class CredentialLeafSafetyTest(unittest.TestCase):
    def test_apply_ready_boundary_rejects_caller_supplied_attestation_json(self) -> None:
        with self.assertRaises(ApplyReadyError):
            build_apply_ready_package({}, b"{}", {}, {})  # type: ignore[arg-type]

    def test_google_and_generic_credential_shapes_are_rejected_without_value_echo(self) -> None:
        values = [
            "AIza" + "A" * 35,
            "ya29." + "x" * 24,
            "password=synthetic-value",
            "api_key=synthetic-value",
            "GOCSPX-" + "x" * 24,
            "client_secret=synthetic-value",
            "-----BEGIN PRIVATE KEY-----\\nsynthetic",
        ]
        for value in values:
            with self.subTest(value=value[:8]):
                with self.assertRaises(ApplySafetyError) as caught:
                    reject_sensitive_string_leaves({"safeNamedLeaf": value}, "test data")
                self.assertNotIn(value, str(caught.exception))

    def test_attestation_expiry_is_fail_closed(self) -> None:
        runner, _ = EnvironmentOperatorAttestationTest()._runner()
        attestation = attest_environment(runner=runner, now=NOW).document
        attestation["expiresAt"] = "2026-07-30T12:16:00Z"
        with self.assertRaises(OperatorAttestationError):
            validate_environment_attestation(attestation, now=NOW)

    def test_promotion_cli_has_no_observation_json_arguments(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "scripts/staging_infrastructure_apply_ready.py"
        ).read_text()
        self.assertNotIn('add_argument("--environment-attestation"', source)
        self.assertNotIn('add_argument("--wif-attestation"', source)

    def test_signed_receipt_survives_json_round_trip_but_rejects_digest_reissue(self) -> None:
        runner, _ = EnvironmentOperatorAttestationTest()._runner()
        payload = attest_environment(runner=runner, now=NOW).document
        with trusted_test_operator_key() as (key_id, private_key):
            envelope = sign_operator_attestation(
                payload, key_id=key_id, private_key=private_key
            )
            restored = json.loads(json.dumps(envelope))
            self.assertEqual(
                verify_operator_attestation_envelope(restored)["repositoryId"], "11"
            )
            restored["payload"]["responseDigests"]["repository"] = "0" * 64
            restored["payloadSha256"] = hashlib.sha256(
                canonical_attestation_bytes(restored["payload"])
            ).hexdigest()
            with self.assertRaises(OperatorSignatureError):
                verify_operator_attestation_envelope(restored)

    def test_empty_immutable_registry_blocks_signing_before_a_private_key_is_used(self) -> None:
        with patch(
            "scripts.staging_infrastructure_operator_signature.TRUSTED_OPERATOR_KEY_REGISTRY",
            MappingProxyType({}),
        ):
            with self.assertRaises(OperatorSignatureError):
                sign_operator_attestation(
                    {"synthetic": True},
                    key_id="unconfigured-operator",
                    private_key=Path("/not-used-because-registry-is-empty.pem"),
                )

    def test_empty_registry_prevents_operator_reads_before_promotion(self) -> None:
        calls: list[str] = []
        with patch(
            "scripts.staging_infrastructure_operator_signature.TRUSTED_OPERATOR_KEY_REGISTRY",
            MappingProxyType({}),
        ):
            with self.assertRaises(ApplyReadyError):
                build_operator_apply_ready_package(
                    {},
                    b"{}",
                    project_id=PROJECT,
                    provider_resource_name=PROVIDER,
                    service_account=SERVICE_ACCOUNT,
                    operator_signing_key_id="unconfigured-operator",
                    operator_signing_private_key=Path("/not-used-because-registry-is-empty.pem"),
                    environment_attestor=lambda **_: calls.append("environment"),  # type: ignore[return-value]
                    wif_attestor=lambda **_: calls.append("wif"),  # type: ignore[return-value]
                )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
