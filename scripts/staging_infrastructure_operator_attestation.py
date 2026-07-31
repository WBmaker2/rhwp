"""Shared exact-schema rules for short-lived operator-read attestations.

The callers that perform the queries live in the Environment and WIF modules.
This module deliberately stores only digests of their raw responses, never a
response body, token, credential, or reviewer identity.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.staging_infrastructure_apply_review_policy import (
    APPLY_BRANCH,
    APPLY_WORKFLOW_REF,
    GITHUB_OIDC_ISSUER,
    REPOSITORY,
    protected_environment_spec,
    wif_attribute_mapping,
    wif_expected_condition,
    wif_expected_principal,
)
from scripts.staging_infrastructure_validation import (
    StrictJsonError,
    canonical_json_bytes,
    validate_json_domain,
)

ENVIRONMENT_ATTESTATION_SCHEMA = "rhwp.staging-infrastructure-environment-attestation/v3"
WIF_ATTESTATION_SCHEMA = "rhwp.staging-infrastructure-wif-attestation/v2"
ENVIRONMENT_QUERY_CONTRACT = "rhwp.staging-infrastructure-environment-read-query/v2"
WIF_QUERY_CONTRACT = "rhwp.staging-infrastructure-wif-read-query/v1"
ATTESTATION_ENCODING = "canonical-json-indent-2/v1"
MAX_ATTESTATION_TTL = timedelta(minutes=15)
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NUMERIC_ID = re.compile(r"^[1-9][0-9]{0,19}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
PROVIDER = re.compile(
    r"^projects/[1-9][0-9]{0,19}/locations/global/"
    r"workloadIdentityPools/[a-z0-9-]{4,63}/providers/[a-z0-9-]{4,63}$"
)
SERVICE_ACCOUNT = re.compile(
    r"^[a-z][a-z0-9-]{5,28}[a-z0-9]@"
    r"[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$"
)


class OperatorAttestationError(RuntimeError):
    pass


_ISSUER_CAPABILITY = object()


@dataclass(frozen=True)
class IssuedOperatorAttestation:
    """In-process receipt emitted only after a fixed-query verifier succeeds."""

    document: dict[str, Any]
    exact_bytes: bytes
    sha256: str
    _issuer: object


def _issue_fixed_query_attestation(value: dict[str, Any]) -> IssuedOperatorAttestation:
    """Seal canonical bytes after a query module has already verified the result."""
    copied = deepcopy(value)
    raw = canonical_attestation_bytes(copied)
    return IssuedOperatorAttestation(
        document=copied,
        exact_bytes=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        _issuer=_ISSUER_CAPABILITY,
    )


def issued_attestation_document(value: Any) -> dict[str, Any]:
    """Reject caller dictionaries and changed receipts at the promotion boundary."""
    if not isinstance(value, IssuedOperatorAttestation) or value._issuer is not _ISSUER_CAPABILITY:
        raise OperatorAttestationError("operator attestation receipt is not issued by a fixed-query verifier")
    raw = canonical_attestation_bytes(value.document)
    if raw != value.exact_bytes or hashlib.sha256(raw).hexdigest() != value.sha256:
        raise OperatorAttestationError("operator attestation receipt bytes changed after verification")
    return deepcopy(value.document)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_attestation_bytes(value: dict[str, Any]) -> bytes:
    validate_json_domain(value)
    return canonical_json_bytes(value, indent=2)


def attestation_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_attestation_bytes(value)).hexdigest()


def response_sha256(raw: bytes) -> str:
    if not isinstance(raw, bytes) or len(raw) > 1_000_000:
        raise OperatorAttestationError("read-only response is invalid")
    return hashlib.sha256(raw).hexdigest()


def environment_required_contract() -> dict[str, Any]:
    spec = protected_environment_spec()
    return {
        "requiredReviewerCountMinimum": spec["requiredReviewerCountMinimum"],
        "preventSelfReview": spec["preventSelfReview"],
        "canAdminsBypass": spec["canAdminsBypass"],
        "adminBypassUiConfigurationRequired": spec["adminBypassUiConfigurationRequired"],
        "adminBypassRestObservationException": spec["adminBypassRestObservationException"],
        "deploymentBranchPolicy": spec["deploymentBranchPolicy"],
        "variableNames": sorted(spec["variableNames"]),
    }


def validate_environment_attestation(
    value: dict[str, Any], *, now: datetime | None = None
) -> None:
    required = {
        "schemaVersion", "queryContractVersion", "status", "verified",
        "encoding", "environmentName", "repository", "repositoryId",
        "repositoryOwnerId", "environmentId", "requiredContract", "observed",
        "responseDigests", "observedAt", "expiresAt",
    }
    try:
        validate_json_domain(value)
    except StrictJsonError as error:
        raise OperatorAttestationError("Environment attestation JSON is invalid") from error
    if set(value) != required:
        raise OperatorAttestationError("Environment attestation schema is invalid")
    if (
        value.get("schemaVersion") != ENVIRONMENT_ATTESTATION_SCHEMA
        or value.get("queryContractVersion") != ENVIRONMENT_QUERY_CONTRACT
        or value.get("status") != "verified"
        or value.get("verified") is not True
        or value.get("encoding") != ATTESTATION_ENCODING
        or value.get("environmentName") != protected_environment_spec()["name"]
        or value.get("repository") != REPOSITORY
    ):
        raise OperatorAttestationError("Environment attestation is not verified")
    if not all(NUMERIC_ID.fullmatch(value.get(key, "")) for key in ("repositoryId", "repositoryOwnerId", "environmentId")):
        raise OperatorAttestationError("Environment immutable identity is invalid")
    if value.get("requiredContract") != environment_required_contract():
        raise OperatorAttestationError("Environment required contract is not exact")
    expected_observed = {
        "requiredReviewerCount": value.get("observed", {}).get("requiredReviewerCount") if isinstance(value.get("observed"), dict) else None,
        "preventSelfReview": False,
        "canAdminsBypass": value.get("observed", {}).get("canAdminsBypass") if isinstance(value.get("observed"), dict) else None,
        "deploymentBranchPolicy": environment_required_contract()["deploymentBranchPolicy"],
        "variableNames": environment_required_contract()["variableNames"],
    }
    observed = value.get("observed")
    if (
        not isinstance(observed, dict)
        or set(observed) != set(expected_observed)
        or observed != expected_observed
        or isinstance(observed["requiredReviewerCount"], bool)
        or not isinstance(observed["requiredReviewerCount"], int)
        or observed["requiredReviewerCount"] < 1
        or not (
            observed["canAdminsBypass"] is False
            or observed["canAdminsBypass"] == "unavailable-in-official-rest"
        )
    ):
        raise OperatorAttestationError("Environment observed policy is not apply-ready")
    _validate_response_digests(value.get("responseDigests"), {"repository", "environment", "branchPolicyPages", "variablePages"})
    _validate_freshness(value, now=now)


def validate_wif_attestation(
    value: dict[str, Any], *, project_id: str | None = None,
    workflow_sha: str | None = None, now: datetime | None = None,
) -> None:
    required = {
        "schemaVersion", "queryContractVersion", "status", "verified",
        "encoding", "projectId", "providerResourceName", "serviceAccount",
        "repositoryId", "repositoryOwnerId", "ref", "workflowRef", "workflowSha",
        "expected", "observed", "observedResourceProvenance", "responseDigests",
        "observedAt", "expiresAt",
    }
    try:
        validate_json_domain(value)
    except StrictJsonError as error:
        raise OperatorAttestationError("WIF attestation JSON is invalid") from error
    if set(value) != required:
        raise OperatorAttestationError("WIF attestation schema is invalid")
    if (
        value.get("schemaVersion") != WIF_ATTESTATION_SCHEMA
        or value.get("queryContractVersion") != WIF_QUERY_CONTRACT
        or value.get("status") != "verified"
        or value.get("verified") is not True
        or value.get("encoding") != ATTESTATION_ENCODING
        or not isinstance(value.get("projectId"), str)
        or not PROJECT.fullmatch(value["projectId"])
        or "staging" not in value["projectId"]
        or "prod" in value["projectId"]
        or not isinstance(value.get("providerResourceName"), str)
        or not PROVIDER.fullmatch(value["providerResourceName"])
        or not isinstance(value.get("serviceAccount"), str)
        or not SERVICE_ACCOUNT.fullmatch(value["serviceAccount"])
        or not value["serviceAccount"].endswith(f"@{value['projectId']}.iam.gserviceaccount.com")
    ):
        raise OperatorAttestationError("WIF provider or service account identity is invalid")
    if project_id is not None and value["projectId"] != project_id:
        raise OperatorAttestationError("WIF project differs from reviewed project")
    if not all(NUMERIC_ID.fullmatch(value.get(key, "")) for key in ("repositoryId", "repositoryOwnerId")):
        raise OperatorAttestationError("WIF immutable repository identifiers are invalid")
    if (
        value.get("ref") != APPLY_BRANCH
        or value.get("workflowRef") != APPLY_WORKFLOW_REF
        or not isinstance(value.get("workflowSha"), str)
        or not COMMIT.fullmatch(value["workflowSha"])
        or workflow_sha is not None and value["workflowSha"] != workflow_sha
    ):
        raise OperatorAttestationError("WIF immutable workflow claims are invalid")
    expected = {
        "attributeMapping": wif_attribute_mapping(),
        "attributeCondition": wif_expected_condition(
            value["repositoryId"], value["repositoryOwnerId"], value["workflowSha"]
        ),
        "workloadIdentityUserPrincipal": wif_expected_principal(
            value["providerResourceName"], value["repositoryId"]
        ),
        "workloadIdentityUserRole": "roles/iam.workloadIdentityUser",
        "oidcIssuerUri": GITHUB_OIDC_ISSUER,
        "allowedAudienceMode": "default-provider-resource",
    }
    if value.get("expected") != expected:
        raise OperatorAttestationError("WIF expected mapping, condition, or principal is not exact")
    observed = {
        "providerResourceName": value["providerResourceName"],
        "providerState": "ACTIVE",
        "providerDisabled": False,
        "attributeMappingMatches": True,
        "attributeConditionMatches": True,
        "workloadIdentityUserBindingMatches": True,
        "oidcIssuerMatches": True,
        "allowedAudienceMode": "default-provider-resource",
    }
    if value.get("observed") != observed:
        raise OperatorAttestationError("WIF observed resource does not match the exact contract")
    provenance = {
        "providerResourceName": value["providerResourceName"],
        "serviceAccount": value["serviceAccount"],
    }
    if value.get("observedResourceProvenance") != provenance:
        raise OperatorAttestationError("WIF observed resource provenance is invalid")
    _validate_response_digests(value.get("responseDigests"), {"provider", "serviceAccountIamPolicy"})
    _validate_freshness(value, now=now)


def validate_attested_runtime_context(
    environment: dict[str, Any], wif: dict[str, Any], claims: dict[str, Any], *,
    project_id: str, workflow_sha: str, now: datetime | None = None,
) -> None:
    """Require current Action claims to match both short-lived attestations."""
    validate_environment_attestation(environment, now=now)
    validate_wif_attestation(wif, project_id=project_id, workflow_sha=workflow_sha, now=now)
    if (
        claims.get("repository") != environment["repository"]
        or claims.get("repositoryId") != environment["repositoryId"]
        or claims.get("repositoryOwnerId") != environment["repositoryOwnerId"]
        or claims.get("repositoryId") != wif["repositoryId"]
        or claims.get("repositoryOwnerId") != wif["repositoryOwnerId"]
        or claims.get("ref") != wif["ref"]
        or claims.get("workflowRef") != wif["workflowRef"]
        or claims.get("workflowSha") != wif["workflowSha"]
    ):
        raise OperatorAttestationError("actual GitHub context differs from attested Environment or WIF")


def write_new_attestation(path: Path, value: dict[str, Any]) -> None:
    """Publish a canonical attestation only to a new regular, non-symlink file."""
    write_new_canonical_json(path, value)


def write_new_canonical_json(path: Path, value: dict[str, Any]) -> None:
    """Publish a canonical non-secret evidence object to a new safe file."""
    if path.exists() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise OperatorAttestationError("attestation output must be a new non-symlink file")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_attestation_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink() or temporary.is_symlink():
            raise OperatorAttestationError("attestation output changed during publication")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise OperatorAttestationError("could not publish attestation") from error


def _validate_response_digests(value: Any, required: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != required:
        raise OperatorAttestationError("attestation response digest schema is invalid")
    for key, digest in value.items():
        if key.endswith("Pages"):
            if not isinstance(digest, list) or not digest or any(
                not isinstance(item, str) or not SHA256.fullmatch(item) for item in digest
            ):
                raise OperatorAttestationError("attestation page digest is invalid")
        elif not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise OperatorAttestationError("attestation response digest is invalid")


def _validate_freshness(value: dict[str, Any], *, now: datetime | None) -> None:
    observed = _parse_utc(value.get("observedAt"), "observed")
    expires = _parse_utc(value.get("expiresAt"), "expiry")
    current = now or utc_now()
    if expires <= observed or expires - observed > MAX_ATTESTATION_TTL:
        raise OperatorAttestationError("attestation validity window is invalid")
    if observed > current or expires <= current:
        raise OperatorAttestationError("attestation is not currently valid")


def parse_attestation_time(value: Any, label: str) -> datetime:
    return _parse_utc(value, label)


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise OperatorAttestationError(f"attestation {label} time is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise OperatorAttestationError(f"attestation {label} time is invalid") from error
