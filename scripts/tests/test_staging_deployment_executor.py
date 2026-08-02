from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.staging_deployment_approval_record import build_approval_record, canonical_sha256, packet_sha256
from scripts.staging_deployment_executor import (
    DeploymentExecutionError,
    _fixed_argv,
    execute_deployment,
    validate_prepared_bundle,
)
from scripts.staging_deployment_prepare import prepare_bundle
from scripts.staging_deployment_observer import _read_json
from scripts.tests.test_staging_deployment_approval_record import evidence, packet, review


def _deployment_packet() -> dict[str, Any]:
    value = packet()
    project = value["project"]["id"]
    value["firebase"] = {
        "webAppId": "1:598693744358:web:abcdef1234567890",
        "apiKeyReference": "firebase-web-config/staging",
        "storageBucket": "rhwp-collaboration-staging-001.firebasestorage.app",
    }
    value["secrets"] = {"collaborationInternal": {"name": "rhwp-collaboration-internal-token-staging"}}
    value["cloudRun"] = {
        "collaboration": {
            "name": "rhwp-collaboration-staging",
            "image": f"asia-northeast3-docker.pkg.dev/{project}/rhwp-staging/collaboration",
            "digest": "a" * 64,
            "serviceAccount": f"rhwp-collaboration-staging@{project}.iam.gserviceaccount.com",
            "ingress": "all",
            "reachability": "internet-reachable-application-auth-required",
            "runtime": {"containerConcurrency": 80, "cpu": "1", "maxScale": 10, "memory": "1Gi", "minScale": 0, "timeoutSeconds": 3600},
        },
        "documentApi": {
            "name": "rhwp-document-api-staging",
            "image": f"asia-northeast3-docker.pkg.dev/{project}/rhwp-staging/document-api",
            "digest": "b" * 64,
            "serviceAccount": f"rhwp-document-api-staging@{project}.iam.gserviceaccount.com",
            "ingress": "all",
            "reachability": "internet-reachable-application-auth-required",
            "runtime": {"containerConcurrency": 80, "cpu": "1", "maxScale": 20, "memory": "512Mi", "minScale": 0, "timeoutSeconds": 300},
        },
        "documentWorker": {
            "name": "rhwp-document-worker-staging",
            "image": f"asia-northeast3-docker.pkg.dev/{project}/rhwp-staging/document-worker",
            "digest": "c" * 64,
            "serviceAccount": f"rhwp-document-worker-staging@{project}.iam.gserviceaccount.com",
            "ingress": "internal",
            "reachability": "internal-only",
            "runtime": {"containerConcurrency": 1, "cpu": "2", "maxScale": 10, "memory": "2Gi", "minScale": 0, "timeoutSeconds": 900},
        },
    }
    value["cloudTasks"] = {
        "callerServiceAccount": f"rhwp-tasks-staging@{project}.iam.gserviceaccount.com",
        "parse": {"dispatchDeadlineSeconds": 900, "location": "asia-northeast3", "name": "rhwp-parse-staging", "rateLimits": {"maxConcurrentDispatches": 1, "maxDispatchesPerSecond": 1}, "retry": {"maxAttempts": 5, "maxBackoffSeconds": 300, "maxDoublings": 5, "minBackoffSeconds": 10}, "targetUrl": "https://rhwp-document-worker-staging-abc123-uc.a.run.app/run/parse"},
        "export": {"dispatchDeadlineSeconds": 900, "location": "asia-northeast3", "name": "rhwp-export-staging", "rateLimits": {"maxConcurrentDispatches": 1, "maxDispatchesPerSecond": 1}, "retry": {"maxAttempts": 5, "maxBackoffSeconds": 300, "maxDoublings": 5, "minBackoffSeconds": 10}, "targetUrl": "https://rhwp-document-worker-staging-abc123-uc.a.run.app/run/export"},
    }
    s = value["cloudRun"]
    t = value["cloudTasks"]
    value["iamDiff"] = [
        {"principal": f"serviceAccount:{s['collaboration']['serviceAccount']}", "role": "roles/datastore.user", "resource": "project", "state": "missing", "plannedAction": "grant-after-approval"},
        {"principal": f"serviceAccount:{s['collaboration']['serviceAccount']}", "role": "roles/storage.objectAdmin", "resource": "bucket:rhwp-collaboration-staging-001.firebasestorage.app", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['collaboration']['serviceAccount']}", "role": "roles/secretmanager.secretAccessor", "resource": "secret:rhwp-collaboration-internal-token-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['documentApi']['serviceAccount']}", "role": "roles/datastore.user", "resource": "project", "state": "missing", "plannedAction": "grant-after-approval"},
        {"principal": f"serviceAccount:{s['documentApi']['serviceAccount']}", "role": "roles/storage.objectViewer", "resource": "bucket:rhwp-collaboration-staging-001.firebasestorage.app", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['documentApi']['serviceAccount']}", "role": "roles/cloudtasks.enqueuer", "resource": "queues:rhwp-parse-staging,rhwp-export-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['documentApi']['serviceAccount']}", "role": "roles/iam.serviceAccountUser", "resource": f"serviceAccount:{t['callerServiceAccount']}", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['documentApi']['serviceAccount']}", "role": "roles/secretmanager.secretAccessor", "resource": "secret:rhwp-collaboration-internal-token-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{s['documentWorker']['serviceAccount']}", "role": "roles/datastore.user", "resource": "project", "state": "missing", "plannedAction": "grant-after-approval"},
        {"principal": f"serviceAccount:{s['documentWorker']['serviceAccount']}", "role": "roles/storage.objectAdmin", "resource": "bucket:rhwp-collaboration-staging-001.firebasestorage.app", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": "allUsers", "role": "roles/run.invoker", "resource": "cloudRun:rhwp-collaboration-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": "allUsers", "role": "roles/run.invoker", "resource": "cloudRun:rhwp-document-api-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
        {"principal": f"serviceAccount:{t['callerServiceAccount']}", "role": "roles/run.invoker", "resource": "cloudRun:rhwp-document-worker-staging", "state": "not-observed", "plannedAction": "verify-before-grant"},
    ]
    return value


class StagingDeploymentExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "bundle"
        self.root.mkdir()
        packet_value = _deployment_packet()
        packet_raw = (json.dumps(packet_value, ensure_ascii=False, indent=2) + "\n").encode()
        digest = packet_sha256(packet_raw)
        acceptance = evidence(packet_value, "acceptance", digest, "pending")
        rollback = evidence(packet_value, "rollback", digest, "pending")
        approved_review = review(packet_value, digest, canonical_sha256(acceptance), canonical_sha256(rollback), approved=True, authorize=True)
        record = build_approval_record(packet_value, packet_raw, approved_review, acceptance, rollback)
        paths = {
            "packet": self.root / "staging-approval-packet.json",
            "review": self.root / "deployment-review.approved.json",
            "acceptance": self.root / "acceptance-evidence.json",
            "rollback": self.root / "rollback-evidence.json",
            "record": self.root / "staging-deployment-approval-record.json",
        }
        paths["packet"].write_bytes(packet_raw)
        for key, value in (("review", approved_review), ("acceptance", acceptance), ("rollback", rollback), ("record", record)):
            paths[key].write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prepared, exact = prepare_bundle(
            packet_path=paths["packet"], review_path=paths["review"], acceptance_path=paths["acceptance"], rollback_path=paths["rollback"], record_path=paths["record"],
            expected_source_commit="d" * 40, expected_workflow_run_id=123, expected_workflow_run_attempt=1,
            expected_artifact_name="staging-approval-packet-deployment", expected_artifact_digest="sha256:" + "a" * 64, expected_packet_sha256=digest,
        )
        (self.root / "deployment-input.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name, raw in exact.items():
            (self.root / name).write_bytes(raw)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validates_canonical_actions_and_splits_queue_binding(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        self.assertEqual(prepared["mutationCommands"], [])
        self.assertEqual(len(actions), 19)  # 3 services + 2 queues + 13 diff entries, one queue entry split
        self.assertEqual(actions[0]["actionId"], "cloud-run-collaboration")
        self.assertEqual(actions[5]["actionId"], "iam-binding-01")
        self.assertEqual(actions[10]["actionId"], "iam-binding-06-rhwp-parse-staging")
        self.assertNotIn(",", actions[10]["resource"]["resource"])

    def test_dry_run_writes_no_commands(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        plan = Path(self.temp.name) / "plan.json"
        post = Path(self.temp.name) / "post.json"
        result = execute_deployment(prepared, actions, plan, post)
        self.assertEqual(result["status"], "dry-run-complete")
        self.assertEqual(json.loads(plan.read_text())["mutationCommands"], [])
        self.assertEqual(json.loads(post.read_text())["status"], "dry-run-complete")

    def test_fixed_argv_binds_project_without_template_literals(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        command = _fixed_argv(prepared["project"]["id"], actions[12])
        self.assertIn("--project=rhwp-collaboration-staging-001", command)
        self.assertNotIn("--project={project_id}", command)

    def test_cloud_run_argv_contains_only_runtime_references(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        collaboration = _fixed_argv(prepared["project"]["id"], actions[0], prepared, {})
        self.assertIn("--set-env-vars=FIREBASE_STORAGE_BUCKET=rhwp-collaboration-staging-001.firebasestorage.app", collaboration)
        self.assertIn("--set-secrets=INTERNAL_API_TOKEN=rhwp-collaboration-internal-token-staging:latest", collaboration)
        self.assertNotIn("do-not-print-this", json.dumps(collaboration))

        document_api = _fixed_argv(
            prepared["project"]["id"],
            actions[1],
            prepared,
            {"cloud-run-collaboration": "https://rhwp-collaboration-staging-abc123-uc.a.run.app"},
        )
        self.assertIn("PARSE_WORKER_URL=https://rhwp-document-worker-staging-abc123-uc.a.run.app/run/parse", json.dumps(document_api))
        self.assertIn("COLLABORATION_FLUSH_URL=https://rhwp-collaboration-staging-abc123-uc.a.run.app", json.dumps(document_api))
        self.assertIn("--set-secrets=COLLABORATION_INTERNAL_TOKEN=rhwp-collaboration-internal-token-staging:latest", document_api)

    def test_apply_requires_observer_and_records_each_write(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        with self.assertRaisesRegex(DeploymentExecutionError, "observer"):
            execute_deployment(prepared, actions, Path(self.temp.name) / "p.json", Path(self.temp.name) / "o.json", apply=True)
        states: dict[str, bool] = {}
        argv: list[tuple[str, ...]] = []

        def observer(action: dict[str, Any]) -> dict[str, Any]:
            service_url = None
            if action["resourceKind"] == "cloud-run-service":
                service_url = f"https://{action['resource']['name']}-abc123-uc.a.run.app"
            if states.get(action["actionId"], False):
                result = {"state": "present", "resourceKind": action["resourceKind"], "matchesDesired": True}
            else:
                result = {"state": "missing", "resourceKind": action["resourceKind"], "matchesDesired": False}
            if service_url:
                result["url"] = service_url
            return result

        def runner(command: tuple[str, ...]) -> str:
            argv.append(command)
            states[next(item["actionId"] for item in actions if item["resourceKind"] in command or item["resourceKind"] == "iam-binding")] = True
            # The test only verifies bounded argv construction; production
            # runner binds the action id before invoking the command.
            return "ok"

        # Use an action-aware runner wrapper so each fake postcondition changes
        # exactly the action that was written.
        states.clear()
        current: dict[str, str] = {"id": ""}

        def aware_observer(action: dict[str, Any]) -> dict[str, Any]:
            current["id"] = action["actionId"]
            return observer(action)

        def aware_runner(command: tuple[str, ...]) -> str:
            argv.append(command)
            states[current["id"]] = True
            return "ok"

        result = execute_deployment(prepared, actions, Path(self.temp.name) / "apply-plan.json", Path(self.temp.name) / "apply-post.json", apply=True, observer=aware_observer, runner=aware_runner)
        self.assertEqual(result["status"], "apply-complete")
        self.assertEqual(len(argv), len(actions))
        self.assertTrue(all(command[0:2] == ("gcloud", "run") or command[0:3] == ("gcloud", "tasks", "queues") or command[0:2] == ("gcloud", "projects") or command[0:2] == ("gcloud", "storage") or command[0:2] == ("gcloud", "secrets") or command[0:2] == ("gcloud", "iam") for command in argv))
        self.assertNotIn("Authorization", json.dumps(argv))

    def test_observer_failure_is_fail_closed_with_evidence(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        post = Path(self.temp.name) / "failure.json"

        def observer(_action: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("permission denied")

        with self.assertRaisesRegex(DeploymentExecutionError, "precondition observation"):
            execute_deployment(prepared, actions, Path(self.temp.name) / "p.json", post, apply=True, observer=observer)
        value = json.loads(post.read_text())
        self.assertEqual(value["status"], "failed-first-error")
        self.assertEqual(value["mutationCommands"], [])

    def test_observer_treats_gcloud_cannot_find_service_as_missing(self) -> None:
        completed = subprocess.CompletedProcess(
            args=("gcloud", "run", "services", "describe"),
            returncode=1,
            stdout="",
            stderr="ERROR: (gcloud.run.services.describe) Cannot find service [rhwp-collaboration-staging].",
        )
        with patch("scripts.staging_deployment_observer.subprocess.run", return_value=completed):
            self.assertIsNone(_read_json(("gcloud", "run", "services", "describe")))

    def test_observer_allows_failed_cloud_run_service_to_be_repaired(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        collaboration = actions[0]["resource"]
        failed_service = {
            "metadata": {"name": collaboration["name"]},
            "spec": {
                "ingress": collaboration["ingress"],
                "template": {
                    "metadata": {"annotations": {"autoscaling.knative.dev/minScale": "0", "autoscaling.knative.dev/maxScale": "10"}},
                    "spec": {
                        "serviceAccountName": collaboration["serviceAccount"],
                        "containerConcurrency": 80,
                        "timeoutSeconds": 3600,
                        "containers": [{
                            "image": f"{collaboration['image']}@sha256:{collaboration['digest']}",
                            "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
                            "env": [],
                        }],
                    },
                },
            },
            "status": {
                "url": "https://rhwp-collaboration-staging-abc123-uc.a.run.app",
                "conditions": [{"type": "Ready", "status": "False", "reason": "HealthCheckContainerError"}],
            }
        }
        with patch("scripts.staging_deployment_observer._read_json", return_value=failed_service):
            from scripts.staging_deployment_observer import _observe_cloud_run

            result = _observe_cloud_run(
                prepared["project"]["id"],
                collaboration,
                prepared=prepared,
                observed_urls={},
            )
        self.assertEqual(result["state"], "missing")
        self.assertFalse(result["matchesDesired"])
        self.assertEqual(result["url"], "https://rhwp-collaboration-staging-abc123-uc.a.run.app")

    def test_observer_keeps_failed_service_with_wrong_identity_incompatible(self) -> None:
        prepared, actions = validate_prepared_bundle(self.root)
        wrong_service = {
            "metadata": {"name": actions[0]["resource"]["name"]},
            "spec": {"template": {"spec": {"containers": [{"image": "wrong.example/image@sha256:" + "f" * 64}]}}},
            "status": {"conditions": [{"type": "Ready", "status": "False"}]},
        }
        with patch("scripts.staging_deployment_observer._read_json", return_value=wrong_service):
            from scripts.staging_deployment_observer import _observe_cloud_run

            result = _observe_cloud_run(prepared["project"]["id"], actions[0]["resource"], prepared=prepared, observed_urls={})
        self.assertEqual(result["state"], "incompatible")
        self.assertFalse(result["matchesDesired"])


if __name__ == "__main__":
    unittest.main()
