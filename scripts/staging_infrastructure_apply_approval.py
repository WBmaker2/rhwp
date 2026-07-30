"""Strict, exact-byte approval binding for the guarded apply executor."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.staging_infrastructure_validation import StrictJsonError, canonical_json_bytes, validate_json_domain
from scripts.staging_infrastructure_apply_review_policy import protected_environment_spec, wif_and_iam_diff
from scripts.staging_infrastructure_apply_safety import ApplySafetyError, reject_sensitive_string_leaves
from scripts.staging_infrastructure_operator_attestation import (
    OperatorAttestationError,
    parse_attestation_time,
    validate_environment_attestation,
    validate_wif_attestation,
)
from scripts.staging_infrastructure_operator_signature import (
    OperatorSignatureError,
    signed_attestation_sha256,
    verify_operator_attestation_envelope,
)

SCHEMA = "rhwp.staging-infrastructure-mutation-approval/v3"
REVIEW_SCHEMA = "rhwp.staging-infrastructure-apply-review/v2"
APPLY_READY_SCHEMA = "rhwp.staging-infrastructure-apply-ready/v3"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{24,128}$")
RUN_ID = re.compile(r"^[1-9][0-9]{0,19}$")
APPROVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ACTION_ID = re.compile(r"^[a-z][A-Za-z0-9.-]{1,127}$")
API_NAME = re.compile(r"^[a-z][a-z0-9-]{1,61}\.googleapis\.com$")
SERVICE_ACCOUNT = re.compile(r"^[a-z][a-z0-9-]{5,28}[a-z0-9]@")
RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
LOCATION = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SECRET_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,254}$")
STAGES = ("api-baseline", "service-accounts", "artifact-registry", "secret-metadata")
KINDS = {"api-baseline": "ensure-api-enabled", "service-accounts": "ensure-service-account", "artifact-registry": "ensure-artifact-repository", "secret-metadata": "ensure-secret-container"}
REVIEW_PACKAGE_KEYS = frozenset({"schemaVersion", "status", "projectId", "executorCommit", "sourceEvidence", "mutationArchitecture", "evidenceTransport", "canonicalMutationSubset", "executorActionAllowlistEnforcement", "protectedEnvironmentSpec", "wifIdentityAndIamDiff", "requiredApprovalRecordSchema", "requiredApprovals", "cloudMutationApproved", "deploymentApproved", "mutationCommands"})
APPLY_READY_KEYS = frozenset({"schemaVersion", "status", "reviewPackageSha256", "reviewPackage", "environmentAttestation", "environmentAttestationSha256", "wifAttestation", "wifAttestationSha256", "requiredApprovalRecordSchema", "cloudMutationApproved", "deploymentApproved", "mutationCommands"})
APPROVAL_KEYS = frozenset({"schemaVersion", "decision", "approvedAt", "approvedBy", "expiresAt", "approvalNonce", "approvedRunId", "approvedRunAttempt", "applyReadyPackageSha256", "environmentAttestationSha256", "wifAttestationSha256", "planSha256", "planObjectSha256", "executorCommitSha", "projectId", "approvedStageIds", "approvedActionIds", "environmentSpecReviewed", "wifIdentityReviewed", "leastPrivilegeIamDiffReviewed", "rollbackReviewed", "cloudMutationApproved", "deploymentApproved"})
FORBIDDEN = ("command", "argv", "shell", "authorization", "token", "password", "privatekey", "apikey", "secret", "credential", "idtoken")
MUTATION_ARCHITECTURE = {"authenticationBeforeValidationAllowed": False, "exactEvidenceBindingRequired": True, "firstFailureStopsExecution": True, "automaticDeleteRollbackAllowed": False, "futureExecutorImplemented": True}
EVIDENCE_TRANSPORT = {"artifactName": "staging-infrastructure-approved-evidence", "actualEvidenceTrackedInGit": False, "exactByteDigestRequired": True, "sameProtectedRunPublicationImplemented": True, "publicationBeforeCloudAuthentication": True, "operatorReceiptSignatureRequired": True, "operatorSigningKeyRegistry": "immutable-tracked-code", "containsCredentials": False, "containsSecretValues": False}
REQUIRED_APPROVALS = ["actual-review-package", "actual-environment-settings", "actual-wif-identity", "actual-live-iam-before-after-diff", "operator-attestation-signing-key", "cloud-mutation-approval-record", "apply-workflow-diff", "apply-workflow-dispatch"]


class MutationApprovalError(RuntimeError): pass


def validate_mutation_approval(package: dict[str, Any], package_bytes: bytes, approval: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    try:
        validate_json_domain(package); validate_json_domain(approval)
        reject_sensitive_string_leaves(package, "apply-ready package")
        reject_sensitive_string_leaves(approval, "approval")
    except (StrictJsonError, ApplySafetyError) as error: raise MutationApprovalError("approval inputs contain invalid or credential-shaped data") from error
    if not isinstance(package_bytes, bytes) or len(package_bytes) > 1_000_000: raise MutationApprovalError("review package bytes are invalid")
    current = now or datetime.now(timezone.utc)
    review = validate_apply_ready_package(package, now=current)
    if set(approval) != APPROVAL_KEYS: raise MutationApprovalError("approval record keys must exactly match v3 schema")
    _reject_forbidden(approval, "approval")
    if approval["schemaVersion"] != SCHEMA or approval["decision"] != "approved": raise MutationApprovalError("approval record is not an approved v3 record")
    for key in ("applyReadyPackageSha256", "environmentAttestationSha256", "wifAttestationSha256", "planSha256", "planObjectSha256"):_digest(approval[key], key)
    if approval["applyReadyPackageSha256"] != hashlib.sha256(package_bytes).hexdigest(): raise MutationApprovalError("apply-ready package exact-byte digest does not match approval")
    if approval["environmentAttestationSha256"] != package["environmentAttestationSha256"] or approval["wifAttestationSha256"] != package["wifAttestationSha256"]: raise MutationApprovalError("approval does not bind live readiness attestations")
    source = review["sourceEvidence"]
    if approval["planSha256"] != source["planSha256"] or approval["planObjectSha256"] != source["planObjectSha256"]: raise MutationApprovalError("plan digests do not match package")
    approved_at, _ = _approvers_and_expiry(approval, current)
    _validate_attestation_approval_window(package, approved_at, current)
    if not isinstance(approval["approvalNonce"], str) or not NONCE.fullmatch(approval["approvalNonce"]): raise MutationApprovalError("approval nonce is invalid")
    if not isinstance(approval["approvedRunId"], str) or not RUN_ID.fullmatch(approval["approvedRunId"]): raise MutationApprovalError("approved run identity is invalid")
    if isinstance(approval["approvedRunAttempt"], bool) or not isinstance(approval["approvedRunAttempt"], int) or approval["approvedRunAttempt"] <= 0: raise MutationApprovalError("approved run attempt is invalid")
    if approval["executorCommitSha"] != review["executorCommit"]["sha"] or not isinstance(approval["executorCommitSha"], str) or not COMMIT.fullmatch(approval["executorCommitSha"]): raise MutationApprovalError("executor commit does not match package")
    if approval["projectId"] != review["projectId"] or _production_like(approval["projectId"]): raise MutationApprovalError("approval project is not staging-only")
    stages, ids = _actions(review)
    if approval["approvedStageIds"] != stages or approval["approvedActionIds"] != ids: raise MutationApprovalError("approved stages/actions must be complete, ordered, and exactly once")
    for key in ("environmentSpecReviewed", "wifIdentityReviewed", "leastPrivilegeIamDiffReviewed", "rollbackReviewed", "cloudMutationApproved"):
        if approval[key] is not True: raise MutationApprovalError(f"approval {key} must be true")
    if approval["deploymentApproved"] is not False: raise MutationApprovalError("infrastructure approval cannot authorize deployment")
    return {key: approval[key] for key in ("schemaVersion", "applyReadyPackageSha256", "environmentAttestationSha256", "wifAttestationSha256", "planSha256", "planObjectSha256", "executorCommitSha", "projectId", "approvedStageIds", "approvedActionIds", "approvedRunId", "approvedRunAttempt", "approvalNonce", "expiresAt", "cloudMutationApproved", "deploymentApproved")}


def _validate_review_package(p: dict[str, Any]) -> None:
    if set(p) != REVIEW_PACKAGE_KEYS or p.get("schemaVersion") != REVIEW_SCHEMA or p.get("status") != "ready-for-apply-review": raise MutationApprovalError("review package is old or has an unsupported top-level schema; regenerate and promote it")
    try: reject_sensitive_string_leaves(p, "review package")
    except ApplySafetyError as error: raise MutationApprovalError("review package contains a credential-shaped value") from error
    _reject_forbidden(p, "review package")
    if p.get("cloudMutationApproved") is not False or p.get("deploymentApproved") is not False or p.get("mutationCommands") != []: raise MutationApprovalError("review package cannot carry execution authority")
    if p.get("mutationArchitecture") != MUTATION_ARCHITECTURE:
        raise MutationApprovalError("mutation architecture does not match the v2 guarded executor contract")
    if p.get("evidenceTransport") != EVIDENCE_TRANSPORT:
        raise MutationApprovalError("evidence transport does not match same-run protected publication contract")
    source, executor = p.get("sourceEvidence"), p.get("executorCommit")
    if not isinstance(source, dict) or set(source) != {"planSha256", "planObjectSha256", "actionSetSha256", "sourceCommitSha", "approvalResultSchema", "canonicalActionSetSha256"}: raise MutationApprovalError("package source provenance schema is invalid")
    for key in ("planSha256", "planObjectSha256", "actionSetSha256", "canonicalActionSetSha256"): _digest(source.get(key), key)
    if source["approvalResultSchema"] != "rhwp.staging-infrastructure-approval-result/v1": raise MutationApprovalError("package approval result schema is invalid")
    if not isinstance(source["sourceCommitSha"], str) or not COMMIT.fullmatch(source["sourceCommitSha"]): raise MutationApprovalError("package source commit is invalid")
    expected_executor = {
        "sha": executor.get("sha") if isinstance(executor, dict) else None,
        "provenance": "caller-declared-unverified",
        "immutableVerifiedProvenance": False,
        "independentVerificationRequired": ["verify-commit-membership-in-approved-branch", "verify-commit-object-and-tree", "verify-approved-apply-workflow-path-and-content"],
    }
    if executor != expected_executor or not isinstance(expected_executor["sha"], str) or not COMMIT.fullmatch(expected_executor["sha"]): raise MutationApprovalError("package executor declaration is invalid")
    if _production_like(p.get("projectId")):
        raise MutationApprovalError("package project is not staging-only")
    stages, _ = _actions(p)
    for action in p["canonicalMutationSubset"]:
        if action["resourceKind"] == "ensure-service-account" and not action["resourceIdentifier"]["identity"].endswith(f"@{p['projectId']}.iam.gserviceaccount.com"):
            raise MutationApprovalError("service account does not bind to package project")
    digest = hashlib.sha256(canonical_json_bytes(p["canonicalMutationSubset"]).rstrip(b"\n")).hexdigest()
    if source["canonicalActionSetSha256"] != digest or stages != list(STAGES): raise MutationApprovalError("canonical action subset digest is invalid")
    _validate_executor_contract(p)


def validate_apply_ready_package(p: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Accept only a promoted, live-attested package; review evidence alone is inert."""
    try:
        validate_json_domain(p)
        reject_sensitive_string_leaves(p, "apply-ready package")
    except (StrictJsonError, ApplySafetyError) as error:
        raise MutationApprovalError("apply-ready package contains invalid or credential-shaped data") from error
    if set(p) != APPLY_READY_KEYS or p.get("schemaVersion") != APPLY_READY_SCHEMA or p.get("status") != "ready-for-approved-apply":
        raise MutationApprovalError("review package is not an apply-ready promotion")
    if p.get("cloudMutationApproved") is not False or p.get("deploymentApproved") is not False or p.get("mutationCommands") != [] or p.get("requiredApprovalRecordSchema") != SCHEMA:
        raise MutationApprovalError("apply-ready package has unsafe authority fields")
    review = p.get("reviewPackage")
    if not isinstance(review, dict): raise MutationApprovalError("apply-ready review package is invalid")
    _validate_review_package(review)
    for key in ("reviewPackageSha256", "environmentAttestationSha256", "wifAttestationSha256"):
        _digest(p.get(key), key)
    environment, wif = p.get("environmentAttestation"), p.get("wifAttestation")
    if not isinstance(environment, dict) or not isinstance(wif, dict): raise MutationApprovalError("apply-ready attestations are invalid")
    if signed_attestation_sha256(environment) != p["environmentAttestationSha256"]:
        raise MutationApprovalError("environment attestation digest is invalid")
    if signed_attestation_sha256(wif) != p["wifAttestationSha256"]:
        raise MutationApprovalError("WIF attestation digest is invalid")
    try:
        environment_payload = verify_operator_attestation_envelope(environment)
        wif_payload = verify_operator_attestation_envelope(wif)
        validate_environment_attestation(environment_payload, now=now)
        validate_wif_attestation(
            wif_payload,
            project_id=review["projectId"],
            workflow_sha=review["executorCommit"]["sha"],
            now=now,
        )
    except (OperatorAttestationError, OperatorSignatureError) as error:
        raise MutationApprovalError("operator attestation is invalid or expired") from error
    if wif_payload["workflowSha"] != review["executorCommit"]["sha"] or wif_payload["repositoryId"] != environment_payload["repositoryId"] or wif_payload["repositoryOwnerId"] != environment_payload["repositoryOwnerId"]:
        raise MutationApprovalError("apply-ready immutable identities do not bind review executor")
    return review


