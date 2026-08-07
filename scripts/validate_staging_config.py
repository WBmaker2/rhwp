#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

from staging_preflight import load_manifest, validate_repository_contract

ROOT = Path(__file__).resolve().parents[1]
COLLABORATION_MANIFEST = ROOT / "deploy/cloudrun/collaboration-server.service.yaml"
DOCUMENT_API_MANIFEST = ROOT / "deploy/cloudrun/document-api.service.yaml"
DOCUMENT_WORKER_MANIFEST = ROOT / "deploy/cloudrun/document-worker.service.yaml"
STAGING_MANIFEST = ROOT / "deploy/staging/staging-manifest.json"
MANIFESTS = [
    COLLABORATION_MANIFEST,
    DOCUMENT_API_MANIFEST,
    DOCUMENT_WORKER_MANIFEST,
]
SECRET_MANIFESTS = [COLLABORATION_MANIFEST, DOCUMENT_API_MANIFEST]
TEXT_FILES = MANIFESTS + [
    ROOT / "firebase/.firebaserc.example",
    ROOT / "firebase/staging.env.example",
    ROOT / "deploy/cloudrun/README.md",
    STAGING_MANIFEST,
]


def fail(message: str) -> None:
    raise SystemExit(f"staging configuration validation failed: {message}")


def main() -> None:
    json.loads((ROOT / "firebase/firebase.json").read_text())
    json.loads((ROOT / "firebase/.firebaserc.example").read_text())
    staging_manifest = load_manifest(STAGING_MANIFEST)
    validate_repository_contract(staging_manifest, ROOT)

    combined = "\n".join(path.read_text() for path in TEXT_FILES)
    forbidden = [
        "-----BEGIN PRIVATE KEY-----",
        '"private_key"',
        '"client_email"',
        "AIzaSy",
    ]
    for marker in forbidden:
        if marker in combined:
            fail(f"credential-like value found: {marker}")

    for manifest in MANIFESTS:
        text = manifest.read_text()
        if not re.search(r"image:\s+\$\{[A-Z0-9_]+\}@sha256:\$\{[A-Z0-9_]+_DIGEST\}", text):
            fail(f"{manifest.name} must use a digest-pinned image placeholder")
        if ":latest" in text:
            fail(f"{manifest.name} contains a mutable latest image tag")
        if "serviceAccountName: ${" not in text:
            fail(f"{manifest.name} must use a dedicated service-account placeholder")
        if re.search(r"name:\s+(?:INTERNAL_API_TOKEN|COLLABORATION_INTERNAL_TOKEN)\s*\n\s+value:", text):
            fail(f"{manifest.name} contains an inline internal token")

    for manifest in SECRET_MANIFESTS:
        if "secretKeyRef:" not in manifest.read_text():
            fail(f"{manifest.name} must reference Secret Manager for internal tokens")

    worker_text = DOCUMENT_WORKER_MANIFEST.read_text()
    if "run.googleapis.com/ingress: internal" not in worker_text:
        fail("document worker must use internal ingress")
    if "containerConcurrency: 1" not in worker_text:
        fail("document worker must use concurrency 1 for 200 MiB processing")
    if "timeoutSeconds: 900" not in worker_text:
        fail("document worker must allow the bounded 900-second task timeout")
    if "memory: 2Gi" not in worker_text:
        fail("document worker must reserve 2Gi memory")
    if "ALLOW_EMULATOR_TASKS" not in worker_text or 'value: "false"' not in worker_text:
        fail("document worker production template must reject emulator task bypass")

    document_api_text = DOCUMENT_API_MANIFEST.read_text()
    if "name: TASK_DISPATCH_DEADLINE_SECONDS" not in document_api_text:
        fail("document API must configure the Cloud Tasks dispatch deadline")
    if 'value: "900"' not in document_api_text:
        fail("document API Cloud Tasks dispatch deadline must be 900 seconds")

    firebaserc = (ROOT / "firebase/.firebaserc.example").read_text()
    if "${FIREBASE_STAGING_PROJECT_ID}" not in firebaserc:
        fail(".firebaserc.example must keep the staging project as a placeholder")

    firebase_json = json.loads((ROOT / "firebase/firebase.json").read_text())
    if firebase_json.get("emulators", {}).get("auth", {}).get("port") != 9099:
        fail("Auth emulator must be configured on port 9099")
    if firebase_json.get("hosting", {}).get("public") != "../rhwp-studio/dist":
        fail("Hosting must serve the built rhwp-studio output")

    print("staging manifest and configuration templates are valid; no deployment was performed")


if __name__ == "__main__":
    main()
