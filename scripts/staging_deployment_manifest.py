#!/usr/bin/env python3
"""Resolve the release-derived fields of a staging manifest without cloud calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.staging_preflight import validate_manifest

SCHEMA = "rhwp.staging-deployment-release/v1"
PLACEHOLDER_PATTERN = re.compile(r"\$\{[A-Z0-9_]+\}")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
PROJECT_NUMBER_PATTERN = re.compile(r"[0-9]{6,20}")
RUN_ID_PATTERN = re.compile(r"[0-9]{1,20}")
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
SERVICE_IMAGE_REPOSITORIES = {
    "collaboration": "collaboration",
    "documentApi": "document-api",
    "documentWorker": "document-worker",
}
DEPLOYMENT_STAGES = frozenset({"initial", "upgrade"})


class DeploymentManifestError(RuntimeError):
    pass


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise DeploymentManifestError(f"{label} not found: {path}") from error
    except json.JSONDecodeError as error:
        raise DeploymentManifestError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise DeploymentManifestError(f"{label} root must be an object")
    return value


def build_deployment_manifest(
    bootstrap_manifest: dict[str, Any],
    release: dict[str, Any],
    *,
    expected_source_commit: str,
) -> dict[str, Any]:
    manifest = copy.deepcopy(bootstrap_manifest)
    if manifest.get("schemaVersion") != "rhwp.staging/v1":
        raise DeploymentManifestError("bootstrap manifest schemaVersion is invalid")
    if manifest.get("environment") != "staging":
        raise DeploymentManifestError("bootstrap manifest environment must be staging")
    project = _mapping(manifest, "project", "manifest")
    project_id = _non_placeholder_string(project, "id", "manifest.project")
    region = _non_placeholder_string(project, "region", "manifest.project")
    expected_image_prefix = f"{region}-docker.pkg.dev/{project_id}/rhwp-staging/"
    _validate_release(release, expected_source_commit, expected_image_prefix)

    _replace_manifest_fields(manifest, release)
    remaining = _placeholder_paths(manifest)
    if remaining:
        raise DeploymentManifestError(
            "deployment manifest has unresolved placeholder at "
            + ", ".join(remaining)
        )
    operations = _mapping(manifest, "operations", "manifest")
    if operations.get("cloudMutationApproved") is not False:
        raise DeploymentManifestError(
            "manifest.operations.cloudMutationApproved must remain false"
        )
    try:
        validate_manifest(manifest)
    except Exception as error:
        raise DeploymentManifestError(
            f"deployment manifest failed staging validation: {error}"
        ) from error
    return manifest


def _validate_release(
    release: dict[str, Any],
    expected_source_commit: str,
    expected_image_prefix: str,
) -> None:
    sensitive = _sensitive_paths(release)
    if sensitive:
        raise DeploymentManifestError("sensitive key is not allowed at " + ", ".join(sensitive))
    if set(release) != {
        "schemaVersion",
        "sourceCommitSha",
        "workflowRunId",
        "workflowRunAttempt",
        "deploymentStage",
        "project",
        "firebase",
        "cloudRun",
        "tasks",
        "rollbackRevisionIds",
    }:
        raise DeploymentManifestError("release metadata keys are not exact")
    if release.get("schemaVersion") != SCHEMA:
        raise DeploymentManifestError(f"release schemaVersion must be {SCHEMA}")
    source = _string(release, "sourceCommitSha", "release")
    if not COMMIT_PATTERN.fullmatch(source) or source != expected_source_commit:
        raise DeploymentManifestError("release source commit does not match checked-out commit")
    run_id = _string(release, "workflowRunId", "release")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise DeploymentManifestError("release workflowRunId must be decimal")
    attempt = release.get("workflowRunAttempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise DeploymentManifestError("release workflowRunAttempt must be a positive integer")
    stage = release.get("deploymentStage")
    if stage not in DEPLOYMENT_STAGES:
        raise DeploymentManifestError("release deploymentStage must be initial or upgrade")

    project = _mapping(release, "project", "release")
    _require_keys(project, {"number"}, "release.project")
    if not PROJECT_NUMBER_PATTERN.fullmatch(_string(project, "number", "release.project")):
        raise DeploymentManifestError("release.project.number must be decimal")

    firebase = _mapping(release, "firebase", "release")
    _require_keys(firebase, {"webAppId", "apiKeyReference"}, "release.firebase")
    _non_placeholder_string(firebase, "webAppId", "release.firebase")
    api_reference = _non_placeholder_string(firebase, "apiKeyReference", "release.firebase")
    if re.fullmatch(r"AIza[0-9A-Za-z_-]{20,}", api_reference):
        raise DeploymentManifestError("release.firebase.apiKeyReference looks like a raw Firebase API key")

    cloud_run = _mapping(release, "cloudRun", "release")
    _require_keys(cloud_run, {"collaboration", "documentApi", "documentWorker"}, "release.cloudRun")
    for key in ("collaboration", "documentApi", "documentWorker"):
        service = _mapping(cloud_run, key, f"release.cloudRun.{key}")
        _require_keys(service, {"image", "digest"}, f"release.cloudRun.{key}")
        image = _non_placeholder_string(service, "image", f"release.cloudRun.{key}")
        digest = _string(service, "digest", f"release.cloudRun.{key}")
        if ":latest" in image or "@sha256:" in image:
            raise DeploymentManifestError(f"release.cloudRun.{key}.image must be a mutable-free repository reference")
        expected_repository = expected_image_prefix + SERVICE_IMAGE_REPOSITORIES[key]
        if not (image == expected_repository or image.startswith(expected_repository + ":")):
            raise DeploymentManifestError(
                f"release.cloudRun.{key}.image must use the canonical staging repository"
            )
        if not SHA256_PATTERN.fullmatch(digest):
            raise DeploymentManifestError(f"release.cloudRun.{key}.digest must be a lowercase SHA-256")

    tasks = _mapping(release, "tasks", "release")
    _require_keys(tasks, {"parse", "export"}, "release.tasks")
    for key, suffix in (("parse", "/run/parse"), ("export", "/run/export")):
        task = _mapping(tasks, key, f"release.tasks.{key}")
        _require_keys(task, {"targetUrl"}, f"release.tasks.{key}")
        target = _non_placeholder_string(task, "targetUrl", f"release.tasks.{key}")
        if not target.startswith("https://") or not target.endswith(suffix):
            raise DeploymentManifestError(f"release.tasks.{key}.targetUrl is invalid")

    rollback = release.get("rollbackRevisionIds")
    if not isinstance(rollback, list) or len(rollback) != 3:
        raise DeploymentManifestError("release.rollbackRevisionIds must contain three entries")
    if stage == "initial":
        if rollback != [None, None, None]:
            raise DeploymentManifestError(
                "initial release.rollbackRevisionIds must explicitly contain three null entries"
            )
    elif not all(
        isinstance(item, str) and item.strip() and not PLACEHOLDER_PATTERN.search(item)
        for item in rollback
    ):
        raise DeploymentManifestError("upgrade release.rollbackRevisionIds must be concrete strings")

def _replace_manifest_fields(manifest: dict[str, Any], release: dict[str, Any]) -> None:
    _mapping(manifest, "project", "manifest")["number"] = release["project"]["number"]
    firebase = _mapping(manifest, "firebase", "manifest")
    firebase["webAppId"] = release["firebase"]["webAppId"]
    firebase["apiKeyReference"] = release["firebase"]["apiKeyReference"]
    cloud_run = _mapping(manifest, "cloudRun", "manifest")
    for key in ("collaboration", "documentApi", "documentWorker"):
        cloud_run[key]["image"] = release["cloudRun"][key]["image"]
        cloud_run[key]["digest"] = release["cloudRun"][key]["digest"]
    tasks = _mapping(manifest, "tasks", "manifest")
    tasks["parse"]["targetUrl"] = release["tasks"]["parse"]["targetUrl"]
    tasks["export"]["targetUrl"] = release["tasks"]["export"]["targetUrl"]
    _mapping(manifest, "operations", "manifest")["rollbackRevisionIds"] = list(
        release["rollbackRevisionIds"]
    )
    _mapping(manifest, "operations", "manifest")["deploymentStage"] = release[
        "deploymentStage"
    ]


def _placeholder_paths(value: Any, path: str = "manifest") -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.extend(_placeholder_paths(item, f"{path}.{key}"))
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            result.extend(_placeholder_paths(item, f"{path}[{index}]"))
        return result
    return [path] if isinstance(value, str) and PLACEHOLDER_PATTERN.search(value) else []


def _sensitive_paths(value: Any, path: str = "release") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                result.append(child)
            result.extend(_sensitive_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_sensitive_paths(item, f"{path}[{index}]"))
    return result


def _require_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise DeploymentManifestError(f"{path} keys are not exact")


def _mapping(value: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise DeploymentManifestError(f"{path}.{key} must be an object")
    return item


def _string(value: dict[str, Any], key: str, path: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise DeploymentManifestError(f"{path}.{key} must be a non-empty string")
    return item.strip()


def _non_placeholder_string(value: dict[str, Any], key: str, path: str) -> str:
    item = _string(value, key, path)
    if PLACEHOLDER_PATTERN.search(item):
        raise DeploymentManifestError(f"{path}.{key} must be concrete")
    return item


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(content)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a staging deployment manifest without cloud calls")
    parser.add_argument("--bootstrap-manifest", type=Path, required=True)
    parser.add_argument("--release-metadata", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bootstrap = load_object(args.bootstrap_manifest, "bootstrap manifest")
        release = load_object(args.release_metadata, "release metadata")
        manifest = build_deployment_manifest(
            bootstrap,
            release,
            expected_source_commit=args.expected_source_commit,
        )
        raw = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(args.output, raw)
    except (DeploymentManifestError, OSError) as error:
        print(f"staging deployment manifest failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "materialized",
        "output": str(args.output),
        "sourceCommitSha": args.expected_source_commit,
        "manifestSha256": hashlib.sha256(raw.encode()).hexdigest(),
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
