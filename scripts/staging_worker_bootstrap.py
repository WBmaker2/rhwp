#!/usr/bin/env python3
"""Validate release-candidate evidence and render the first worker service manifest.

This helper never calls a cloud API and never mutates the candidate evidence.  It only
creates a deterministic, secret-free Cloud Run YAML for the protected worker bootstrap
job and a small input summary that binds the render to the candidate run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "rhwp.staging-release-candidate/v1"
SUMMARY_SCHEMA = "rhwp.staging-worker-bootstrap-input/v1"
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
ARTIFACT_DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
PROJECT_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
PROJECT_NUMBER_PATTERN = re.compile(r"[0-9]{6,20}")
BUCKET_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]")
SERVICE_ACCOUNT_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com")
SERVICE_NAMES = ("collaboration", "documentApi", "documentWorker")


class WorkerBootstrapError(RuntimeError):
    """Raised when an immutable worker bootstrap input is invalid."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise WorkerBootstrapError(f"{label} not found") from error
    except json.JSONDecodeError as error:
        raise WorkerBootstrapError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise WorkerBootstrapError(f"{label} root must be an object")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise WorkerBootstrapError(f"{label} keys are not exact")


def _string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise WorkerBootstrapError(f"{label}.{key} must be a non-empty string")
    return item.strip()


def _validate_release_evidence(
    evidence: dict[str, Any],
    *,
    expected_source_commit: str,
    expected_run_id: str,
    expected_run_attempt: int,
    expected_project_number: str,
    expected_project_id: str,
    region: str,
    expected_artifact_digest: str,
) -> dict[str, Any]:
    _require_keys(
        evidence,
        {
            "schemaVersion",
            "sourceCommitSha",
            "workflowRunId",
            "workflowRunAttempt",
            "deploymentStage",
            "project",
            "firebase",
            "cloudRun",
            "rollbackRevisionIds",
        },
        "release evidence",
    )
    if evidence.get("schemaVersion") != SCHEMA:
        raise WorkerBootstrapError("release evidence schemaVersion is invalid")
    source = _string(evidence, "sourceCommitSha", "release evidence")
    if not COMMIT_PATTERN.fullmatch(source) or source != expected_source_commit:
        raise WorkerBootstrapError("release evidence source commit does not match")
    run_id = _string(evidence, "workflowRunId", "release evidence")
    if run_id != expected_run_id or not run_id.isdecimal():
        raise WorkerBootstrapError("release evidence workflow run ID does not match")
    attempt = evidence.get("workflowRunAttempt")
    if attempt != expected_run_attempt or not isinstance(attempt, int) or isinstance(attempt, bool):
        raise WorkerBootstrapError("release evidence workflow run attempt does not match")
    if evidence.get("deploymentStage") != "initial":
        raise WorkerBootstrapError("worker bootstrap requires deploymentStage=initial")

    project = evidence.get("project")
    if not isinstance(project, dict):
        raise WorkerBootstrapError("release evidence project must be an object")
    _require_keys(project, {"number"}, "release evidence project")
    if _string(project, "number", "release evidence project") != expected_project_number:
        raise WorkerBootstrapError("release evidence project number does not match")
    if not PROJECT_NUMBER_PATTERN.fullmatch(expected_project_number):
        raise WorkerBootstrapError("project number is invalid")

    firebase = evidence.get("firebase")
    if not isinstance(firebase, dict):
        raise WorkerBootstrapError("release evidence firebase must be an object")
    _require_keys(firebase, {"webAppId", "apiKeyReference"}, "release evidence firebase")
    web_app_id = _string(firebase, "webAppId", "release evidence firebase")
    if not web_app_id.startswith("1:"):
        raise WorkerBootstrapError("Firebase Web App ID is invalid")
    if _string(firebase, "apiKeyReference", "release evidence firebase") != "firebase-web-config/staging":
        raise WorkerBootstrapError("Firebase API key reference is not canonical")

    cloud_run = evidence.get("cloudRun")
    if not isinstance(cloud_run, dict):
        raise WorkerBootstrapError("release evidence cloudRun must be an object")
    _require_keys(cloud_run, set(SERVICE_NAMES), "release evidence cloudRun")
    expected_prefix = f"{region}-docker.pkg.dev/{expected_project_id}/rhwp-staging/"
    for key in SERVICE_NAMES:
        service = cloud_run.get(key)
        if not isinstance(service, dict):
            raise WorkerBootstrapError(f"release evidence cloudRun.{key} must be an object")
        _require_keys(service, {"image", "digest"}, f"release evidence cloudRun.{key}")
        image = _string(service, "image", f"release evidence cloudRun.{key}")
        digest = _string(service, "digest", f"release evidence cloudRun.{key}")
        expected_repository = expected_prefix + {
            "collaboration": "collaboration",
            "documentApi": "document-api",
            "documentWorker": "document-worker",
        }[key]
        if image != expected_repository or not SHA256_PATTERN.fullmatch(digest):
            raise WorkerBootstrapError(f"release evidence cloudRun.{key} is not digest-pinned")

    rollback = evidence.get("rollbackRevisionIds")
    if rollback != [None, None, None]:
        raise WorkerBootstrapError("initial release rollback revisions must be three nulls")
    if not ARTIFACT_DIGEST_PATTERN.fullmatch(expected_artifact_digest):
        raise WorkerBootstrapError("release artifact digest is invalid")
    return {"webAppId": web_app_id, "worker": cloud_run["documentWorker"]}


