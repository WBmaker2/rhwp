#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

BOOTSTRAP_APPROVAL_SCHEMA = "rhwp.staging-bootstrap-approval/v1"
INFRASTRUCTURE_PLAN_SCHEMA = "rhwp.staging-infrastructure-plan/v1"
PACKET_SCHEMA = "rhwp.staging-approval-packet/v1"
MANIFEST_SCHEMA = "rhwp.staging/v1"
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BILLING_ACCOUNT_PATTERN = re.compile(r"^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

APPROVAL_RECORD_KEYS = frozenset({
    "schemaVersion",
    "decision",
    "approvedAt",
    "approvedBy",
    "commitSha",
    "workflowRunId",
    "packetSha256",
    "projectId",
    "billingAccount",
    "acceptedDeferredPaths",
    "securityExceptions",
    "deploymentApproved",
    "cloudMutationApproved",
})
ALLOWED_SECURITY_EXCEPTIONS = frozenset({"mvp-staging-internal-token"})
SENSITIVE_KEY_MARKERS = (
    "accesstoken",
    "authorization",
    "clientsecret",
    "credential",
    "idtoken",
    "password",
    "privatekey",
    "refreshtoken",
    "secretvalue",
)


class InfrastructurePlanError(RuntimeError):
    pass


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise InfrastructurePlanError(f"{label} not found: {path}") from error
    except json.JSONDecodeError as error:
        raise InfrastructurePlanError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise InfrastructurePlanError(f"{label} root must be an object")
    return value


def validate_bootstrap_approval_record(
    record: dict[str, Any],
    packet: dict[str, Any],
    packet_sha256: str,
) -> None:
    sensitive_paths = _find_sensitive_key_paths(record, "approval")
    if sensitive_paths:
        raise InfrastructurePlanError(
            "sensitive key is not allowed at " + ", ".join(sorted(sensitive_paths))
        )

    _require_exact_keys(record, APPROVAL_RECORD_KEYS, "approval record")
    if record.get("schemaVersion") != BOOTSTRAP_APPROVAL_SCHEMA:
        raise InfrastructurePlanError(
            f"approval record schemaVersion must be {BOOTSTRAP_APPROVAL_SCHEMA}"
        )
    if packet.get("schemaVersion") != PACKET_SCHEMA:
        raise InfrastructurePlanError(f"bootstrap packet schemaVersion must be {PACKET_SCHEMA}")
    if packet.get("phase") != "bootstrap":
        raise InfrastructurePlanError("bootstrap packet phase must be bootstrap")
    if packet.get("status") != "ready-for-bootstrap-approval":
        raise InfrastructurePlanError(
            "bootstrap packet status must be ready-for-bootstrap-approval"
        )
    if record.get("decision") != "approved":
        raise InfrastructurePlanError("approval record decision must be approved")

    approved_at = _required_string(record, "approvedAt", "approval record")
    if not UTC_TIMESTAMP_PATTERN.fullmatch(approved_at):
        raise InfrastructurePlanError(
            "approval record approvedAt must use UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    _non_empty_string_list(record, "approvedBy", "approval record")

    commit_sha = _required_string(record, "commitSha", "approval record")
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise InfrastructurePlanError(
            "approval record commitSha must be 40 lowercase hexadecimal characters"
        )
    workflow_run_id = record.get("workflowRunId")
    if isinstance(workflow_run_id, bool) or not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise InfrastructurePlanError("approval record workflowRunId must be a positive integer")

    expected_digest = _required_string(record, "packetSha256", "approval record")
    if not SHA256_PATTERN.fullmatch(expected_digest):
        raise InfrastructurePlanError(
            "approval record packetSha256 must be a 64-character SHA-256 digest"
        )
    if not SHA256_PATTERN.fullmatch(packet_sha256) or expected_digest != packet_sha256:
        raise InfrastructurePlanError("bootstrap packet digest does not match approval record")

    project_id = _required_string(record, "projectId", "approval record")
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise InfrastructurePlanError("approval record projectId is not a valid GCP project ID")
    lowered = project_id.lower()
    if "production" in lowered or re.search(r"(^|-)prod($|-)", lowered):
        raise InfrastructurePlanError("approval record projectId must not be production-like")

    billing_account = _required_string(record, "billingAccount", "approval record")
    if not BILLING_ACCOUNT_PATTERN.fullmatch(billing_account):
        raise InfrastructurePlanError(
            "approval record billingAccount must use XXXXXX-XXXXXX-XXXXXX format"
        )

    packet_project = _mapping(packet, "project", "bootstrap packet")
    if project_id != packet_project.get("id"):
        raise InfrastructurePlanError("approval record projectId does not match bootstrap packet")
    if billing_account != packet_project.get("billingAccount"):
        raise InfrastructurePlanError(
            "approval record billingAccount does not match bootstrap packet"
        )

    accepted_paths = _string_list(
        record,
        "acceptedDeferredPaths",
        "approval record",
        allow_empty=True,
    )
    if len(accepted_paths) != len(set(accepted_paths)):
        raise InfrastructurePlanError(
            "approval record acceptedDeferredPaths must not contain duplicates"
        )
    packet_deferred = packet.get("deferredValues")
    if not isinstance(packet_deferred, list):
        raise InfrastructurePlanError("bootstrap packet deferredValues must be an array")
    packet_paths: list[str] = []
    for index, entry in enumerate(packet_deferred):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise InfrastructurePlanError(
                f"bootstrap packet deferredValues[{index}].path must be a string"
            )
        packet_paths.append(entry["path"])
    if set(accepted_paths) != set(packet_paths):
        raise InfrastructurePlanError(
            "approval record accepted deferred paths do not match bootstrap packet"
        )

    security_exceptions = _string_list(
        record,
        "securityExceptions",
        "approval record",
        allow_empty=True,
    )
    if len(security_exceptions) != len(set(security_exceptions)):
        raise InfrastructurePlanError(
            "approval record securityExceptions must not contain duplicates"
        )
    unknown_exceptions = sorted(set(security_exceptions) - ALLOWED_SECURITY_EXCEPTIONS)
    if unknown_exceptions:
        raise InfrastructurePlanError(
            "approval record contains unknown security exception: "
            + ", ".join(unknown_exceptions)
        )
    internal_flush = _mapping(packet, "internalFlush", "bootstrap packet")
    if internal_flush.get("decision") == "mvp-staging-internal-token" and (
        "mvp-staging-internal-token" not in security_exceptions
    ):
        raise InfrastructurePlanError(
            "approval record must acknowledge the staging internal flush security exception"
        )

    if record.get("deploymentApproved") is not False:
        raise InfrastructurePlanError("approval record deploymentApproved must remain false")
    if record.get("cloudMutationApproved") is not False:
        raise InfrastructurePlanError("approval record cloudMutationApproved must remain false")

    security = _mapping(packet, "security", "bootstrap packet")
    if security.get("containsCloudMutationCommands") is not False:
        raise InfrastructurePlanError(
            "bootstrap packet containsCloudMutationCommands must remain false"
        )
    if security.get("mutationCommands") != []:
        raise InfrastructurePlanError("bootstrap packet mutationCommands must be empty")


def build_infrastructure_plan(
    manifest: dict[str, Any],
    packet: dict[str, Any],
    approval: dict[str, Any],
    packet_sha256: str,
) -> dict[str, Any]:
    validate_bootstrap_approval_record(approval, packet, packet_sha256)
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise InfrastructurePlanError(f"manifest schemaVersion must be {MANIFEST_SCHEMA}")
    if manifest.get("environment") != "staging":
        raise InfrastructurePlanError("manifest environment must be staging")

    project = _mapping(manifest, "project", "manifest")
    operations = _mapping(manifest, "operations", "manifest")
    packet_project = _mapping(packet, "project", "bootstrap packet")
    if project.get("id") != packet_project.get("id"):
        raise InfrastructurePlanError("manifest project ID does not match bootstrap packet")
    if project.get("billingAccount") != packet_project.get("billingAccount"):
        raise InfrastructurePlanError("manifest billing account does not match bootstrap packet")
    if operations.get("cloudMutationApproved") is not False:
        raise InfrastructurePlanError(
            "manifest operations.cloudMutationApproved must remain false"
        )
    packet_approval = _mapping(packet, "approval", "bootstrap packet")
    if operations.get("approvalReference") != packet_approval.get("reference"):
        raise InfrastructurePlanError(
            "manifest approvalReference does not match bootstrap packet"
        )

    firebase = _mapping(manifest, "firebase", "manifest")
    artifact_registry = _mapping(manifest, "artifactRegistry", "manifest")
    cloud_run = _mapping(manifest, "cloudRun", "manifest")
    tasks = _mapping(manifest, "tasks", "manifest")
    secrets = _mapping(manifest, "secrets", "manifest")
    iam = _mapping(manifest, "iam", "manifest")
    budget = _mapping(manifest, "budget", "manifest")

    required_values = _post_bootstrap_required_values(packet)
    stages = [
        _stage(
            "project-billing",
            "Project and billing boundary",
            "Prepare the dedicated staging project boundary and approved billing relationship.",
            [],
            {
                "projectId": project.get("id"),
                "billingAccount": project.get("billingAccount"),
                "region": project.get("region"),
                "forbiddenProjectIds": project.get("forbiddenProjectIds"),
            },
            [
                "project identity is dedicated to staging",
                "billing responsibility and monthly KRW budget are confirmed",
                "forbidden production project IDs remain excluded",
            ],
            "Do not automatically delete a project; disconnect or suspend only under a separate rollback approval.",
        ),
        _stage(
            "api-baseline",
            "Required API baseline",
            "Review the exact Google Cloud and Firebase APIs required by the staging design.",
            ["project-billing"],
            [
                "serviceusage.googleapis.com",
                "cloudbilling.googleapis.com",
                "firebase.googleapis.com",
                "firestore.googleapis.com",
                "firebasestorage.googleapis.com",
                "run.googleapis.com",
                "cloudtasks.googleapis.com",
                "artifactregistry.googleapis.com",
                "secretmanager.googleapis.com",
                "iam.googleapis.com",
                "iamcredentials.googleapis.com",
            ],
            [
                "approved API allowlist is recorded",
                "no unrelated API is included",
                "API enablement remains separately mutation-approved",
            ],
            "Record the previous enabled-API set before any later execution; disabling APIs requires separate impact review.",
        ),
        _stage(
            "firebase-foundation",
            "Firebase foundation",
            "Prepare Auth, Firestore, Storage, and Hosting metadata for the dedicated staging project.",
            ["api-baseline"],
            {
                "projectId": project.get("id"),
                "authDomain": firebase.get("authDomain"),
                "authorizedDomains": firebase.get("authorizedDomains"),
                "firestoreLocation": firebase.get("firestoreLocation"),
                "storageBucket": firebase.get("storageBucket"),
                "storageLocation": firebase.get("storageLocation"),
                "hostingSite": firebase.get("hostingSite"),
            },
            [
                "all Firebase resources belong to the staging project",
                "data locations match asia-northeast3",
                "actual Firebase identifiers are captured after preparation",
            ],
            "Do not delete Firestore or Storage automatically; block traffic and preserve evidence under a separate rollback decision.",
        ),
        _stage(
            "service-accounts",
            "Dedicated service accounts",
            "Prepare distinct service identities for Collaboration, Document API, Document Worker, and Cloud Tasks.",
            ["api-baseline"],
            {
                "collaboration": _mapping(cloud_run, "collaboration", "manifest.cloudRun").get("serviceAccount"),
                "documentApi": _mapping(cloud_run, "documentApi", "manifest.cloudRun").get("serviceAccount"),
                "documentWorker": _mapping(cloud_run, "documentWorker", "manifest.cloudRun").get("serviceAccount"),
                "tasksCaller": tasks.get("callerServiceAccount"),
            },
            [
                "each workload has a dedicated identity",
                "no service-account key file is created",
                "Workload Identity and runtime identity boundaries are documented",
            ],
            "Disable a compromised service identity only after workload impact and recovery identity are approved.",
        ),
        _stage(
            "artifact-registry",
            "Artifact Registry boundary",
            "Prepare the staging-only container repository before image build and digest capture.",
            ["api-baseline"],
            {
                "repository": artifact_registry.get("repository"),
                "location": artifact_registry.get("location"),
            },
            [
                "repository is staging-only",
                "location matches asia-northeast3",
                "mutable latest tags are not accepted for deployment approval",
            ],
            "Retain immutable image digests required for rollback; repository deletion is not automatic.",
        ),
        _stage(
            "secret-metadata",
            "Secret metadata boundary",
            "Prepare secret names and access policy metadata without storing or rendering secret values.",
            ["api-baseline", "service-accounts"],
            {
                key: {
                    "name": _mapping(secrets, key, "manifest.secrets").get("name"),
                    "versionReference": _mapping(secrets, key, "manifest.secrets").get("version"),
                    "valueIncluded": False,
                }
                for key in sorted(secrets)
            },
            [
                "only secret names and version references are reviewed",
                "no secret value appears in artifacts",
                "access principals match the least-privilege IAM plan",
            ],
            "Revoke access before disabling a secret version; never print or export the secret value during rollback.",
        ),
        _stage(
            "iam-bindings",
            "Least-privilege IAM bindings",
            "Review the exact principal, role, and resource bindings from the staging manifest.",
            ["firebase-foundation", "service-accounts", "secret-metadata"],
            iam.get("bindings"),
            [
                "roles/owner and roles/editor are absent",
                "each binding is scoped to the narrowest available resource",
                "actual IAM diff is captured by later live read-only preflight",
            ],
            "Record every pre-existing binding; removal or restoration must be reviewed binding by binding.",
        ),
        _stage(
            "budget-guardrails",
            "Budget and notification guardrails",
            "Prepare the approved KRW monthly budget and notification thresholds.",
            ["project-billing"],
            {
                "currency": budget.get("currency"),
                "amount": budget.get("amount"),
                "thresholds": budget.get("thresholds"),
                "notificationChannels": budget.get("notificationChannels"),
            },
            [
                "currency remains KRW",
                "monthly amount matches the approved decision",
                "50%, 80%, and 100% notifications have accountable recipients",
            ],
            "Budget changes require a new approval reference; removing alerts is never an automatic rollback step.",
        ),
        _stage(
            "cloud-run-prerequisites",
            "Cloud Run deployment prerequisites",
            "Review service names, runtime limits, ingress, and identities while image digests remain blocked for deployment approval.",
            ["service-accounts", "artifact-registry", "secret-metadata", "iam-bindings"],
            {
                key: {
                    "name": _mapping(cloud_run, key, "manifest.cloudRun").get("name"),
                    "serviceAccount": _mapping(cloud_run, key, "manifest.cloudRun").get("serviceAccount"),
                    "ingress": _mapping(cloud_run, key, "manifest.cloudRun").get("ingress"),
                    "runtime": _mapping(cloud_run, key, "manifest.cloudRun").get("runtime"),
                    "state": "blocked-pending-image-digest",
                }
                for key in ("collaboration", "documentApi", "documentWorker")
            },
            [
                "runtime contracts match repository templates",
                "image and digest values remain deferred to image-build approval",
                "no Cloud Run deployment is authorized by this plan",
            ],
            "A later deployment rollback uses reviewed immutable revision IDs; no revision change occurs in this phase.",
        ),
        _stage(
            "cloud-tasks-prerequisites",
            "Cloud Tasks queue prerequisites",
            "Review queue retry, rate, deadline, caller identity, and deferred worker target URLs.",
            ["service-accounts", "cloud-run-prerequisites"],
            {
                "callerServiceAccount": tasks.get("callerServiceAccount"),
                "parse": _mapping(tasks, "parse", "manifest.tasks"),
                "export": _mapping(tasks, "export", "manifest.tasks"),
                "state": "blocked-pending-worker-url",
            },
            [
                "dispatch deadline remains 900 seconds",
                "retry and rate limits match the manifest",
                "target URLs remain deferred until the worker service has an approved URL",
            ],
            "Pause queue dispatch before changing queue configuration; deleting queues requires separate approval.",
        ),
        _stage(
            "post-bootstrap-evidence",
            "Post-bootstrap evidence capture",
            "Capture actual identifiers required to materialize the deployment manifest and run live read-only preflight.",
            [
                "firebase-foundation",
                "service-accounts",
                "artifact-registry",
                "secret-metadata",
                "iam-bindings",
                "budget-guardrails",
            ],
            required_values,
            [
                "every resource-derived identifier has provenance",
                "actual identifiers are compared to the approved names",
                "deployment remains blocked until all placeholders are resolved",
            ],
            "Evidence collection is read-only; discrepancies stop the lifecycle instead of triggering corrective mutation.",
        ),
    ]

    plan: dict[str, Any] = {
        "schemaVersion": INFRASTRUCTURE_PLAN_SCHEMA,
        "status": "ready-for-infrastructure-approval",
        "generatedAt": approval.get("approvedAt"),
        "projectId": project.get("id"),
        "billingAccount": project.get("billingAccount"),
        "region": project.get("region"),
        "approvalReference": operations.get("approvalReference"),
        "sourceEvidence": {
            "commitSha": approval.get("commitSha"),
            "workflowRunId": approval.get("workflowRunId"),
            "packetSha256": packet_sha256,
            "bootstrapApprovalSchema": approval.get("schemaVersion"),
            "bootstrapPacketSchema": packet.get("schemaVersion"),
        },
        "approvalBoundary": {
            "bootstrapPacketReviewed": True,
            "infrastructureMutationApproved": False,
            "deploymentApproved": False,
            "separateInfrastructureApprovalRequired": True,
        },
        "stages": stages,
        "postBootstrapRequiredValues": required_values,
        "rollback": [
            {
                "id": "stop-before-mutation",
                "description": "Any evidence mismatch stops execution before resource changes.",
            },
            {
                "id": "preserve-data",
                "description": "Firestore, Storage, and secret evidence are never automatically deleted.",
            },
            {
                "id": "restore-iam-explicitly",
                "description": "IAM rollback is reviewed binding by binding against captured prior state.",
            },
            {
                "id": "separate-deployment-rollback",
                "description": "Cloud Run revision rollback is defined only after immutable revisions exist.",
            },
        ],
        "security": {
            "readOnlyGenerator": True,
            "containsCloudMutationCommands": False,
            "mutationCommands": [],
            "secretValuesIncluded": False,
            "cloudCliInvoked": False,
        },
    }
    safe_plan = redact_sensitive(plan)
    safe_security = _mapping(safe_plan, "security", "plan")
    safe_security["secretValuesIncluded"] = False
    return safe_plan


def render_markdown(plan: dict[str, Any]) -> str:
    safe = redact_sensitive(plan)
    if safe.get("schemaVersion") != INFRASTRUCTURE_PLAN_SCHEMA:
        raise InfrastructurePlanError(
            f"plan schemaVersion must be {INFRASTRUCTURE_PLAN_SCHEMA}"
        )
    lines = [
        "# rhwp Staging Infrastructure Bootstrap Plan",
        "",
        "> This plan is review evidence only and does not authorize cloud mutation or deployment.",
        "",
        f"- Status: `{_md(safe.get('status'))}`",
        f"- Project ID: `{_md(safe.get('projectId'))}`",
        f"- Billing account: `{_md(safe.get('billingAccount'))}`",
        f"- Region: `{_md(safe.get('region'))}`",
        f"- Approval reference: `{_md(safe.get('approvalReference'))}`",
        f"- Bootstrap packet SHA-256: `{_md(_mapping(safe, 'sourceEvidence', 'plan').get('packetSha256'))}`",
        "",
        "## Approval boundary",
        "",
        "- Bootstrap packet reviewed: yes",
        "- Infrastructure mutation approved: **no**",
        "- Deployment approved: **no**",
        "- A separate infrastructure approval record is required before any resource change.",
        "",
        "## Ordered stages",
        "",
        "| Order | Stage | Depends on | Mutation approval required |",
        "|---:|---|---|---|",
    ]
    stages = safe.get("stages")
    if not isinstance(stages, list):
        raise InfrastructurePlanError("plan stages must be an array")
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            raise InfrastructurePlanError("plan stage must be an object")
        dependencies = stage.get("dependsOn")
        dependency_text = ", ".join(dependencies) if isinstance(dependencies, list) else ""
        lines.append(
            f"| {index} | `{_md(stage.get('id'))}` — {_md(stage.get('title'))} | "
            f"{_md(dependency_text or 'none')} | yes |"
        )
    lines.extend(["", "## Stage details", ""])
    for stage in stages:
        lines.extend([
            f"### {_md(stage.get('id'))}: {_md(stage.get('title'))}",
            "",
            _md(stage.get("intent")),
            "",
            "Acceptance evidence:",
            "",
        ])
        evidence = stage.get("acceptanceEvidence")
        if isinstance(evidence, list):
            for item in evidence:
                lines.append(f"- {_md(item)}")
        lines.extend([
            "",
            f"Rollback boundary: {_md(stage.get('rollbackBoundary'))}",
            "",
        ])
    lines.extend([
        "## Required values before deployment approval",
        "",
        "| Path | Resolution phase | Reason |",
        "|---|---|---|",
    ])
    required_values = safe.get("postBootstrapRequiredValues")
    if isinstance(required_values, list):
        for entry in required_values:
            if isinstance(entry, dict):
                lines.append(
                    f"| `{_md(entry.get('path'))}` | `{_md(entry.get('resolutionPhase'))}` | "
                    f"{_md(entry.get('reason'))} |"
                )
    lines.extend([
        "",
        "## Security",
        "",
        "- Generator is read-only.",
        "- Cloud CLI invocation: no.",
        "- Secret values included: no.",
        "- Mutation commands: none.",
        "- This plan must be reviewed and bound to a separate infrastructure approval record.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a non-mutating rhwp staging infrastructure bootstrap plan"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bootstrap-packet", type=Path, required=True)
    parser.add_argument("--bootstrap-approval-record", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)

    json_temp = args.json_output.with_name(args.json_output.name + ".tmp")
    markdown_temp = args.markdown_output.with_name(args.markdown_output.name + ".tmp")
    try:
        manifest = load_json_object(args.manifest, "staging manifest")
        packet_bytes = args.bootstrap_packet.read_bytes()
        try:
            packet = json.loads(packet_bytes)
        except json.JSONDecodeError as error:
            raise InfrastructurePlanError(
                f"bootstrap packet is not valid JSON: {error}"
            ) from error
        if not isinstance(packet, dict):
            raise InfrastructurePlanError("bootstrap packet root must be an object")
        approval = load_json_object(
            args.bootstrap_approval_record,
            "bootstrap approval record",
        )
        packet_sha256 = hashlib.sha256(packet_bytes).hexdigest()
        plan = build_infrastructure_plan(
            manifest,
            packet,
            approval,
            packet_sha256,
        )
        markdown = render_markdown(plan)
        json_content = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        json_temp.write_text(json_content)
        markdown_temp.write_text(markdown)
        json_temp.replace(args.json_output)
        markdown_temp.replace(args.markdown_output)
    except (InfrastructurePlanError, OSError) as error:
        for path in (json_temp, markdown_temp):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"staging infrastructure plan failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": plan["status"],
        "projectId": plan["projectId"],
        "jsonOutput": str(args.json_output),
        "markdownOutput": str(args.markdown_output),
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        if "-----BEGIN PRIVATE KEY-----" in value or value.startswith("Bearer "):
            return "[REDACTED]"
    return value


def _post_bootstrap_required_values(packet: dict[str, Any]) -> list[dict[str, str]]:
    deferred = packet.get("deferredValues")
    if not isinstance(deferred, list):
        raise InfrastructurePlanError("bootstrap packet deferredValues must be an array")
    result: list[dict[str, str]] = []
    for entry in deferred:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise InfrastructurePlanError("bootstrap packet deferred value must contain a path")
        path = entry["path"]
        if path.startswith("manifest.project.") or path.startswith("manifest.firebase."):
            phase = "infrastructure-bootstrap"
        elif path.startswith("manifest.cloudRun."):
            phase = "image-build"
        else:
            phase = "initial-deployment"
        result.append({
            "path": path,
            "resolutionPhase": phase,
            "reason": str(entry.get("reason") or "resource-derived value must be captured from approved evidence"),
        })
    return sorted(result, key=lambda item: item["path"])


def _stage(
    stage_id: str,
    title: str,
    intent: str,
    depends_on: list[str],
    resources: Any,
    acceptance_evidence: list[str],
    rollback_boundary: str,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "title": title,
        "intent": intent,
        "dependsOn": depends_on,
        "resources": resources,
        "acceptanceEvidence": acceptance_evidence,
        "rollbackBoundary": rollback_boundary,
        "mutationApprovalRequired": True,
    }


def _require_exact_keys(value: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    actual = set(value)
    unknown = sorted(actual - allowed)
    missing = sorted(allowed - actual)
    if unknown:
        raise InfrastructurePlanError(
            f"unknown keys are not allowed in {label}: " + ", ".join(unknown)
        )
    if missing:
        raise InfrastructurePlanError(
            f"missing required keys in {label}: " + ", ".join(missing)
        )


def _mapping(value: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise InfrastructurePlanError(f"{label}.{key} must be an object")
    return item


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise InfrastructurePlanError(f"{label}.{key} must be a non-empty string")
    return item.strip()


def _non_empty_string_list(value: dict[str, Any], key: str, label: str) -> list[str]:
    return _string_list(value, key, label, allow_empty=False)


def _string_list(
    value: dict[str, Any],
    key: str,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or (not allow_empty and not item):
        requirement = "an array" if allow_empty else "a non-empty array"
        raise InfrastructurePlanError(f"{label}.{key} must be {requirement} of strings")
    if not all(isinstance(entry, str) and entry.strip() for entry in item):
        raise InfrastructurePlanError(f"{label}.{key} must contain only non-empty strings")
    return [entry.strip() for entry in item]


def _find_sensitive_key_paths(value: Any, path: str) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            child = f"{path}.{key}"
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                result.append(child)
            result.extend(_find_sensitive_key_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_find_sensitive_key_paths(item, f"{path}[{index}]"))
    return result


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("`", "'").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
