#!/usr/bin/env python3
"""Create a sanitized WIF/IAM attestation from fixed read-only gcloud queries."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.staging_infrastructure_apply_review_policy import (
    APPLY_BRANCH,
    APPLY_WORKFLOW_REF,
    GITHUB_OIDC_ISSUER,
    wif_attribute_mapping,
    wif_expected_condition,
    wif_expected_principal,
)
from scripts.staging_infrastructure_operator_attestation import (
    ATTESTATION_ENCODING,
    COMMIT,
    MAX_ATTESTATION_TTL,
    NUMERIC_ID,
    PROJECT,
    PROVIDER,
    SERVICE_ACCOUNT,
    IssuedOperatorAttestation,
    WIF_ATTESTATION_SCHEMA,
    WIF_QUERY_CONTRACT,
    OperatorAttestationError,
    response_sha256,
    _issue_fixed_query_attestation,
    utc_now,
    utc_text,
    validate_wif_attestation,
    write_new_attestation,
)
from scripts.staging_infrastructure_validation import StrictJsonError, parse_strict_json_bytes

Runner = Callable[[tuple[str, ...]], bytes]


class WifAttestationError(RuntimeError):
    pass


def attest_wif(
    *, project_id: str, provider_resource_name: str, service_account: str,
    repository_id: str, repository_owner_id: str, workflow_sha: str,
    runner: Runner | None = None, now: datetime | None = None,
) -> IssuedOperatorAttestation:
    """Read and verify the provider plus the deployer account IAM policy.

    The production path never accepts observed JSON. It calls exactly two fixed
    read-only gcloud commands with ``shell=False``; an injected runner exists
    solely for deterministic unit tests.
    """
    _validate_inputs(
        project_id, provider_resource_name, service_account,
        repository_id, repository_owner_id, workflow_sha,
    )
    run = runner or _run_fixed_gcloud
    try:
        provider_raw = run(_provider_argv(project_id, provider_resource_name))
        policy_raw = run(_policy_argv(project_id, service_account))
        provider = _json_object(provider_raw, "provider")
        policy = _json_object(policy_raw, "service-account IAM policy")
        expected_condition = wif_expected_condition(
            repository_id, repository_owner_id, workflow_sha
        )
        expected_principal = wif_expected_principal(
            provider_resource_name, repository_id
        )
        _verify_provider(provider, provider_resource_name, expected_condition)
        _verify_workload_identity_user_binding(policy, expected_principal)
        observed_at = now or utc_now()
        result = {
            "schemaVersion": WIF_ATTESTATION_SCHEMA,
            "queryContractVersion": WIF_QUERY_CONTRACT,
            "status": "verified",
            "verified": True,
            "encoding": ATTESTATION_ENCODING,
            "projectId": project_id,
            "providerResourceName": provider_resource_name,
            "serviceAccount": service_account,
            "repositoryId": repository_id,
            "repositoryOwnerId": repository_owner_id,
            "ref": APPLY_BRANCH,
            "workflowRef": APPLY_WORKFLOW_REF,
            "workflowSha": workflow_sha,
            "expected": {
                "attributeMapping": wif_attribute_mapping(),
                "attributeCondition": expected_condition,
                "workloadIdentityUserPrincipal": expected_principal,
                "workloadIdentityUserRole": "roles/iam.workloadIdentityUser",
                "oidcIssuerUri": GITHUB_OIDC_ISSUER,
                "allowedAudienceMode": "default-provider-resource",
            },
            "observed": {
                "providerResourceName": provider_resource_name,
                "providerState": "ACTIVE",
                "providerDisabled": False,
                "attributeMappingMatches": True,
                "attributeConditionMatches": True,
                "workloadIdentityUserBindingMatches": True,
                "oidcIssuerMatches": True,
                "allowedAudienceMode": "default-provider-resource",
            },
            "observedResourceProvenance": {
                "providerResourceName": provider_resource_name,
                "serviceAccount": service_account,
            },
            "responseDigests": {
                "provider": response_sha256(provider_raw),
                "serviceAccountIamPolicy": response_sha256(policy_raw),
            },
            "observedAt": utc_text(observed_at),
            "expiresAt": utc_text(observed_at + MAX_ATTESTATION_TTL),
        }
        validate_wif_attestation(
            result, project_id=project_id, workflow_sha=workflow_sha,
            now=observed_at,
        )
        return _issue_fixed_query_attestation(result)
    except (WifAttestationError, OperatorAttestationError):
        raise
    except Exception as error:
        raise WifAttestationError("WIF read-only query failed") from error


def _validate_inputs(
    project_id: str, provider_resource_name: str, service_account: str,
    repository_id: str, repository_owner_id: str, workflow_sha: str,
) -> None:
    if (
        not PROJECT.fullmatch(project_id) or "staging" not in project_id
        or "prod" in project_id or not PROVIDER.fullmatch(provider_resource_name)
        or not SERVICE_ACCOUNT.fullmatch(service_account)
        or not service_account.endswith(f"@{project_id}.iam.gserviceaccount.com")
        or not NUMERIC_ID.fullmatch(repository_id)
        or not NUMERIC_ID.fullmatch(repository_owner_id)
        or not COMMIT.fullmatch(workflow_sha)
    ):
        raise WifAttestationError("WIF attestation identifiers are invalid")


def _provider_argv(project_id: str, provider_resource_name: str) -> tuple[str, ...]:
    return (
        "gcloud", "iam", "workload-identity-pools", "providers", "describe",
        provider_resource_name, f"--project={project_id}", "--format=json", "--quiet",
    )


def _policy_argv(project_id: str, service_account: str) -> tuple[str, ...]:
    return (
        "gcloud", "iam", "service-accounts", "get-iam-policy", service_account,
        f"--project={project_id}", "--format=json", "--quiet",
    )


def _run_fixed_gcloud(argv: tuple[str, ...]) -> bytes:
    completed = subprocess.run(
        list(argv), shell=False, check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise WifAttestationError("fixed GCP read-only command failed")
    return completed.stdout


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = parse_strict_json_bytes(raw, label)
    except StrictJsonError as error:
        raise WifAttestationError("GCP read-only response is not strict JSON") from error
    if not isinstance(value, dict):
        raise WifAttestationError("GCP read-only response must be an object")
    return value


def _verify_provider(
    provider: dict[str, Any], provider_resource_name: str, expected_condition: str
) -> None:
    if (
        provider.get("name") != provider_resource_name
        or provider.get("state") != "ACTIVE"
        or provider.get("disabled") is not False
        or provider.get("attributeMapping") != wif_attribute_mapping()
        or provider.get("attributeCondition") != expected_condition
        or not _is_exact_github_oidc_config(provider.get("oidc"))
    ):
        raise WifAttestationError("WIF provider mapping, condition, or identity is not exact")


def _is_exact_github_oidc_config(value: Any) -> bool:
    """Allow GitHub's issuer only with the provider's default audience mode."""
    if not isinstance(value, dict) or set(value) not in ({"issuerUri"}, {"issuerUri", "allowedAudiences"}):
        return False
    audiences = value.get("allowedAudiences", [])
    return value.get("issuerUri") == GITHUB_OIDC_ISSUER and audiences == []


def _verify_workload_identity_user_binding(policy: dict[str, Any], principal: str) -> None:
    bindings = policy.get("bindings")
    if not isinstance(bindings, list) or any(not isinstance(item, dict) for item in bindings):
        raise WifAttestationError("service-account IAM policy bindings are invalid")
    matching = [
        item for item in bindings
        if item.get("role") == "roles/iam.workloadIdentityUser"
    ]
    if matching != [{"role": "roles/iam.workloadIdentityUser", "members": [principal]}]:
        raise WifAttestationError("service-account workloadIdentityUser binding is not exact")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attest WIF provider and deployer IAM with read-only gcloud")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--provider-resource-name", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--repository-owner-id", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = attest_wif(
            project_id=args.project_id,
            provider_resource_name=args.provider_resource_name,
            service_account=args.service_account,
            repository_id=args.repository_id,
            repository_owner_id=args.repository_owner_id,
            workflow_sha=args.workflow_sha,
        )
        write_new_attestation(args.output, result.document)
    except (WifAttestationError, OperatorAttestationError, OSError) as error:
        print(f"staging WIF attestation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "verified", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