def _validate_operating_values(
    *, project_id: str, region: str, bucket: str, service_account: str
) -> None:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise WorkerBootstrapError("project ID is invalid")
    if not region or "/" in region or " " in region:
        raise WorkerBootstrapError("region is invalid")
    if not BUCKET_PATTERN.fullmatch(bucket) or "${" in bucket:
        raise WorkerBootstrapError("Storage bucket must be concrete and valid")
    if not SERVICE_ACCOUNT_PATTERN.fullmatch(service_account):
        raise WorkerBootstrapError("worker service account is invalid")


def render_worker_manifest(
    evidence: dict[str, Any],
    *,
    expected_source_commit: str,
    expected_run_id: str,
    expected_run_attempt: int,
    expected_project_number: str,
    project_id: str,
    region: str,
    storage_bucket: str,
    service_account: str,
    expected_artifact_digest: str,
    evidence_sha256: str,
) -> tuple[str, dict[str, Any]]:
    _validate_operating_values(
        project_id=project_id,
        region=region,
        bucket=storage_bucket,
        service_account=service_account,
    )
    values = _validate_release_evidence(
        evidence,
        expected_source_commit=expected_source_commit,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        expected_project_number=expected_project_number,
        expected_project_id=project_id,
        region=region,
        expected_artifact_digest=expected_artifact_digest,
    )
    worker = values["worker"]
    image = worker["image"]
    digest = worker["digest"]
    yaml = f'''apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: rhwp-document-worker-staging
  annotations:
    run.googleapis.com/ingress: internal
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "10"
    spec:
      serviceAccountName: {service_account}
      containerConcurrency: 1
      timeoutSeconds: 900
      containers:
        - image: {image}@sha256:{digest}
          ports:
            - name: http1
              containerPort: 8080
          resources:
            limits:
              cpu: "2"
              memory: 2Gi
          env:
            - name: FIREBASE_STORAGE_BUCKET
              value: {storage_bucket}
            - name: RHWP_COLLABORATION_WORKER_BIN
              value: /usr/local/bin/rhwp-collaboration-worker
            - name: ALLOW_EMULATOR_TASKS
              value: "false"
          startupProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 3
            failureThreshold: 60
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 30
'''
    summary = {
        "schemaVersion": SUMMARY_SCHEMA,
        "sourceCommitSha": expected_source_commit,
        "releaseWorkflowRunId": expected_run_id,
        "releaseWorkflowRunAttempt": expected_run_attempt,
        "releaseArtifactDigest": expected_artifact_digest,
        "releaseEvidenceSha256": evidence_sha256,
        "project": {"id": project_id, "number": expected_project_number, "region": region},
        "firebase": {"webAppId": values["webAppId"]},
        "worker": {
            "service": "rhwp-document-worker-staging",
            "image": image,
            "digest": digest,
            "storageBucket": storage_bucket,
            "serviceAccount": service_account,
        },
        "deploymentStage": "initial",
        "rollbackRevisionId": None,
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }
    return yaml, summary


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-release-run-id", required=True)
    parser.add_argument("--expected-release-run-attempt", type=int, required=True)
    parser.add_argument("--expected-project-number", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--storage-bucket", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--release-artifact-digest", required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence_bytes = args.release_evidence.read_bytes()
        evidence = _load_object(args.release_evidence, "release evidence")
        evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
        manifest, summary = render_worker_manifest(
            evidence,
            expected_source_commit=args.expected_source_commit,
            expected_run_id=args.expected_release_run_id,
            expected_run_attempt=args.expected_release_run_attempt,
            expected_project_number=args.expected_project_number,
            project_id=args.project_id,
            region=args.region,
            storage_bucket=args.storage_bucket,
            service_account=args.service_account,
            expected_artifact_digest=args.release_artifact_digest,
            evidence_sha256=evidence_sha256,
        )
        _atomic_write(args.manifest_output, manifest)
        _atomic_write(args.summary_output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    except (OSError, WorkerBootstrapError) as error:
        print(f"staging worker bootstrap input failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "rendered",
        "manifestSha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "summarySha256": hashlib.sha256((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
