from __future__ import annotations

import copy
import inspect
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts import staging_approval_packet
from scripts.staging_approval_packet import ApprovalPacketError, build_approval_packet, main, render_markdown
from scripts.tests.test_staging_approval_packet import concrete_manifest, live_report, static_report

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/staging-config-validate.yml"


def bootstrap_manifest() -> dict[str, object]:
    manifest = copy.deepcopy(concrete_manifest())
    project = manifest["project"]
    firebase = manifest["firebase"]
    cloud_run = manifest["cloudRun"]
    operations = manifest["operations"]
    assert isinstance(project, dict)
    assert isinstance(firebase, dict)
    assert isinstance(cloud_run, dict)
    assert isinstance(operations, dict)

    project["number"] = "${GCP_PROJECT_NUMBER}"
    firebase["webAppId"] = "${FIREBASE_WEB_APP_ID}"
    firebase["apiKeyReference"] = "${FIREBASE_WEB_API_KEY_REFERENCE}"
    firebase["storageBucket"] = "${FIREBASE_STORAGE_BUCKET}"
    firebase["hostingSite"] = "${FIREBASE_HOSTING_SITE}"

    image_placeholders = {
        "collaboration": ("${COLLABORATION_IMAGE}", "${COLLABORATION_IMAGE_DIGEST}"),
        "documentApi": ("${DOCUMENT_API_IMAGE}", "${DOCUMENT_API_IMAGE_DIGEST}"),
        "documentWorker": ("${DOCUMENT_WORKER_IMAGE}", "${DOCUMENT_WORKER_IMAGE_DIGEST}"),
    }
    for key, (image, digest) in image_placeholders.items():
        service = cloud_run[key]
        assert isinstance(service, dict)
        service["image"] = image
        service["digest"] = digest

    operations["rollbackRevisionIds"] = [
        "${COLLABORATION_ROLLBACK_REVISION}",
        "${DOCUMENT_API_ROLLBACK_REVISION}",
        "${DOCUMENT_WORKER_ROLLBACK_REVISION}",
    ]
    return manifest


