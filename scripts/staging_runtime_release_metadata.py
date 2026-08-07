#!/usr/bin/env python3
"""Derive source-bound deployment metadata from release and worker evidence.

The input evidence files are read as raw bytes and never rewritten.  Only the
small, validated metadata object used by ``staging_deployment_manifest.py`` is
generated.  No cloud or GitHub API calls are made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"[0-9]{1,20}")
SCHEMA = "rhwp.staging-deployment-release/v1"
RELEASE_SCHEMA = "rhwp.staging-release-candidate/v1"
WORKER_SCHEMA = "rhwp.staging-worker-bootstrap/v1"
RELEASE_KEYS = {
    "schemaVersion",
    "sourceCommitSha",
    "workflowRunId",
    "workflowRunAttempt",
    "deploymentStage",
    "project",
    "firebase",
    "cloudRun",
    "rollbackRevisionIds",
}
WORKER_KEYS = {
    "schemaVersion",
    "sourceCommitSha",
    "releaseWorkflowRunId",
    "releaseWorkflowRunAttempt",
    "releaseArtifactDigest",
    "releaseEvidenceSha256",
    "bootstrapWorkflowRunId",
    "bootstrapWorkflowRunAttempt",
    "project",
    "firebase",
    "worker",
    "deploymentStage",
    "rollbackRevisionId",
}
SERVICE_KEYS = ("collaboration", "documentApi", "documentWorker")


class RuntimeMetadataError(RuntimeError):
    """Raised when evidence binding or metadata shape is not exact."""


def _load_raw_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise RuntimeMetadataError(f"{label} not found or unreadable") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeMetadataError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeMetadataError(f"{label} root must be an object")
    return raw, value


def _string(value: dict[str, Any], key: str, path: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RuntimeMetadataError(f"{path}.{key} must be a non-empty string")
    return item.strip()


def _mapping(value: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise RuntimeMetadataError(f"{path}.{key} must be an object")
    return item


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise RuntimeMetadataError(f"{path} keys are not exact")


def _positive_int(value: dict[str, Any], key: str, path: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise RuntimeMetadataError(f"{path}.{key} must be a positive integer")
    return item


def _sha256(raw: bytes, expected: str | None, label: str) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None:
        if not SHA256_RE.fullmatch(expected) or digest != expected:
            raise RuntimeMetadataError(f"{label} exact-byte SHA-256 does not match")
    return digest


def _validate_common_commit(value: dict[str, Any], path: str, expected: str) -> str:
    commit = _string(value, "sourceCommitSha", path)
    if not COMMIT_RE.fullmatch(commit) or commit != expected:
        raise RuntimeMetadataError(f"{path}.sourceCommitSha does not match expected source")
    return commit


def _validate_release(release: dict[str, Any], expected_source: str) -> None:
    _exact_keys(release, RELEASE_KEYS, "release")
    if release.get("schemaVersion") != RELEASE_SCHEMA:
        raise RuntimeMetadataError("release schemaVersion is invalid")
    _validate_common_commit(release, "release", expected_source)
    run_id = _string(release, "workflowRunId", "release")
    if not RUN_ID_RE.fullmatch(run_id):
        raise RuntimeMetadataError("release workflowRunId is invalid")
    _positive_int(release, "workflowRunAttempt", "release")
    if release.get("deploymentStage") != "initial":
        raise RuntimeMetadataError("release deploymentStage must be initial")
    if release.get("rollbackRevisionIds") != [None, None, None]:
        raise RuntimeMetadataError("release rollback revisions must be three null entries")

    project = _mapping(release, "project", "release")
    number = _string(project, "number", "release.project")
    if not number.isdecimal():
        raise RuntimeMetadataError("release.project.number must be decimal")
    firebase = _mapping(release, "firebase", "release")
    _string(firebase, "webAppId", "release.firebase")
    api_reference = _string(firebase, "apiKeyReference", "release.firebase")
    if api_reference.startswith("AIza"):
        raise RuntimeMetadataError("release.firebase.apiKeyReference looks like a raw API key")
    cloud_run = _mapping(release, "cloudRun", "release")
    _exact_keys(cloud_run, set(SERVICE_KEYS), "release.cloudRun")
    for service_name in SERVICE_KEYS:
        service = _mapping(cloud_run, service_name, f"release.cloudRun.{service_name}")
        image = _string(service, "image", f"release.cloudRun.{service_name}")
        digest = _string(service, "digest", f"release.cloudRun.{service_name}")
        if not image.startswith("asia-northeast3-docker.pkg.dev/") or ":latest" in image:
            raise RuntimeMetadataError(f"release.cloudRun.{service_name}.image is invalid")
        if not SHA256_RE.fullmatch(digest):
            raise RuntimeMetadataError(f"release.cloudRun.{service_name}.digest is invalid")


def _validate_worker(worker: dict[str, Any], expected_source: str, release: dict[str, Any]) -> None:
    _exact_keys(worker, WORKER_KEYS, "worker")
    if worker.get("schemaVersion") != WORKER_SCHEMA:
        raise RuntimeMetadataError("worker schemaVersion is invalid")
    _validate_common_commit(worker, "worker", expected_source)
    if str(worker.get("releaseWorkflowRunId")) != str(release.get("workflowRunId")):
        raise RuntimeMetadataError("worker release workflow run ID does not match release")
    if worker.get("releaseWorkflowRunAttempt") != release.get("workflowRunAttempt"):
        raise RuntimeMetadataError("worker release workflow attempt does not match release")
    release_artifact_digest = _string(worker, "releaseArtifactDigest", "worker")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", release_artifact_digest):
        raise RuntimeMetadataError("worker release artifact digest is invalid")
    release_evidence_sha = _string(worker, "releaseEvidenceSha256", "worker")
    if not SHA256_RE.fullmatch(release_evidence_sha):
        raise RuntimeMetadataError("worker release evidence SHA-256 is invalid")
    _string(worker, "bootstrapWorkflowRunId", "worker")
    _positive_int(worker, "bootstrapWorkflowRunAttempt", "worker")
    if worker.get("deploymentStage") != "initial" or worker.get("rollbackRevisionId") is not None:
        raise RuntimeMetadataError("worker bootstrap must represent an initial deployment")

    release_project = _mapping(release, "project", "release")
    worker_project = _mapping(worker, "project", "worker")
    if _string(worker_project, "number", "worker.project") != _string(release_project, "number", "release.project"):
        raise RuntimeMetadataError("worker project number does not match release")
    release_firebase = _mapping(release, "firebase", "release")
    worker_firebase = _mapping(worker, "firebase", "worker")
    if _string(worker_firebase, "webAppId", "worker.firebase") != _string(release_firebase, "webAppId", "release.firebase"):
        raise RuntimeMetadataError("worker Firebase web app does not match release")

    worker_data = _mapping(worker, "worker", "worker")
    service = _string(worker_data, "service", "worker.worker")
    if service != "rhwp-document-worker-staging":
        raise RuntimeMetadataError("worker service name is invalid")
    url = _string(worker_data, "url", "worker.worker")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise RuntimeMetadataError("worker URL must be an HTTPS Cloud Run host")
    if not parsed.netloc.endswith(".a.run.app"):
        raise RuntimeMetadataError("worker URL must be a Cloud Run run.app host")
    digest = _string(worker_data, "digest", "worker.worker")
    if not SHA256_RE.fullmatch(digest):
        raise RuntimeMetadataError("worker image digest is invalid")
    release_worker = _mapping(_mapping(release, "cloudRun", "release"), "documentWorker", "release.cloudRun")
    if _string(worker_data, "image", "worker.worker") != _string(release_worker, "image", "release.cloudRun.documentWorker"):
        raise RuntimeMetadataError("worker image repository does not match release")
    if digest != _string(release_worker, "digest", "release.cloudRun.documentWorker"):
        raise RuntimeMetadataError("worker image digest does not match release")
    _string(worker_data, "revision", "worker.worker")


def build_release_metadata(
    release: dict[str, Any],
    worker: dict[str, Any],
    *,
    expected_source_commit: str,
) -> dict[str, Any]:
    _validate_release(release, expected_source_commit)
    _validate_worker(worker, expected_source_commit, release)
    worker_data = _mapping(worker, "worker", "worker")
    worker_url = _string(worker_data, "url", "worker.worker").rstrip("/")
    tasks = {
        "parse": {"targetUrl": worker_url + "/run/parse"},
        "export": {"targetUrl": worker_url + "/run/export"},
    }
    return {
        "schemaVersion": SCHEMA,
        "sourceCommitSha": expected_source_commit,
        "workflowRunId": _string(release, "workflowRunId", "release"),
        "workflowRunAttempt": _positive_int(release, "workflowRunAttempt", "release"),
        "deploymentStage": "initial",
        "project": {"number": _string(_mapping(release, "project", "release"), "number", "release.project")},
        "firebase": dict(_mapping(release, "firebase", "release")),
        "cloudRun": {
            key: dict(_mapping(_mapping(release, "cloudRun", "release"), key, "release.cloudRun"))
            for key in SERVICE_KEYS
        },
        "tasks": tasks,
        "rollbackRevisionIds": [None, None, None],
    }


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive source-bound staging release metadata")
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--worker-evidence", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-release-evidence-sha256")
    parser.add_argument("--expected-worker-evidence-sha256")
    parser.add_argument("--expected-release-artifact-digest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if not COMMIT_RE.fullmatch(args.expected_source_commit):
            raise RuntimeMetadataError("expected source commit is invalid")
        release_raw, release = _load_raw_json(args.release_evidence, "release evidence")
        worker_raw, worker = _load_raw_json(args.worker_evidence, "worker evidence")
        release_sha = _sha256(release_raw, args.expected_release_evidence_sha256, "release evidence")
        worker_sha = _sha256(worker_raw, args.expected_worker_evidence_sha256, "worker evidence")
        worker_release_sha = worker.get("releaseEvidenceSha256")
        if worker_release_sha != release_sha:
            raise RuntimeMetadataError("worker release evidence SHA-256 does not match exact release bytes")
        if args.expected_release_artifact_digest is not None:
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.expected_release_artifact_digest):
                raise RuntimeMetadataError("expected release artifact digest is invalid")
            if worker.get("releaseArtifactDigest") != args.expected_release_artifact_digest:
                raise RuntimeMetadataError("worker release artifact digest does not match expected digest")
        metadata = build_release_metadata(
            release,
            worker,
            expected_source_commit=args.expected_source_commit,
        )
        output_raw = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
        _atomic_write(args.output, output_raw)
    except (RuntimeMetadataError, OSError) as error:
        try:
            args.output.with_name(args.output.name + ".tmp").unlink(missing_ok=True)
        except OSError:
            pass
        print(f"staging runtime release metadata failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "materialized",
        "output": str(args.output),
        "sourceCommitSha": args.expected_source_commit,
        "releaseEvidenceSha256": release_sha,
        "workerEvidenceSha256": worker_sha,
        "metadataSha256": hashlib.sha256(output_raw).hexdigest(),
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
