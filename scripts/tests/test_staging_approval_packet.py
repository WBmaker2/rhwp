from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.staging_approval_packet import (
    ApprovalPacketError,
    build_approval_packet,
    main,
    redact_sensitive,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"


def concrete_manifest() -> dict[str, object]:
    project_id = "rhwp-collaboration-staging-123"
    collaboration_sa = f"rhwp-collaboration-staging@{project_id}.iam.gserviceaccount.com"
    document_api_sa = f"rhwp-document-api-staging@{project_id}.iam.gserviceaccount.com"
    document_worker_sa = f"rhwp-document-worker-staging@{project_id}.iam.gserviceaccount.com"
    tasks_sa = f"rhwp-tasks-staging@{project_id}.iam.gserviceaccount.com"
    bucket = f"{project_id}.firebasestorage.app"
    return {
        "schemaVersion": "rhwp.staging/v1",
        "environment": "staging",
        "project": {
            "id": project_id,
            "number": "123456789012",
            "billingAccount": "000000-111111-222222",
            "region": "asia-northeast3",
            "forbiddenProjectIds": ["rhwp-production"],
        },
        "firebase": {
            "webAppId": "1:123456789012:web:abcdef123456",
            "apiKeyReference": "firebase-web-config/staging",
            "authDomain": f"{project_id}.firebaseapp.com",
            "authorizedDomains": [
                f"{project_id}.firebaseapp.com",
                f"{project_id}.web.app",
            ],
            "firestoreLocation": "asia-northeast3",
            "storageBucket": bucket,
            "storageLocation": "asia-northeast3",
            "hostingSite": project_id,
        },
        "artifactRegistry": {
            "repository": "rhwp-staging",
            "location": "asia-northeast3",
        },
        "cloudRun": {
            "collaboration": {
                "name": "rhwp-collaboration-staging",
                "image": f"asia-northeast3-docker.pkg.dev/{project_id}/rhwp-staging/collaboration",
                "digest": "a" * 64,
                "serviceAccount": collaboration_sa,
                "ingress": "all",
                "runtime": {
                    "containerConcurrency": 80,
                    "timeoutSeconds": 3600,
                    "cpu": "1",
                    "memory": "1Gi",
                    "minScale": 0,
                    "maxScale": 10,
                },
            },
            "documentApi": {
                "name": "rhwp-document-api-staging",
                "image": f"asia-northeast3-docker.pkg.dev/{project_id}/rhwp-staging/document-api",
                "digest": "b" * 64,
                "serviceAccount": document_api_sa,
                "ingress": "all",
                "runtime": {
                    "containerConcurrency": 80,
                    "timeoutSeconds": 300,
                    "cpu": "1",
                    "memory": "512Mi",
                    "minScale": 0,
                    "maxScale": 20,
                },
            },
            "documentWorker": {
                "name": "rhwp-document-worker-staging",
                "image": f"asia-northeast3-docker.pkg.dev/{project_id}/rhwp-staging/document-worker",
                "digest": "c" * 64,
                "serviceAccount": document_worker_sa,
                "ingress": "internal",
                "runtime": {
                    "containerConcurrency": 1,
                    "timeoutSeconds": 900,
                    "cpu": "2",
                    "memory": "2Gi",
                    "minScale": 0,
                    "maxScale": 10,
                },
            },
        },
        "tasks": {
            "callerServiceAccount": tasks_sa,
            "parse": {
                "name": "rhwp-parse-staging",
                "location": "asia-northeast3",
                "targetUrl": "https://worker.example/run/parse",
                "dispatchDeadlineSeconds": 900,
                "retry": {
                    "maxAttempts": 5,
                    "minBackoffSeconds": 10,
                    "maxBackoffSeconds": 300,
                    "maxDoublings": 5,
                },
                "rateLimits": {
                    "maxConcurrentDispatches": 1,
                    "maxDispatchesPerSecond": 1,
                },
            },
            "export": {
                "name": "rhwp-export-staging",
                "location": "asia-northeast3",
                "targetUrl": "https://worker.example/run/export",
                "dispatchDeadlineSeconds": 900,
                "retry": {
                    "maxAttempts": 5,
                    "minBackoffSeconds": 10,
                    "maxBackoffSeconds": 300,
                    "maxDoublings": 5,
                },
                "rateLimits": {
                    "maxConcurrentDispatches": 1,
                    "maxDispatchesPerSecond": 1,
                },
            },
        },
        "secrets": {
            "collaborationInternal": {
                "name": "rhwp-collaboration-internal-token-staging",
                "version": "7",
            }
        },
        "iam": {
            "bindings": [
                {
                    "principal": f"serviceAccount:{collaboration_sa}",
                    "role": "roles/datastore.user",
                    "resource": "project",
                },
                {
                    "principal": f"serviceAccount:{document_api_sa}",
                    "role": "roles/datastore.user",
                    "resource": "project",
                },
                {
                    "principal": f"serviceAccount:{document_api_sa}",
                    "role": "roles/cloudtasks.enqueuer",
                    "resource": "queues:rhwp-parse-staging,rhwp-export-staging",
                },
                {
                    "principal": f"serviceAccount:{tasks_sa}",
                    "role": "roles/run.invoker",
                    "resource": "cloudRun:rhwp-document-worker-staging",
                },
                {
                    "principal": f"serviceAccount:{document_worker_sa}",
                    "role": "roles/storage.objectAdmin",
                    "resource": f"bucket:{bucket}",
                },
                {
                    "principal": f"serviceAccount:{document_api_sa}",
                    "role": "roles/secretmanager.secretAccessor",
                    "resource": "secret:rhwp-collaboration-internal-token-staging",
                },
            ]
        },
        "budget": {
            "currency": "KRW",
            "amount": 50000,
            "thresholds": [0.5, 0.8, 1.0],
            "notificationChannels": ["billing-admins@example.com"],
        },
        "operations": {
            "dataRetentionDays": "14",
            "approvalReference": "approval-2026-07-26-001",
            "rollbackRevisionIds": [
                "collaboration-revision-00001",
                "document-api-revision-00001",
                "document-worker-revision-00001",
            ],
            "internalFlushSecurityDecision": "mvp-staging-internal-token",
            "cloudMutationApproved": False,
        },
    }


def static_report(manifest: dict[str, object]) -> dict[str, object]:
    project = manifest["project"]
    assert isinstance(project, dict)
    return {
        "schemaVersion": "rhwp.preflight-report/v1",
        "generatedAt": "2026-07-26T00:00:00+00:00",
        "mode": "static",
        "status": "pass",
        "manifest": "deploy/staging/staging-manifest.json",
        "environment": "staging",
        "projectId": project["id"],
        "repositoryChecks": ["manifest schema and safety constraints"],
        "cloudQueries": [],
        "mutationCommands": [],
        "plannedChanges": {},
        "warnings": [],
    }


def live_report(manifest: dict[str, object]) -> dict[str, object]:
    project = manifest["project"]
    iam = manifest["iam"]
    assert isinstance(project, dict)
    assert isinstance(iam, dict)
    bindings = iam["bindings"]
    assert isinstance(bindings, list)
    present = bindings[1]
    assert isinstance(present, dict)
    return {
        "schemaVersion": "rhwp.preflight-report/v1",
        "generatedAt": "2026-07-26T00:01:00+00:00",
        "mode": "live",
        "status": "pass",
        "manifest": "deploy/staging/staging-manifest.json",
        "environment": "staging",
        "projectId": project["id"],
        "repositoryChecks": ["manifest schema and safety constraints"],
        "cloudQueries": ["gcloud projects describe rhwp-collaboration-staging-123 --format=json"],
        "mutationCommands": [],
        "plannedChanges": {
            "createOrEnable": {"cloudRun": ["rhwp-document-worker-staging"]},
            "alreadyPresent": {"cloudRun": []},
            "unexpectedManagedResources": {},
        },
        "warnings": [],
        "cloudState": {
            "iamPolicy": {
                "bindings": [
                    {
                        "role": present["role"],
                        "members": [present["principal"]],
                    }
                ]
            },
            "authorization": "Bearer should-never-leak",
            "credential": "credential-should-never-leak",
        },
    }


class ApprovalInputValidationTest(unittest.TestCase):
    def test_rejects_embedded_placeholder_before_packet_generation(self) -> None:
        manifest = concrete_manifest()
        firebase = manifest["firebase"]
        assert isinstance(firebase, dict)
        firebase["authDomain"] = "${FIREBASE_STAGING_PROJECT_ID}.firebaseapp.com"

        with self.assertRaisesRegex(ApprovalPacketError, "unresolved placeholder"):
            build_approval_packet(manifest, static_report(manifest), None)

    def test_rejects_static_report_with_mutation_commands(self) -> None:
        manifest = concrete_manifest()
        report = static_report(manifest)
        report["mutationCommands"] = ["gcloud run deploy forbidden"]

        with self.assertRaisesRegex(ApprovalPacketError, "mutationCommands"):
            build_approval_packet(manifest, report, None)

    def test_rejects_mismatched_live_project(self) -> None:
        manifest = concrete_manifest()
        report = live_report(manifest)
        report["projectId"] = "different-project"

        with self.assertRaisesRegex(ApprovalPacketError, "projectId"):
            build_approval_packet(manifest, static_report(manifest), report)


class ApprovalPacketBuildTest(unittest.TestCase):
    def test_builds_required_review_sections(self) -> None:
        manifest = concrete_manifest()
        packet = build_approval_packet(manifest, static_report(manifest), live_report(manifest))

        for section in (
            "approval",
            "project",
            "firebase",
            "budget",
            "iamDiff",
            "secrets",
            "cloudRun",
            "cloudTasks",
            "internalFlush",
            "rollback",
            "acceptanceTests",
            "preflight",
            "security",
        ):
            self.assertIn(section, packet)

        self.assertEqual(packet["schemaVersion"], "rhwp.staging-approval-packet/v1")
        self.assertEqual(packet["budget"]["currency"], "KRW")
        self.assertEqual(packet["budget"]["amount"], 50000)
        self.assertEqual(packet["cloudRun"]["collaboration"]["reachability"], "internet-reachable-application-auth-required")
        self.assertEqual(packet["cloudRun"]["documentWorker"]["reachability"], "internal-only")
        self.assertEqual(packet["cloudTasks"]["parse"]["dispatchDeadlineSeconds"], 900)
        self.assertEqual(len(packet["acceptanceTests"]), 11)
        self.assertEqual(packet["security"]["mutationCommands"], [])

    def test_computes_conservative_iam_diff(self) -> None:
        manifest = concrete_manifest()
        packet = build_approval_packet(manifest, static_report(manifest), live_report(manifest))
        by_role_and_resource = {
            (entry["role"], entry["resource"], entry["principal"]): entry
            for entry in packet["iamDiff"]
        }
        iam = manifest["iam"]
        assert isinstance(iam, dict)
        bindings = iam["bindings"]
        assert isinstance(bindings, list)

        missing_project = bindings[0]
        present_project = bindings[1]
        resource_level = bindings[2]
        assert isinstance(missing_project, dict)
        assert isinstance(present_project, dict)
        assert isinstance(resource_level, dict)

        self.assertEqual(
            by_role_and_resource[(present_project["role"], present_project["resource"], present_project["principal"])]["state"],
            "present",
        )
        self.assertEqual(
            by_role_and_resource[(missing_project["role"], missing_project["resource"], missing_project["principal"])]["plannedAction"],
            "grant-after-approval",
        )
        self.assertEqual(
            by_role_and_resource[(resource_level["role"], resource_level["resource"], resource_level["principal"])]["state"],
            "not-observed",
        )


class ApprovalPacketRedactionTest(unittest.TestCase):
    def test_redacts_sensitive_keys_and_private_key_values(self) -> None:
        payload = {
            "accessToken": "access-secret",
            "id_token": "id-secret",
            "authorization": "Bearer auth-secret",
            "credential": "credential-secret",
            "privateKey": "-----BEGIN PRIVATE KEY-----\nprivate-secret",
            "secretValue": "secret-value",
            "password": "password-secret",
            "safe": "visible",
        }

        redacted = redact_sensitive(payload)
        serialized = json.dumps(redacted)

        for secret in (
            "access-secret",
            "id-secret",
            "auth-secret",
            "credential-secret",
            "private-secret",
            "secret-value",
            "password-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(redacted["safe"], "visible")

    def test_markdown_is_rendered_from_sanitized_packet(self) -> None:
        manifest = concrete_manifest()
        packet = build_approval_packet(manifest, static_report(manifest), live_report(manifest))
        packet["security"]["authorization"] = "Bearer markdown-secret"

        markdown = render_markdown(packet)

        self.assertNotIn("markdown-secret", markdown)
        for heading in (
            "## Project",
            "## Budget",
            "## IAM diff",
            "## Secret metadata",
            "## Cloud Run",
            "## Cloud Tasks",
            "## Internal flush security",
            "## Rollback",
            "## Acceptance tests",
            "## Preflight evidence",
        ):
            self.assertIn(heading, markdown)
        self.assertIn("contains no cloud mutation commands", markdown)
        self.assertIn("does not itself approve deployment", markdown)


class ApprovalPacketCliTest(unittest.TestCase):
    def test_cli_writes_json_and_markdown_outputs(self) -> None:
        manifest = concrete_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            static_path = root / "static.json"
            live_path = root / "live.json"
            json_output = root / "output/packet.json"
            markdown_output = root / "output/packet.md"
            manifest_path.write_text(json.dumps(manifest))
            static_path.write_text(json.dumps(static_report(manifest)))
            live_path.write_text(json.dumps(live_report(manifest)))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--manifest", str(manifest_path),
                    "--static-report", str(static_path),
                    "--live-report", str(live_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertTrue(json_output.exists())
            self.assertTrue(markdown_output.exists())
            self.assertEqual(json.loads(json_output.read_text())["schemaVersion"], "rhwp.staging-approval-packet/v1")
            self.assertIn('"status": "ready-for-approval"', stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_cli_fails_safely_when_placeholders_remain(self) -> None:
        manifest = concrete_manifest()
        project = manifest["project"]
        assert isinstance(project, dict)
        project["id"] = "${FIREBASE_STAGING_PROJECT_ID}"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            static_path = root / "static.json"
            json_output = root / "packet.json"
            markdown_output = root / "packet.md"
            manifest_path.write_text(json.dumps(manifest))
            static_path.write_text(json.dumps(static_report(manifest)))
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main([
                    "--manifest", str(manifest_path),
                    "--static-report", str(static_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 1)
            self.assertFalse(json_output.exists())
            self.assertFalse(markdown_output.exists())
            self.assertIn("unresolved placeholder", stderr.getvalue())
            self.assertNotIn("credential", stderr.getvalue().lower())


class ApprovalPacketWorkflowTest(unittest.TestCase):
    def test_live_workflow_generates_and_uploads_approval_packet(self) -> None:
        workflow = WORKFLOW_PATH.read_text()

        for marker in (
            "python3 scripts/staging_preflight.py",
            "--report artifacts/staging-preflight-static.json",
            "--report artifacts/staging-preflight-live.json",
            "python3 scripts/staging_approval_packet.py",
            "--static-report artifacts/staging-preflight-static.json",
            "--live-report artifacts/staging-preflight-live.json",
            "--json-output artifacts/staging-approval-packet.json",
            "--markdown-output artifacts/staging-approval-packet.md",
            "staging-approval-packet",
        ):
            self.assertIn(marker, workflow)

        self.assertNotRegex(
            workflow,
            r"(?:gcloud|firebase)[^\n]*(?:\bcreate\b|\bdelete\b|\bdeploy\b|\benable\b|\bdisable\b|\bupdate\b|add-iam-policy-binding|set-iam-policy)",
        )


if __name__ == "__main__":
    unittest.main()
