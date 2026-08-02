from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.staging_deployment_approval_record import (
    build_approval_record,
    canonical_sha256,
    packet_sha256,
)
from scripts.staging_deployment_prepare import DeploymentPrepareError, prepare_bundle
from scripts.tests.test_staging_deployment_approval_record import (
    evidence,
    packet,
    raw,
    review,
)


def deployment_fixture() -> tuple[dict[str, Any], bytes, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    value = packet()
    value["firebase"] = {
        "webAppId": "1:598693744358:web:abcdef1234567890",
        "apiKeyReference": "firebase-web-config/staging",
        "storageBucket": "rhwp-collaboration-staging-001.firebasestorage.app",
    }
    value["cloudTasks"] = {
        "callerServiceAccount": "rhwp-document-api-staging@rhwp-collaboration-staging-001.iam.gserviceaccount.com",
        "parse": {"name": "rhwp-parse-staging", "targetUrl": "https://worker.example/run/parse"},
        "export": {"name": "rhwp-export-staging", "targetUrl": "https://worker.example/run/export"},
    }
    packet_raw = raw(value)
    digest = packet_sha256(packet_raw)
    acceptance = evidence(value, "acceptance", digest, "pending")
    rollback = evidence(value, "rollback", digest, "pending")
    acceptance_digest = canonical_sha256(acceptance)
    rollback_digest = canonical_sha256(rollback)
    approved_review = review(value, digest, acceptance_digest, rollback_digest, approved=True, authorize=True)
    record = build_approval_record(value, packet_raw, approved_review, acceptance, rollback)
    return value, packet_raw, approved_review, acceptance, rollback, record


class StagingDeploymentPrepareTest(unittest.TestCase):
    def setUp(self) -> None:
        self.value, self.packet_raw, self.review, self.acceptance, self.rollback, self.record = deployment_fixture()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = {
            "packet": root / "packet.json",
            "review": root / "review.json",
            "acceptance": root / "acceptance.json",
            "rollback": root / "rollback.json",
            "record": root / "record.json",
        }
        self.paths["packet"].write_bytes(self.packet_raw)
        self.paths["review"].write_text(json.dumps(self.review, indent=2) + "\n", encoding="utf-8")
        self.paths["acceptance"].write_text(json.dumps(self.acceptance, indent=2) + "\n", encoding="utf-8")
        self.paths["rollback"].write_text(json.dumps(self.rollback, indent=2) + "\n", encoding="utf-8")
        self.paths["record"].write_text(json.dumps(self.record, indent=2) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _prepare(self, **overrides: Any) -> tuple[dict[str, Any], dict[str, bytes]]:
        args = {
            "packet_path": self.paths["packet"],
            "review_path": self.paths["review"],
            "acceptance_path": self.paths["acceptance"],
            "rollback_path": self.paths["rollback"],
            "record_path": self.paths["record"],
            "expected_source_commit": "d" * 40,
            "expected_workflow_run_id": 123,
            "expected_workflow_run_attempt": 1,
            "expected_artifact_name": "staging-approval-packet-deployment",
            "expected_artifact_digest": "sha256:" + "a" * 64,
            "expected_packet_sha256": packet_sha256(self.packet_raw),
        }
        args.update(overrides)
        return prepare_bundle(**args)

    def test_prepares_exact_packet_bytes_and_safe_metadata(self) -> None:
        prepared, exact_bytes = self._prepare()
        self.assertEqual(exact_bytes["staging-approval-packet.json"], self.packet_raw)
        self.assertEqual(prepared["packetSha256"], packet_sha256(self.packet_raw))
        self.assertEqual(prepared["approval"]["deploymentApproved"], True)
        self.assertEqual(prepared["mutationCommands"], [])

    def test_source_binding_mismatch_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(DeploymentPrepareError, "binding"):
            self._prepare(expected_source_commit="e" * 40)

    def test_record_mutation_or_mismatch_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.record)
        mutated["mutationCommands"] = ["gcloud run services replace"]
        self.paths["record"].write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentPrepareError, "exactly match"):
            self._prepare()


if __name__ == "__main__":
    unittest.main()
