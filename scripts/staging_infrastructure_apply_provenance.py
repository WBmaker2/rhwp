"""Fail-closed, cross-run provenance checks performed before cloud auth."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from typing import Any

from scripts.staging_infrastructure_apply_approval import COMMIT, RUN_ID, SHA256, MutationApprovalError, validate_apply_ready_package
from scripts.staging_infrastructure_operator_attestation import (
    OperatorAttestationError,
    validate_attested_runtime_context,
)
from scripts.staging_infrastructure_operator_signature import (
    OperatorSignatureError,
    verify_operator_attestation_envelope,
)

BRANCH = "refs/heads/feat/firebase-collaboration-mvp-v1"
WORKFLOW_PATH = ".github/workflows/staging-infrastructure-apply.yml"
REPOSITORY = "WBmaker2/rhwp"
REQUIRED = frozenset({"packageSha256", "executorCommitSha", "executorTreeSha", "expectedExecutorTreeSha", "repository", "expectedRepository", "repositoryId", "expectedRepositoryId", "repositoryOwnerId", "expectedRepositoryOwnerId", "ref", "expectedRef", "workflowRef", "expectedWorkflowRef", "workflowSha", "expectedWorkflowSha", "workflowContentSha256", "expectedWorkflowContentSha256", "runId", "runAttempt", "artifactSourceRunId", "artifactId", "artifactName", "artifactArchiveSha256", "artifactSourceCommitSha"})

class ProvenanceError(RuntimeError): pass

def validate_pre_auth_provenance(
    package: dict[str, Any], approved: dict[str, Any], claims: dict[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if set(claims) != REQUIRED: raise ProvenanceError("provenance claims must use exact v2 schema")
    try: review = validate_apply_ready_package(package, now=now)
    except MutationApprovalError as error: raise ProvenanceError("pre-auth requires an apply-ready package") from error
    if approved.get("cloudMutationApproved") is not True or approved.get("deploymentApproved") is not False: raise ProvenanceError("validated non-deployment approval is required")
    if claims["packageSha256"] != approved.get("applyReadyPackageSha256") or not _sha(claims["packageSha256"]): raise ProvenanceError("package digest claim is invalid")
    source = review.get("sourceEvidence", {}).get("sourceCommitSha")
    if not _commit(source) or claims["artifactSourceCommitSha"] != claims["executorCommitSha"]: raise ProvenanceError("artifact source commit does not independently bind the checked-out executor")
    if claims["executorCommitSha"] != review.get("executorCommit", {}).get("sha") or claims["executorCommitSha"] != approved.get("executorCommitSha") or not _commit(claims["executorCommitSha"]): raise ProvenanceError("actual run revision does not match declared executor commit")
    if claims["executorTreeSha"] != claims["expectedExecutorTreeSha"] or not _commit(claims["executorTreeSha"]): raise ProvenanceError("executor commit tree does not match protected expected tree")
    for actual, expected in (("repository", "expectedRepository"), ("repositoryId", "expectedRepositoryId"), ("repositoryOwnerId", "expectedRepositoryOwnerId"), ("ref", "expectedRef"), ("workflowRef", "expectedWorkflowRef"), ("workflowSha", "expectedWorkflowSha"), ("workflowContentSha256", "expectedWorkflowContentSha256")):
        if claims[actual] != claims[expected]: raise ProvenanceError(f"{actual} does not match protected expected value")
    if claims["repository"] != REPOSITORY or claims["ref"] != BRANCH or claims["workflowRef"] != f"{REPOSITORY}/{WORKFLOW_PATH}@{BRANCH}": raise ProvenanceError("actual GitHub repository/ref/workflow_ref is not allowed")
    if not all(_id(claims[k]) for k in ("repositoryId", "repositoryOwnerId", "runId", "artifactSourceRunId", "artifactId")) or not isinstance(claims["runAttempt"], int) or claims["runAttempt"] <= 0: raise ProvenanceError("actual GitHub identity is malformed")
    if claims["runId"] != approved.get("approvedRunId") or claims["runAttempt"] != approved.get("approvedRunAttempt"): raise ProvenanceError("approval is not bound to this run identity")
    if claims["artifactSourceRunId"] != claims["runId"] or claims["artifactName"] != "staging-infrastructure-approved-evidence": raise ProvenanceError("approval artifact is not published by this protected apply run")
    if not _commit(claims["workflowSha"]) or not _commit(claims["artifactSourceCommitSha"]) or not _sha(claims["workflowContentSha256"]) or not _sha(claims["artifactArchiveSha256"]): raise ProvenanceError("workflow or artifact immutable digest is malformed")
    try:
        environment = verify_operator_attestation_envelope(package["environmentAttestation"])
        wif = verify_operator_attestation_envelope(package["wifAttestation"])
        validate_attested_runtime_context(
            environment, wif, claims,
            project_id=review["projectId"], workflow_sha=review["executorCommit"]["sha"],
            now=now,
        )
    except (OperatorAttestationError, OperatorSignatureError) as error:
        raise ProvenanceError("actual run context or operator attestation is invalid") from error
    return dict(claims)


def validate_checked_out_git_binding(package: dict[str, Any], claims: dict[str, Any], *, git_runner: Any = None) -> None:
    """Bind artifact source and executor to checked-out immutable Git objects.

    This deliberately derives every fact from Git rather than accepting a pair
    copied from the review package into workflow claims.
    """
    try: review = validate_apply_ready_package(package)
    except MutationApprovalError as error: raise ProvenanceError("Git binding requires an apply-ready package") from error
    source = review.get("sourceEvidence", {}).get("sourceCommitSha")
    executor = claims.get("executorCommitSha")
    if not _commit(source) or not _commit(executor):
        raise ProvenanceError("Git binding commits are malformed")
    run = git_runner or _git
    try:
        run(("cat-file", "-e", f"{source}^{{commit}}"))
        run(("cat-file", "-e", f"{executor}^{{commit}}"))
        tree = run(("rev-parse", f"{executor}^{{tree}}")).strip()
        if tree != claims.get("executorTreeSha"):
            raise ProvenanceError("checked-out executor tree does not match claim")
        run(("merge-base", "--is-ancestor", source, executor))
        remote_branch = "refs/remotes/origin/feat/firebase-collaboration-mvp-v1"
        run(("show-ref", "--verify", "--quiet", remote_branch))
        run(("merge-base", "--is-ancestor", executor, remote_branch))
    except ProvenanceError:
        raise
    except Exception as error:
        raise ProvenanceError("checked-out Git object or approved-branch relationship is invalid") from error


def _git(args: tuple[str, ...]) -> str:
    completed = subprocess.run(("git", *args), check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if completed.returncode != 0:
        raise ProvenanceError("Git verification command failed")
    return completed.stdout

def _sha(v: Any) -> bool: return isinstance(v, str) and SHA256.fullmatch(v) is not None
def _commit(v: Any) -> bool: return isinstance(v, str) and COMMIT.fullmatch(v) is not None
def _id(v: Any) -> bool: return isinstance(v, str) and RUN_ID.fullmatch(v) is not None


def validate_auth_configuration(
    package: dict[str, Any], claims: dict[str, Any], provider: Any,
    service_account: Any, *, now: datetime | None = None,
) -> None:
    """Ensure the auth action receives the immutable, promoted WIF identifiers."""
    try: validate_apply_ready_package(package, now=now)
    except MutationApprovalError as error: raise ProvenanceError("WIF auth requires an apply-ready package") from error
    try:
        wif = verify_operator_attestation_envelope(package["wifAttestation"])
    except OperatorSignatureError as error:
        raise ProvenanceError("WIF auth requires a valid immutable operator signature") from error
    if provider != wif["providerResourceName"] or service_account != wif["serviceAccount"]:
        raise ProvenanceError("auth configuration differs from promoted WIF identifiers")
    if claims["repositoryId"] != wif["repositoryId"] or claims["repositoryOwnerId"] != wif["repositoryOwnerId"] or claims["ref"] != wif["ref"] or claims["workflowRef"] != wif["workflowRef"] or claims["workflowSha"] != wif["workflowSha"]:
        raise ProvenanceError("actual GitHub claims differ from enforced WIF condition")
