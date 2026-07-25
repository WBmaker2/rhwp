#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = [
    ROOT / "deploy/cloudrun/collaboration-server.service.yaml",
    ROOT / "deploy/cloudrun/document-api.service.yaml",
]
TEXT_FILES = MANIFESTS + [
    ROOT / "firebase/.firebaserc.example",
    ROOT / "firebase/staging.env.example",
    ROOT / "deploy/cloudrun/README.md",
]


def fail(message: str) -> None:
    raise SystemExit(f"staging configuration validation failed: {message}")


def main() -> None:
    json.loads((ROOT / "firebase/firebase.json").read_text())
    json.loads((ROOT / "firebase/.firebaserc.example").read_text())

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
        if "secretKeyRef:" not in text:
            fail(f"{manifest.name} must reference Secret Manager for internal tokens")
        if re.search(r"name:\s+(?:INTERNAL_API_TOKEN|COLLABORATION_INTERNAL_TOKEN)\s*\n\s+value:", text):
            fail(f"{manifest.name} contains an inline internal token")

    firebaserc = (ROOT / "firebase/.firebaserc.example").read_text()
    if "${FIREBASE_STAGING_PROJECT_ID}" not in firebaserc:
        fail(".firebaserc.example must keep the staging project as a placeholder")

    firebase_json = json.loads((ROOT / "firebase/firebase.json").read_text())
    if firebase_json.get("emulators", {}).get("auth", {}).get("port") != 9099:
        fail("Auth emulator must be configured on port 9099")
    if firebase_json.get("hosting", {}).get("public") != "../rhwp-studio/dist":
        fail("Hosting must serve the built rhwp-studio output")

    print("staging configuration templates are valid; no deployment was performed")


if __name__ == "__main__":
    main()
