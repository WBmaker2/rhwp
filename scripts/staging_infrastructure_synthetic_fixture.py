"""Tracked, non-secret synthetic evidence used by the apply-review workflow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.staging_approval_packet import build_approval_packet
from scripts.staging_bootstrap_materializer import materialize_bootstrap_manifest
from scripts.staging_infrastructure_approval import validate_infrastructure_approval
from scripts.staging_infrastructure_plan import build_infrastructure_plan

ROOT = Path(__file__).resolve().parents[1]


def canonical_plan_and_approval() -> tuple[dict[str, Any], dict[str, Any], bytes]:
    manifest = materialize_bootstrap_manifest(
        json.loads((ROOT / "deploy/staging/staging-manifest.json").read_text()),
        _bootstrap_values(),
    )
    static_report = {
        "schemaVersion": "rhwp.preflight-report/v1",
        "mode": "static",
        "status": "pass",
        "projectId": manifest["project"]["id"],
        "cloudQueries": [],
        "mutationCommands": [],
    }
    packet = build_approval_packet(manifest, static_report, phase="bootstrap")
    packet_text = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
    packet_digest = hashlib.sha256(packet_text.encode()).hexdigest()
    bootstrap_approval = {
        "schemaVersion": "rhwp.staging-bootstrap-approval/v1",
        "decision": "approved",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": "1" * 40,
        "workflowRunId": 30202041336,
        "packetSha256": packet_digest,
        "projectId": packet["project"]["id"],
        "billingAccount": packet["project"]["billingAccount"],
        "acceptedDeferredPaths": sorted(
            entry["path"] for entry in packet["deferredValues"]
        ),
        "securityExceptions": ["mvp-staging-internal-token"],
        "deploymentApproved": False,
        "cloudMutationApproved": False,
    }
    plan = build_infrastructure_plan(
        manifest, packet, bootstrap_approval, packet_digest
    )
    raw = (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode()
    approval = {
        "schemaVersion": "rhwp.staging-infrastructure-approval/v1",
        "decision": "approved",
        "approvedAt": "2026-07-27T00:00:00Z",
        "approvedBy": ["repository-owner"],
        "commitSha": plan["sourceEvidence"]["commitSha"],
        "planSha256": hashlib.sha256(raw).hexdigest(),
        "projectId": plan["projectId"],
        "billingAccount": plan["billingAccount"],
        "approvedStageIds": [stage["id"] for stage in plan["stages"]],
        "maximumMonthlyBudgetKrw": next(
            stage["resources"]["amount"]
            for stage in plan["stages"]
            if stage["id"] == "budget-guardrails"
        ),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "rollbackReviewed": True,
    }
    return plan, validate_infrastructure_approval(
        plan, raw, approval, require_cloud_mutation=False
    ), raw


def _bootstrap_values() -> dict[str, Any]:
    return {
        "schemaVersion": "rhwp.staging-bootstrap-values/v1",
        "project": {
            "id": "rhwp-collaboration-staging-123",
            "billingAccount": "000000-111111-222222",
            "forbiddenProjectIds": ["rhwp-production"],
        },
        "firebase": {"storageBucket": "rhwp-collaboration-staging-123.firebasestorage.app"},
        "budget": {
            "amountKrw": 50000,
            "notificationChannels": ["billing-admins@example.com"],
        },
        "operations": {
            "dataRetentionDays": 14,
            "approvalReference": "approval-2026-07-26-001",
            "internalFlushSecurityDecision": "mvp-staging-internal-token",
        },
    }
