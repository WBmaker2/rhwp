"""Non-applied future Environment, WIF, and IAM review specifications."""
from __future__ import annotations

from typing import Any


def protected_environment_spec() -> dict[str, Any]:
    return {
        "name": "staging-infrastructure-apply",
        "configuredByThisPackage": False,
        "requiredReviewerCountMinimum": 1,
        "preventSelfReview": True,
        "canAdminsBypass": False,
        "supportVerificationStatus": "required-before-apply",
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
        ],
        "currentReviewJobPermissions": {
            "contents": "read",
            "actions": "none",
            "id-token": "none",
        },
        "futureApplyJobPermissions": {
            "contents": "read",
            "actions": "read",
            "id-token": "write",
        },
    }


def wif_and_iam_diff() -> dict[str, Any]:
    apply_workflow = ".github/workflows/staging-infrastructure-apply.yml"
    review_workflow = ".github/workflows/staging-infrastructure-apply-review.yml"
    return {
        "status": "proposed-diff-requires-live-review",
        "actualIdentifiersIncluded": False,
        "providerVariable": "GCP_WORKLOAD_IDENTITY_PROVIDER",
        "serviceAccountVariable": "GCP_DEPLOYER_SERVICE_ACCOUNT",
        "attributeMapping": {
            "google.subject": "assertion.sub",
            "attribute.repository": "assertion.repository",
            "attribute.ref": "assertion.ref",
            "attribute.workflow_ref": "assertion.workflow_ref",
            "attribute.repository_id": "assertion.repository_id",
            "attribute.repository_owner_id": "assertion.repository_owner_id",
            "attribute.workflow_sha": "assertion.workflow_sha",
        },
        "requiredActualInputs": {
            "repositoryId": {"value": None, "expectedFormat": "^[0-9]+$"},
            "repositoryOwnerId": {"value": None, "expectedFormat": "^[0-9]+$"},
            "workflowSha": {"value": None, "expectedFormat": "^[0-9a-f]{40}$"},
        },
        "proposedConditionStatus": "incomplete-until-actual-immutable-claims-approved",
        "applicable": False,
        "oidcAttributeConditions": {
            "repository": "WBmaker2/rhwp",
            "ref": "refs/heads/feat/firebase-collaboration-mvp-v1",
            "workflowRef": (
                "WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml"
                "@refs/heads/feat/firebase-collaboration-mvp-v1"
            ),
            "implemented": False,
            "excludedWorkflows": [review_workflow],
        },
        "finalConditionRequirements": {
            "repositoryId": "approved immutable attribute.repository_id",
            "repositoryOwnerId": "approved immutable attribute.repository_owner_id",
            "workflowSha": "approved reviewed attribute.workflow_sha",
            "ref": "refs/heads/feat/firebase-collaboration-mvp-v1",
            "workflowRef": (
                "WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml"
                "@refs/heads/feat/firebase-collaboration-mvp-v1"
            ),
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


def _custom_roles() -> list[dict[str, Any]]:
    return [
        _role("stagingApiEnableOnly", ["serviceusage.services.enable"], ["serviceusage.services.disable"]),
        _role("stagingServiceAccountCreateOnly", ["iam.serviceAccounts.create"], ["iam.serviceAccountKeys.create", "iam.serviceAccountKeys.delete", "iam.serviceAccounts.delete", "iam.serviceAccounts.getAccessToken"]),
        _role("stagingArtifactRegistryRepositoryCreateRead", ["artifactregistry.repositories.create", "artifactregistry.repositories.get", "artifactregistry.repositories.list"], ["artifactregistry.repositories.delete"]),
        _role("stagingSecretManagerMetadataCreateReadList", ["secretmanager.secrets.create", "secretmanager.secrets.get", "secretmanager.secrets.list"], ["secretmanager.secrets.delete", "secretmanager.versions.access", "secretmanager.versions.add", "secretmanager.versions.destroy"]),
    ]


def _role(role_id: str, included: list[str], excluded: list[str]) -> dict[str, Any]:
    return {
        "principal": "approved-deployer-service-account", "roleType": "custom",
        "roleId": role_id, "scope": "staging-project",
        "includedPermissions": included, "excludedPermissions": excluded,
    }