def _validate_executor_contract(p: dict[str, Any]) -> None:
    subset = p["canonicalMutationSubset"]
    expected_allowlist = {
        "implemented": True,
        "iamScopeAloneSufficient": False,
        "independentExecutorEnforcementRequired": True,
        "liveProjectScopeBindingDiffRequired": True,
        "approvedActions": [
            {"actionId": item["actionId"], "resourceIdentifier": item["resourceIdentifier"], "preconditionEvidence": item["preconditionEvidence"]}
            for item in subset
        ],
    }
    if p.get("executorActionAllowlistEnforcement") != expected_allowlist:
        raise MutationApprovalError("executor action allowlist contract is invalid")
    if p.get("protectedEnvironmentSpec") != protected_environment_spec():
        raise MutationApprovalError("protected environment specification is not exact")
    if p.get("wifIdentityAndIamDiff") != wif_and_iam_diff():
        raise MutationApprovalError("WIF and IAM review diff is not exact")
    if p.get("requiredApprovalRecordSchema") != APPLY_READY_SCHEMA or p.get("requiredApprovals") != REQUIRED_APPROVALS:
        raise MutationApprovalError("review promotion contract is not exact")


def _actions(p: dict[str, Any]) -> tuple[list[str], list[str]]:
    values = p.get("canonicalMutationSubset")
    if not isinstance(values, list) or not values: raise MutationApprovalError("canonical action subset is missing")
    stages, ids, position = [], [], -1
    required = {"actionId", "stageId", "resourceKind", "resourceIdentifier", "desiredState", "preconditionEvidence", "rollbackDisposition"}
    for item in values:
        if not isinstance(item, dict) or set(item) != required: raise MutationApprovalError("canonical action nested schema is invalid")
        stage, kind, action_id = item["stageId"], item["resourceKind"], item["actionId"]
        if stage not in STAGES or kind != KINDS[stage] or not isinstance(action_id, str) or not ACTION_ID.fullmatch(action_id) or action_id in ids: raise MutationApprovalError("canonical action kind or ID is unsafe")
        index = STAGES.index(stage)
        if index < position or (stage in stages and index != position): raise MutationApprovalError("canonical action order is invalid")
        position = index
        if stage not in stages: stages.append(stage)
        _semantic_action(item); ids.append(action_id)
    return stages, ids


