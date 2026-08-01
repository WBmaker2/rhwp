"""Non-applied future Environment, WIF, and IAM review specifications."""
from __future__ import annotations

from typing import Any


REPOSITORY = "WBmaker2/rhwp"
APPLY_BRANCH = "refs/heads/feat/firebase-collaboration-mvp-v1"
APPLY_WORKFLOW_PATH = ".github/workflows/staging-infrastructure-apply.yml"
APPLY_WORKFLOW_REF = f"{REPOSITORY}/{APPLY_WORKFLOW_PATH}@{APPLY_BRANCH}"
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com/"


def protected_environment_spec() -> dict[str, Any]:
    return {
        "name": "staging-infrastructure-apply",
        "configuredByThisPackage": False,
        "requiredReviewerCountMinimum": 1,
        "preventSelfReview": False,
        "canAdminsBypass": False,
        "adminBypassUiConfigurationRequired": True,
        "adminBypassRestObservationException": "unavailable-in-official-rest-only",
        "supportVerificationStatus": "operator-read-only-attestation-required",
        "unsupportedOrUnverifiedBlocksApprovalApply": True,
        "deploymentBranchPolicy": {
            "protectedBranches": False,
            "customBranchPolicies": True,
            "branchPolicies": [
                {"name": "feat/firebase-collaboration-mvp-v1", "type": "branch"}
            ],
            "tagPolicies": [],
        },
        "secrets": [],
        "longLivedCloudCredentials": [],
        "variableNames": [
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
        "currentReviewJobPermissions": {
            "contents": "read",
            "actions": "read",
            "id-token": "none",
        },
        "futureApplyJobPermissions": {
            "contents": "read",
            "actions": "read",
            "id-token": "write",
        },
    }


def wif_and_iam_diff() -> dict[str, Any]:
    review_workflow = ".github/workflows/staging-infrastructure-apply-review.yml"
    return {
        "status": "proposed-diff-requires-live-review",
        "actualIdentifiersIncluded": False,
        "providerVariable": "GCP_WORKLOAD_IDENTITY_PROVIDER",
        "serviceAccountVariable": "GCP_DEPLOYER_SERVICE_ACCOUNT",
        "attributeMapping": wif_attribute_mapping(),
        "requiredActualInputs": {
            "repositoryId": {"value": None, "expectedFormat": "^[0-9]+$"},
            "repositoryOwnerId": {"value": None, "expectedFormat": "^[0-9]+$"},
            "workflowSha": {"value": None, "expectedFormat": "^[0-9a-f]{40}$"},
        },
        "proposedConditionStatus": "incomplete-until-actual-immutable-claims-approved",
        "applicable": False,
        "oidcAttributeConditions": {
            "repository": REPOSITORY,
            "ref": APPLY_BRANCH,
            "workflowRef": APPLY_WORKFLOW_REF,
            "implemented": False,
            "excludedWorkflows": [review_workflow],
        },
        "finalConditionRequirements": {
            "repositoryId": "approved immutable attribute.repository_id",
            "repositoryOwnerId": "approved immutable attribute.repository_owner_id",
            "workflowSha": "approved reviewed attribute.workflow_sha",
            "ref": APPLY_BRANCH,
            "workflowRef": APPLY_WORKFLOW_REF,
        },
        "candidateBindings": [
            {
                "principal": "approved-github-oidc-principal",
                "role": "roles/iam.workloadIdentityUser",
                "scope": "deployer-service-account",
            },
            *_custom_roles(),
        ],
        "forbiddenRoles": [
            "roles/owner", "roles/editor", "roles/firebase.admin", "roles/run.admin",
            "roles/cloudtasks.admin", "roles/serviceusage.serviceUsageAdmin",
            "roles/iam.serviceAccountAdmin", "roles/artifactregistry.admin",
            "roles/secretmanager.admin",
        ],
        "serviceAccountKeysAllowed": False,
        "liveBeforeAfterDiffRequired": True,
        "liveProjectScopeBindingDiffRequired": True,
        "projectScopeTruth": {
            "createEnablePermissionsRequireProjectScope": True,
            "iamScopeConstrainsResourceIdentifiers": False,
            "independentExecutorAllowlistRequired": True,
        },
    }


def wif_attribute_mapping() -> dict[str, str]:
    """Return the literal provider mapping that the operator must observe."""
    return {
        "google.subject": "assertion.sub",
        "attribute.repository": "assertion.repository",
        "attribute.ref": "assertion.ref",
        "attribute.workflow_ref": "assertion.workflow_ref",
        "attribute.repository_id": "assertion.repository_id",
        "attribute.repository_owner_id": "assertion.repository_owner_id",
        "attribute.workflow_sha": "assertion.workflow_sha",
    }


def wif_expected_condition(
    repository_id: str, repository_owner_id: str, workflow_sha: str
) -> str:
    """Build the exact CEL condition approved for this one apply workflow."""
    return (
        f"attribute.repository == '{REPOSITORY}' && "
        f"attribute.repository_id == '{repository_id}' && "
        f"attribute.repository_owner_id == '{repository_owner_id}' && "
        f"attribute.ref == '{APPLY_BRANCH}' && "
        f"attribute.workflow_ref == '{APPLY_WORKFLOW_REF}' && "
        f"attribute.workflow_sha == '{workflow_sha}'"
    )


def wif_expected_principal(provider_resource_name: str, repository_id: str) -> str:
    """Return the sole allowed principalSet member for the deployer account."""
    prefix, _, _ = provider_resource_name.partition("/providers/")
    return (
        "principalSet://iam.googleapis.com/"
        f"{prefix}/attribute.repository_id/{repository_id}"
    )


def _custom_roles() -> list[dict[str, Any]]:
    return [
        _role("stagingApiEnableOnly", ["serviceusage.services.enable", "serviceusage.services.list"], ["serviceusage.services.disable"]),
        _role("stagingServiceAccountCreateReadList", ["iam.serviceAccounts.create", "iam.serviceAccounts.get", "iam.serviceAccounts.list", "iam.serviceAccountKeys.list"], ["iam.serviceAccountKeys.create", "iam.serviceAccountKeys.delete", "iam.serviceAccounts.delete", "iam.serviceAccounts.getAccessToken"]),
        _role("stagingArtifactRegistryRepositoryCreateRead", ["artifactregistry.repositories.create", "artifactregistry.repositories.get", "artifactregistry.repositories.list"], ["artifactregistry.repositories.delete"]),
        _role("stagingSecretManagerMetadataCreateReadList", ["secretmanager.secrets.create", "secretmanager.secrets.get", "secretmanager.secrets.list"], ["secretmanager.secrets.delete", "secretmanager.versions.access", "secretmanager.versions.add", "secretmanager.versions.destroy"]),
    ]


def _role(role_id: str, included: list[str], excluded: list[str]) -> dict[str, Any]:
    return {
        "principal": "approved-deployer-service-account", "roleType": "custom",
        "roleId": role_id, "scope": "staging-project",
        "includedPermissions": included, "excludedPermissions": excluded,
    }
