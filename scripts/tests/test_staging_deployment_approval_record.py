from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from scripts.staging_deployment_approval_record import (
    ACK_KEYS,
    DeploymentApprovalError,
    build_approval_record,
    canonical_sha256,
    packet_sha256,
    validate_deployment_packet,
)


def packet() -> dict[str, Any]:
    services = {}
    for key in ("collaboration", "documentApi", "documentWorker"):
        services[key] = {
            "name": f"rhwp-{key}-staging",
            "image": f"asia-northeast3-docker.pkg.dev/rhwp-collaboration-staging-001/rhwp-staging/{key}",
            "digest": ("a" if key == "collaboration" else "b" if key == "documentApi" else "c") * 64,
            "serviceAccount": f"rhwp-{key}-staging@rhwp-collaboration-staging-001.iam.gserviceaccount.com",
            "ingress": "internal" if key == "documentWorker" else "all",
            "reachability": "internal-only" if key == "documentWorker" else "internet-reachable-application-auth-required",
            "runtime": {"timeoutSeconds": 900},
        }
    return {
        "schemaVersion": "rhwp.staging-approval-packet/v1",
        "phase": "deployment",
        "generatedAt": "2026-08-02T00:00:00Z",
        "status": "ready-for-deployment-approval",
        "deferredValues": [],
        "approval": {
            "reference": "staging-bootstrap-approval-2026-07-27-001",
            "cloudMutationApproved": False,
            "packetIsDeploymentApproval": False,
        },
        "project": {
            "id": "rhwp-collaboration-staging-001",
            "number": "598693744358",
            "billingAccount": "0156C9-F378D3-43F511",
            "region": "asia-northeast3",
            "forbiddenProjectIds": ["stellar-builder-503701-b2"],
        },
        "firebase": {},
        "budget": {},
        "iamDiff": [{
            "principal": "serviceAccount:rhwp-document-api-staging@rhwp-collaboration-staging-001.iam.gserviceaccount.com",
            "role": "roles/datastore.user",
            "resource": "project",
            "state": "missing",
            "plannedAction": "grant-after-approval",
        }],
        "secrets": {},
        "cloudRun": services,
        "cloudTasks": {},
        "internalFlush": {},
        "rollback": {
            "deploymentStage": "initial",
            "revisionIds": [None, None, None],
            "dataRetentionDays": 14,
            "automaticDeletionAllowed": False,
        },
        "acceptanceTests": [
            {"id": "auth-acl", "name": "Auth", "expected": "ACL", "status": "pending"},
            {"id": "upload", "name": "Upload", "expected": "HWP", "status": "pending"},
        ],
        "preflight": {
            "comparisonMode": "live",
            "static": {"status": "pass"},
            "live": {"status": "pass", "cloudQueryCount": 12},
        },
        "security": {
            "readOnly": True,
            "containsCloudMutationCommands": False,
            "mutationCommands": [],
            "redactionApplied": True,
        },
    }