def _semantic_action(item: dict[str, Any]) -> None:
    r, d, e, rollback, kind = item["resourceIdentifier"], item["desiredState"], item["preconditionEvidence"], item["rollbackDisposition"], item["resourceKind"]
    if not isinstance(r, dict) or not isinstance(d, dict) or not isinstance(e, dict) or not isinstance(rollback, str) or not rollback: raise MutationApprovalError("canonical action semantics are invalid")
    contracts = {
        "ensure-api-enabled": ({"api"}, {"enabled": True, "operation": "enable-only"}, lambda x: set(x) == {"type", "api"} and x["type"] == "enabled-service-list"),
        "ensure-service-account": ({"identity", "workload"}, {"exists": True, "operation": "create-if-missing", "keysAllowed": False}, lambda x: set(x) == {"type", "identity"} and x["type"] == "service-account"),
        "ensure-artifact-repository": ({"repository", "location", "format"}, {"exists": True, "operation": "create-if-missing", "deletionAllowed": False, "format": "DOCKER"}, lambda x: set(x) == {"type", "fields"} and x["type"] == "artifact-repository"),
        "ensure-secret-container": ({"name", "replication", "valueIncluded"}, {"exists": True, "operation": "create-if-missing", "versionsAllowed": False, "replication": "automatic"}, lambda x: set(x) == {"type", "name", "replication"} and x["type"] == "secret-container"),
    }
    keys, desired, check = contracts[kind]
    if set(r) != keys or d != desired or not check(e): raise MutationApprovalError("canonical action nested semantics do not match the builder contract")
    if kind == "ensure-api-enabled" and e["api"] != r["api"]: raise MutationApprovalError("API evidence does not match identifier")
    if kind == "ensure-api-enabled" and (not isinstance(r["api"], str) or not API_NAME.fullmatch(r["api"])): raise MutationApprovalError("API identifier is invalid")
    if kind == "ensure-service-account" and (not isinstance(r["identity"], str) or not isinstance(r["workload"], str) or not SERVICE_ACCOUNT.match(r["identity"]) or e["identity"] != r["identity"]): raise MutationApprovalError("service account evidence does not match identifier")
    if kind == "ensure-artifact-repository" and (not isinstance(r["repository"], str) or not RESOURCE_NAME.fullmatch(r["repository"]) or not isinstance(r["location"], str) or not LOCATION.fullmatch(r["location"]) or r["format"] != "DOCKER" or e["fields"] != ["repository", "location", "format"]): raise MutationApprovalError("artifact evidence semantics are invalid")
    if kind == "ensure-secret-container" and (not isinstance(r["name"], str) or not SECRET_NAME.fullmatch(r["name"]) or r["valueIncluded"] is not False or r["replication"] != "automatic" or e["name"] != r["name"] or e["replication"] != "automatic"): raise MutationApprovalError("secret metadata semantics are invalid")


