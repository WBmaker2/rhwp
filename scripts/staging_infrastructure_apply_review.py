#!/usr/bin/env python3
"""Build a non-mutating review package for guarded staging apply promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.staging_infrastructure_action_io import ActionIoError, publish
    from scripts.staging_infrastructure_actions import (
        InfrastructureActionsError,
        build_execution_manifest,
    )
    from scripts.staging_infrastructure_approval import load_json_with_bytes
    from scripts.staging_infrastructure_apply_review_paths import (
        ApplyReviewPathError,
        validate_cli_paths,
    )
    from scripts.staging_infrastructure_apply_review_policy import (
        protected_environment_spec,
        wif_and_iam_diff,
    )
    from scripts.staging_infrastructure_validation import (
        StrictJsonError,
        canonical_json_bytes,
        validate_json_domain,
    )
    from scripts.staging_infrastructure_apply_safety import ApplySafetyError, reject_sensitive_string_leaves
except ImportError:  # pragma: no cover - direct script execution
    from staging_infrastructure_action_io import ActionIoError, publish
    from staging_infrastructure_actions import (  # type: ignore[no-redef]
        InfrastructureActionsError,
        build_execution_manifest,
    )
    from staging_infrastructure_approval import load_json_with_bytes  # type: ignore[no-redef]
    from staging_infrastructure_apply_review_paths import (  # type: ignore[no-redef]
        ApplyReviewPathError,
        validate_cli_paths,
    )
    from staging_infrastructure_apply_review_policy import (  # type: ignore[no-redef]
        protected_environment_spec,
        wif_and_iam_diff,
    )
    from staging_infrastructure_validation import (  # type: ignore[no-redef]
        StrictJsonError,
        canonical_json_bytes,
        validate_json_domain,
    )
    from staging_infrastructure_apply_safety import ApplySafetyError, reject_sensitive_string_leaves  # type: ignore[no-redef]

SCHEMA = "rhwp.staging-infrastructure-apply-review/v2"
EXECUTION_SCHEMA = "rhwp.staging-infrastructure-execution/v1"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ELIGIBLE_STAGES = (
    "api-baseline",
    "service-accounts",
    "artifact-registry",
    "secret-metadata",
)
ALLOWED_KINDS = {
    "api-baseline": "ensure-api-enabled",
    "service-accounts": "ensure-service-account",
    "artifact-registry": "ensure-artifact-repository",
    "secret-metadata": "ensure-secret-container",
}


class ApplyReviewError(RuntimeError):
    pass


def build_apply_review_package(
    plan: dict[str, Any],
    approval_result: dict[str, Any],
    execution_manifest: dict[str, Any],
    *,
    plan_bytes: bytes,
    executor_commit_sha: str,
) -> dict[str, Any]:
    """Bind reviewed evidence and emit no cloud authority or executable command."""
    try:
        validate_json_domain(execution_manifest)
        rebuilt = build_execution_manifest(
            plan,
            approval_result,
            plan_bytes=plan_bytes,
        )
    except (StrictJsonError, InfrastructureActionsError) as error:
        raise ApplyReviewError("source plan bytes or evidence validation failed") from error

    if execution_manifest != rebuilt:
        raise ApplyReviewError("execution manifest does not match canonical rebuilt evidence")
    if execution_manifest.get("schemaVersion") != EXECUTION_SCHEMA:
        raise ApplyReviewError("execution manifest schema is not supported")
    if execution_manifest.get("status") != "awaiting-cloud-mutation-approval":
        raise ApplyReviewError("execution manifest must remain awaiting cloud mutation approval")
    if approval_result.get("cloudMutationApproved") is not False:
        raise ApplyReviewError("plan review must not contain cloud mutation authority")
    if not isinstance(executor_commit_sha, str) or not COMMIT_PATTERN.fullmatch(
        executor_commit_sha
    ):
        raise ApplyReviewError("executor commit SHA must be 40 lowercase hexadecimal characters")

    subset = _canonical_subset(execution_manifest)
    source = execution_manifest["sourceEvidence"]
    package = {
        "schemaVersion": SCHEMA,
        "status": "ready-for-apply-review",
        "projectId": execution_manifest["projectId"],
        "executorCommit": {
            "sha": executor_commit_sha,
            "provenance": "caller-declared-unverified",
            "immutableVerifiedProvenance": False,
            "independentVerificationRequired": [
                "verify-commit-membership-in-approved-branch",
                "verify-commit-object-and-tree",
                "verify-approved-apply-workflow-path-and-content",
            ],
        },
        "sourceEvidence": {
            "planSha256": source["planSha256"],
            "planObjectSha256": source["planObjectSha256"],
            "actionSetSha256": source["actionSetSha256"],
            "sourceCommitSha": source["commitSha"],
            "approvalResultSchema": source["approvalResultSchema"],
            "canonicalActionSetSha256": hashlib.sha256(
                canonical_json_bytes(subset).rstrip(b"\n")
            ).hexdigest(),
        },
        "mutationArchitecture": {
            "authenticationBeforeValidationAllowed": False,
            "exactEvidenceBindingRequired": True,
            "firstFailureStopsExecution": True,
            "automaticDeleteRollbackAllowed": False,
            "futureExecutorImplemented": True,
            "prepareJobMayAuthenticateCloud": False,
            "prepareJobMayMutateCloud": False,
            "protectedApplyJobRequired": True,
        },
        "evidenceTransport": {
            "artifactName": "staging-infrastructure-approved-evidence",
            "actualEvidenceTrackedInGit": False,
            "exactByteDigestRequired": True,
            "prepareJobCreatesRunBoundRecord": True,
            "sameRunArtifactOnly": True,
            "publicationBeforeCloudAuthentication": True,
            "operatorReceiptSignatureRequired": True,
            "operatorSigningKeyRegistry": "immutable-tracked-code",
            "packageSource": "repository-variable-base64",
            "environmentCarriesRunBoundJson": False,
            "containsCredentials": False,
            "containsSecretValues": False,
        },
        "canonicalMutationSubset": subset,
        "executorActionAllowlistEnforcement": _executor_action_allowlist(subset),
        "protectedEnvironmentSpec": protected_environment_spec(),
        "wifIdentityAndIamDiff": wif_and_iam_diff(),
        "requiredApprovalRecordSchema": "rhwp.staging-infrastructure-apply-ready/v3",
        "requiredApprovals": [
            "actual-review-package",
            "actual-environment-settings",
            "actual-wif-identity",
            "actual-live-iam-before-after-diff",
            "operator-attestation-signing-key",
            "cloud-mutation-approval-record",
            "apply-workflow-diff",
            "apply-workflow-dispatch",
        ],
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }
    _assert_safe_package(package)
    return package


def _canonical_subset(execution: dict[str, Any]) -> list[dict[str, Any]]:
    actions = execution.get("actions")
    if not isinstance(actions, list):
        raise ApplyReviewError("execution actions must be an array")
    subset: list[dict[str, Any]] = []
    seen_stages: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise ApplyReviewError("execution action must be an object")
        stage = action.get("stageId")
        if stage not in ELIGIBLE_STAGES:
            continue
        if action.get("classification") != "eligible-mutation":
            raise ApplyReviewError("eligible stage classification does not match")
        if action.get("kind") != ALLOWED_KINDS[stage]:
            raise ApplyReviewError("eligible stage action kind is not canonical")
        resource = action.get("resource")
        evidence = action.get("evidenceQuery")
        desired = action.get("desiredState")
        if not all(isinstance(item, dict) for item in (resource, evidence, desired)):
            raise ApplyReviewError("eligible action structure is invalid")
        subset.append(
            {
                "actionId": action.get("id"),
                "stageId": stage,
                "resourceKind": action["kind"],
                "resourceIdentifier": resource,
                "desiredState": desired,
                "preconditionEvidence": evidence,
                "rollbackDisposition": action.get("rollbackBoundary"),
            }
        )
        seen_stages.add(stage)
    if seen_stages != set(ELIGIBLE_STAGES) or not subset:
        raise ApplyReviewError("canonical eligible mutation subset is incomplete")
    return subset


def _executor_action_allowlist(subset: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "implemented": True,
        "iamScopeAloneSufficient": False,
        "independentExecutorEnforcementRequired": True,
        "liveProjectScopeBindingDiffRequired": True,
        "approvedActions": [
            {
                "actionId": item["actionId"],
                "resourceIdentifier": item["resourceIdentifier"],
                "preconditionEvidence": item["preconditionEvidence"],
            }
            for item in subset
        ],
    }


def _assert_safe_package(package: dict[str, Any]) -> None:
    validate_json_domain(package)
    try:
        reject_sensitive_string_leaves(package, "review package")
    except ApplySafetyError as error:
        raise ApplyReviewError("review package contains a credential-shaped value") from error
    encoded = canonical_json_bytes(package).decode("utf-8").lower()
    forbidden_keys = (
        '"command":',
        '"argv":',
        '"shell":',
        '"accesstoken":',
        '"idtoken":',
        '"authorization":',
        '"privatekey":',
        '"secretvalue":',
        '"credential":',
    )
    if any(marker in encoded for marker in forbidden_keys):
        raise ApplyReviewError("review package contains a forbidden execution or sensitive key")
    if package["cloudMutationApproved"] is not False:
        raise ApplyReviewError("review package cannot approve cloud mutation")
    if package["deploymentApproved"] is not False or package["mutationCommands"] != []:
        raise ApplyReviewError("review package cannot authorize deployment or commands")


def render_markdown(package: dict[str, Any]) -> str:
    lines = [
        "# rhwp Staging Infrastructure Apply Review Package",
        "",
        "> This package is review evidence only. It does not authenticate or mutate cloud resources.",
        "",
        f"- Status: `{_md(package.get('status'))}`",
        f"- Project ID: `{_md(package.get('projectId'))}`",
        f"- Executor commit (caller-declared, unverified): `{_md(package.get('executorCommit', {}).get('sha'))}`",
        "- Future apply must independently verify approved-branch membership and the commit tree before authentication.",
        "- Cloud mutation approved: `False`",
        "- Deployment approved: `False`",
        "",
        "## Canonical mutation candidates",
        "",
        "| Action | Stage | Kind |",
        "|---|---|---|",
    ]
    for item in package.get("canonicalMutationSubset", []):
        lines.append(
            f"| `{_md(item.get('actionId'))}` | `{_md(item.get('stageId'))}` | "
            f"`{_md(item.get('resourceKind'))}` |"
        )
    lines.extend(
        [
            "",
            "## Required approvals before apply",
            "",
            *[f"- `{_md(item)}`" for item in package.get("requiredApprovals", [])],
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a non-mutating staging infrastructure apply review package"
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval-result", type=Path, required=True)
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--executor-commit-sha", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_cli_paths(
            args.plan,
            args.approval_result,
            args.execution_manifest,
            args.json_output,
            args.markdown_output,
        )
        plan, raw = load_json_with_bytes(args.plan, "infrastructure plan")
        approval, _ = load_json_with_bytes(
            args.approval_result, "infrastructure approval result"
        )
        execution, _ = load_json_with_bytes(
            args.execution_manifest, "infrastructure execution manifest"
        )
        package = build_apply_review_package(
            plan,
            approval,
            execution,
            plan_bytes=raw,
            executor_commit_sha=args.executor_commit_sha,
        )
        json_text = canonical_json_bytes(package, indent=2).decode("utf-8")
        marker = publish(
            args.json_output,
            args.markdown_output,
            json_text,
            render_markdown(package),
        )
    except (
        ActionIoError,
        ApplyReviewError,
        ApplyReviewPathError,
        InfrastructureActionsError,
        StrictJsonError,
    ) as error:
        print(f"staging infrastructure apply review failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": package["status"],
                "projectId": package["projectId"],
                "jsonOutput": str(args.json_output),
                "markdownOutput": str(args.markdown_output),
                "completionMarker": str(marker),
                "cloudMutationApproved": False,
                "deploymentApproved": False,
                "mutationCommands": [],
            }
        )
    )
    return 0


def _md(value: Any) -> str:
    return re.sub(
        r"[\x00-\x1f\x7f\x85\u2028\u2029]",
        " ",
        "" if value is None else str(value),
    ).replace("|", "\\|").replace("`", "'")


if __name__ == "__main__":
    raise SystemExit(main())