def raw(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def evidence(value: dict[str, Any], kind: str, digest: str, status: str) -> dict[str, Any]:
    data: dict[str, Any]
    if kind == "acceptance":
        data = {"testStatuses": [{"id": item["id"], "status": status} for item in value["acceptanceTests"]]}
    else:
        data = {"deploymentStage": "initial", "revisionIds": [None, None, None]}
    return {
        "schemaVersion": "rhwp.staging-deployment-evidence/v1",
        "evidenceKind": kind,
        "status": status if kind == "acceptance" else "not-applicable-initial",
        "sourceCommitSha": "d" * 40,
        "workflowRunId": 123,
        "workflowRunAttempt": 1,
        "packetSha256": digest,
        "observedAt": "2026-08-02T00:00:00Z",
        "data": data,
        "mutationCommands": [],
        "redactionApplied": True,
    }


def review(value: dict[str, Any], digest: str, acceptance_digest: str, rollback_digest: str, *, approved: bool = False, authorize: bool = False) -> dict[str, Any]:
    ack = {key: approved for key in ACK_KEYS}
    return {
        "schemaVersion": "rhwp.staging-deployment-packet-review/v1",
        "decision": "approved" if approved else "pending",
        "approvedAt": "2026-08-02T00:00:00Z" if approved else None,
        "approvedBy": ["synthetic-reviewer"] if approved else [],
        "commitSha": "d" * 40,
        "workflowRunId": 123,
        "workflowRunAttempt": 1,
        "artifactName": "staging-approval-packet-deployment",
        "expectedPacketSha256": digest,
        "expectedApprovalReference": value["approval"]["reference"],
        "expectedIamDiffSha256": canonical_sha256(value["iamDiff"]),
        "acceptanceEvidenceSha256": acceptance_digest,
        "rollbackEvidenceSha256": rollback_digest,
        "acknowledgements": ack,
        "deploymentApproved": authorize,
        "cloudMutationApproved": authorize,
        "notes": ["synthetic fixture"],
    }


class DeploymentApprovalRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = packet()
        self.raw = raw(self.packet)
        self.digest = packet_sha256(self.raw)
        self.acceptance = evidence(self.packet, "acceptance", self.digest, "pending")
        self.rollback = evidence(self.packet, "rollback", self.digest, "pending")
        self.acceptance_digest = canonical_sha256(self.acceptance)
        self.rollback_digest = canonical_sha256(self.rollback)

    def test_accepts_safe_deployment_packet(self) -> None:
        validate_deployment_packet(self.packet)

    def test_packet_hash_is_exact_bytes_not_reserialized(self) -> None:
        compact = json.dumps(self.packet, separators=(",", ":")).encode("utf-8")
        self.assertEqual(self.digest, hashlib.sha256(self.raw).hexdigest())
        self.assertNotEqual(self.digest, packet_sha256(compact))

    def test_pending_record_never_grants_authority(self) -> None:
        record = build_approval_record(self.packet, self.raw, review(self.packet, self.digest, self.acceptance_digest, self.rollback_digest), self.acceptance, self.rollback)
        self.assertEqual(record["decision"], "pending")
        self.assertFalse(record["deploymentApproved"])
        self.assertFalse(record["cloudMutationApproved"])
        self.assertEqual(record["mutationCommands"], [])
        self.assertEqual(record["rollbackEvidence"]["status"], "not-applicable-initial")

    def test_approved_record_requires_all_acknowledgements(self) -> None:
        candidate = review(self.packet, self.digest, self.acceptance_digest, self.rollback_digest, approved=True, authorize=True)
        candidate["acknowledgements"]["rollbackEvidenceReviewed"] = False
        with self.assertRaisesRegex(DeploymentApprovalError, "acknowledgement"):
            build_approval_record(self.packet, self.raw, candidate, self.acceptance, self.rollback)

    def test_explicit_approved_initial_record_can_authorize_workflow(self) -> None:
        candidate = review(self.packet, self.digest, self.acceptance_digest, self.rollback_digest, approved=True, authorize=True)
        record = build_approval_record(self.packet, self.raw, candidate, self.acceptance, self.rollback)
        self.assertTrue(record["deploymentApproved"])
        self.assertTrue(record["cloudMutationApproved"])
        self.assertEqual(record["acceptedIamDiffSha256"], canonical_sha256(self.packet["iamDiff"]))

    def test_wrong_packet_digest_is_fail_closed(self) -> None:
        candidate = review(self.packet, "0" * 64, self.acceptance_digest, self.rollback_digest)
        with self.assertRaisesRegex(DeploymentApprovalError, "exact packet bytes"):
            build_approval_record(self.packet, self.raw, candidate, self.acceptance, self.rollback)

    def test_evidence_source_run_binding_must_match_review(self) -> None:
        mismatched = copy.deepcopy(self.acceptance)
        mismatched["workflowRunAttempt"] = 2
        with self.assertRaisesRegex(DeploymentApprovalError, "source/run binding"):
            build_approval_record(self.packet, self.raw, review(self.packet, self.digest, canonical_sha256(mismatched), self.rollback_digest), mismatched, self.rollback)

    def test_packet_mutation_and_sensitive_key_are_rejected(self) -> None:
        mutated = copy.deepcopy(self.packet)
        mutated["security"]["mutationCommands"] = ["gcloud run deploy"]
        with self.assertRaisesRegex(DeploymentApprovalError, "mutationCommands"):
            validate_deployment_packet(mutated)
        sensitive = copy.deepcopy(self.packet)
        sensitive["internalFlush"]["internalFlushToken"] = "never"
        with self.assertRaisesRegex(DeploymentApprovalError, "sensitive key"):
            validate_deployment_packet(sensitive)

    def test_acceptance_evidence_ids_must_match_packet(self) -> None:
        bad = copy.deepcopy(self.acceptance)
        bad["data"]["testStatuses"][0]["id"] = "different"
        candidate = review(self.packet, self.digest, canonical_sha256(bad), self.rollback_digest)
        with self.assertRaisesRegex(DeploymentApprovalError, "test IDs"):
            build_approval_record(self.packet, self.raw, candidate, bad, self.rollback)

    def test_upgrade_requires_concrete_rollback_revisions(self) -> None:
        upgraded = copy.deepcopy(self.packet)
        upgraded["rollback"] = {
            "deploymentStage": "upgrade",
            "revisionIds": ["collab-1", "api-1", "worker-1"],
            "dataRetentionDays": 14,
            "automaticDeletionAllowed": False,
        }
        with self.assertRaisesRegex(DeploymentApprovalError, "upgrade packet rollback"):
            validate_deployment_packet({**upgraded, "rollback": {**upgraded["rollback"], "revisionIds": [None, None, None]}})


if __name__ == "__main__":
    unittest.main()