class PhaseTestCase(unittest.TestCase):
    def build_for_phase(
        self,
        manifest: dict[str, object],
        *,
        phase: str,
        live: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if "phase" not in inspect.signature(build_approval_packet).parameters:
            self.fail("build_approval_packet must accept a phase keyword")
        return build_approval_packet(
            manifest,
            static_report(manifest),
            live,
            phase=phase,
        )


class BootstrapPhaseValidationTest(PhaseTestCase):
    def test_bootstrap_allows_only_resource_derived_deferred_values(self) -> None:
        manifest = bootstrap_manifest()

        packet = self.build_for_phase(manifest, phase="bootstrap")

        self.assertEqual(packet["phase"], "bootstrap")
        self.assertEqual(packet["status"], "ready-for-bootstrap-approval")
        deferred = packet["deferredValues"]
        self.assertIsInstance(deferred, list)
        deferred_paths = {entry["path"] for entry in deferred}
        self.assertEqual(deferred_paths, {
            "manifest.project.number",
            "manifest.firebase.webAppId",
            "manifest.firebase.apiKeyReference",
            "manifest.firebase.storageBucket",
            "manifest.firebase.hostingSite",
            "manifest.cloudRun.collaboration.image",
            "manifest.cloudRun.collaboration.digest",
            "manifest.cloudRun.documentApi.image",
            "manifest.cloudRun.documentApi.digest",
            "manifest.cloudRun.documentWorker.image",
            "manifest.cloudRun.documentWorker.digest",
            "manifest.operations.rollbackRevisionIds[0]",
            "manifest.operations.rollbackRevisionIds[1]",
            "manifest.operations.rollbackRevisionIds[2]",
        })
        self.assertEqual(packet["preflight"]["comparisonMode"], "static-only")

    def test_bootstrap_rejects_non_deferred_governance_placeholders(self) -> None:
        cases = (
            ("project.id", lambda manifest: manifest["project"].__setitem__("id", "${FIREBASE_STAGING_PROJECT_ID}")),
            ("project.billingAccount", lambda manifest: manifest["project"].__setitem__("billingAccount", "${GCP_BILLING_ACCOUNT_ID}")),
            ("budget.amount", lambda manifest: manifest["budget"].__setitem__("amount", "${STAGING_MONTHLY_BUDGET_KRW}")),
            ("budget.notificationChannels", lambda manifest: manifest["budget"].__setitem__("notificationChannels", ["${STAGING_BUDGET_NOTIFICATION_CHANNEL}"])),
            ("operations.approvalReference", lambda manifest: manifest["operations"].__setitem__("approvalReference", "${APPROVAL_REFERENCE}")),
            ("iam.principal", lambda manifest: manifest["iam"]["bindings"][0].__setitem__("principal", "serviceAccount:${COLLABORATION_SERVICE_ACCOUNT}")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest = bootstrap_manifest()
                mutate(manifest)
                with self.assertRaisesRegex(ApprovalPacketError, "unresolved placeholder"):
                    self.build_for_phase(manifest, phase="bootstrap")

    def test_bootstrap_rejects_live_report(self) -> None:
        manifest = bootstrap_manifest()

        with self.assertRaisesRegex(ApprovalPacketError, "bootstrap.*live report"):
            self.build_for_phase(manifest, phase="bootstrap", live=live_report(manifest))


class DeploymentPhaseValidationTest(PhaseTestCase):
    def test_deployment_requires_live_report(self) -> None:
        manifest = concrete_manifest()

        with self.assertRaisesRegex(ApprovalPacketError, "deployment.*live report"):
            self.build_for_phase(manifest, phase="deployment")

    def test_deployment_rejects_every_placeholder(self) -> None:
        manifest = bootstrap_manifest()

        with self.assertRaisesRegex(ApprovalPacketError, "unresolved placeholder"):
            self.build_for_phase(
                manifest,
                phase="deployment",
                live=live_report(manifest),
            )

    def test_deployment_builds_live_comparison_packet(self) -> None:
        manifest = concrete_manifest()

        packet = self.build_for_phase(
            manifest,
            phase="deployment",
            live=live_report(manifest),
        )

        self.assertEqual(packet["phase"], "deployment")
        self.assertEqual(packet["status"], "ready-for-deployment-approval")
        self.assertEqual(packet["deferredValues"], [])
        self.assertEqual(packet["preflight"]["comparisonMode"], "live")
        self.assertEqual(packet["approval"]["packetIsDeploymentApproval"], False)

    def test_deployment_live_review_status_requires_human_review(self) -> None:
        manifest = concrete_manifest()
        report = live_report(manifest)
        report["status"] = "review"
        report["warnings"] = ["unexpected rhwp-prefixed resources require explicit review"]

        packet = self.build_for_phase(
            manifest,
            phase="deployment",
            live=report,
        )

        self.assertEqual(packet["status"], "review-required")


class PhaseMarkdownAndCliTest(PhaseTestCase):
    def test_markdown_distinguishes_bootstrap_and_deployment(self) -> None:
        bootstrap = self.build_for_phase(bootstrap_manifest(), phase="bootstrap")
        deployment_manifest = concrete_manifest()
        deployment = self.build_for_phase(
            deployment_manifest,
            phase="deployment",
            live=live_report(deployment_manifest),
        )

        bootstrap_markdown = render_markdown(bootstrap)
        deployment_markdown = render_markdown(deployment)

        self.assertIn("# rhwp Staging Bootstrap Approval Packet", bootstrap_markdown)
        self.assertIn("- Phase: `bootstrap`", bootstrap_markdown)
        self.assertIn("## Deferred values", bootstrap_markdown)
        self.assertIn("# rhwp Staging Deployment Approval Packet", deployment_markdown)
        self.assertIn("- Phase: `deployment`", deployment_markdown)
        self.assertNotIn("## Deferred values", deployment_markdown)

    def test_cli_requires_and_reports_phase(self) -> None:
        source = inspect.getsource(staging_approval_packet.main)
        if '"--phase"' not in source and "'--phase'" not in source:
            self.fail("staging approval packet CLI must define --phase")

        manifest = bootstrap_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            static_path = root / "static.json"
            json_output = root / "packet.json"
            markdown_output = root / "packet.md"
            manifest_path.write_text(json.dumps(manifest))
            static_path.write_text(json.dumps(static_report(manifest)))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([
                    "--phase", "bootstrap",
                    "--manifest", str(manifest_path),
                    "--static-report", str(static_path),
                    "--json-output", str(json_output),
                    "--markdown-output", str(markdown_output),
                ])

            self.assertEqual(result, 0, stderr.getvalue())
            self.assertEqual(json.loads(json_output.read_text())["phase"], "bootstrap")
            self.assertIn('"phase": "bootstrap"', stdout.getvalue())


class ApprovalPacketPhaseWorkflowTest(unittest.TestCase):
    def test_workflow_routes_bootstrap_and_deployment_packets(self) -> None:
        workflow = WORKFLOW_PATH.read_text()

        for marker in (
            "approval_phase:",
            "Bootstrap approval packet",
            "inputs.approval_phase == 'bootstrap'",
            "--phase bootstrap",
            "staging-approval-packet-bootstrap",
            "inputs.approval_phase == 'deployment'",
            "--phase deployment",
            "staging-approval-packet-deployment",
        ):
            self.assertIn(marker, workflow)

        self.assertNotRegex(
            workflow,
            r"(?:gcloud|firebase)[^\n]*(?:\bcreate\b|\bdelete\b|\bdeploy\b|\benable\b|\bdisable\b|\bupdate\b|add-iam-policy-binding|set-iam-policy)",
        )


if __name__ == "__main__":
    unittest.main()