def _approvers_and_expiry(a: dict[str, Any], now: datetime) -> tuple[datetime, datetime]:
    for field in ("approvedAt", "expiresAt"):
        if not isinstance(a[field], str) or not UTC.fullmatch(a[field]): raise MutationApprovalError("approval time is invalid")
    try: approved, expires = (datetime.strptime(a[x], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for x in ("approvedAt", "expiresAt"))
    except ValueError as error: raise MutationApprovalError("approval time is invalid") from error
    current = now
    if approved > current: raise MutationApprovalError("approval time cannot be in the future")
    if expires <= approved or expires <= current: raise MutationApprovalError("approval has expired")
    if expires - approved > timedelta(days=31): raise MutationApprovalError("approval validity exceeds the maximum window")
    if not isinstance(a["approvedBy"], list) or not a["approvedBy"] or any(not isinstance(x, str) or not APPROVER.fullmatch(x) for x in a["approvedBy"]): raise MutationApprovalError("human approver is required")
    return approved, expires


def _validate_attestation_approval_window(
    package: dict[str, Any], approved_at: datetime, current: datetime
) -> None:
    """Require both operator observations to cover approval and current apply time."""
    for key in ("environmentAttestation", "wifAttestation"):
        value = package.get(key)
        if not isinstance(value, dict):
            raise MutationApprovalError("operator attestation is missing")
        try:
            payload = verify_operator_attestation_envelope(value)
            observed = parse_attestation_time(payload.get("observedAt"), "observed")
            expires = parse_attestation_time(payload.get("expiresAt"), "expiry")
        except (OperatorAttestationError, OperatorSignatureError) as error:
            raise MutationApprovalError("operator attestation time is invalid") from error
        if not (observed <= approved_at < expires and observed <= current < expires):
            raise MutationApprovalError("operator attestation does not cover approval and apply time")


def _digest(v: Any, label: str) -> None:
    if not isinstance(v, str) or not SHA256.fullmatch(v): raise MutationApprovalError(f"{label} must be SHA-256")
def _production_like(v: Any) -> bool:
    return not isinstance(v, str) or "staging" not in v.lower() or "production" in v.lower() or re.search(r"(^|-)prod($|-)", v.lower()) is not None
def _numeric_id(v: Any) -> bool:
    return isinstance(v, str) and RUN_ID.fullmatch(v) is not None
def _reject_forbidden(v: Any, label: str, path: tuple[str, ...] = ()) -> None:
    if isinstance(v, dict):
        for key, item in v.items():
            normal = key.lower().replace("_", "").replace("-", "")
            current = (*path, key)
            if any(marker in normal for marker in FORBIDDEN) and not _allowed_sensitive_key(label, current, item):
                raise MutationApprovalError(f"{label} contains a forbidden key")
            _reject_forbidden(item, label, current)
    elif isinstance(v, list):
        for item in v: _reject_forbidden(item, label, path)


def _allowed_sensitive_key(label: str, path: tuple[str, ...], value: Any) -> bool:
    """Allow only schema-checked inert keys at their one sanctioned path."""
    return (label == "review package" and path == ("mutationCommands",) and value == []) or (
        label == "review package" and path == ("protectedEnvironmentSpec", "secrets") and value == []
    ) or (
        label == "review package" and path in {
            ("protectedEnvironmentSpec", "currentReviewJobPermissions", "id-token"),
            ("protectedEnvironmentSpec", "futureApplyJobPermissions", "id-token"),
        } and value in {"none", "write"}
    ) or (
        label == "review package" and path == ("protectedEnvironmentSpec", "longLivedCloudCredentials") and value == []
    ) or (
        label == "review package" and path in {
            ("evidenceTransport", "containsCredentials"),
            ("evidenceTransport", "containsSecretValues"),
        } and value is False
    )
