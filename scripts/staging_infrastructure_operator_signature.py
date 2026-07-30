"""Durable, offline verification for fixed-query operator attestations.

Raw-response digests show that a response was hashed, but cannot prove who
performed a read.  A promotion therefore accepts only an Ed25519 envelope
signed by a key pinned in this tracked, immutable-by-review registry.  The
registry deliberately starts empty: no real operator key can be trusted until
a separately reviewed code change adds its public key and fingerprint.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from scripts.staging_infrastructure_operator_attestation import (
    canonical_attestation_bytes,
)
from scripts.staging_infrastructure_validation import StrictJsonError, validate_json_domain

SIGNED_ATTESTATION_SCHEMA = "rhwp.staging-infrastructure-operator-signed-attestation/v1"
ALGORITHM = "ed25519"
KEY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BASE64URL = re.compile(r"^[A-Za-z0-9_-]{86}$")

# Add a reviewed public key only through a separate approved source change.
# A protected Environment variable is intentionally not a trust root because a
# variable editor could otherwise replace both the key and the signed package.
TRUSTED_OPERATOR_KEY_REGISTRY: Mapping[str, Mapping[str, str]] = MappingProxyType({})


class OperatorSignatureError(RuntimeError):
    pass


def preflight_operator_signature(key_id: str, private_key: Path) -> None:
    """Fail before live reads if no immutable signing trust root is configured."""
    entry = _trusted_key(key_id)
    _validate_private_key_path(private_key)
    _verify_public_key_algorithm(entry["publicKeyPem"])


def sign_operator_attestation(
    payload: dict[str, Any], *, key_id: str, private_key: Path
) -> dict[str, Any]:
    """Sign canonical payload bytes and immediately verify against pinned key."""
    entry = _trusted_key(key_id)
    _validate_private_key_path(private_key)
    _verify_public_key_algorithm(entry["publicKeyPem"])
    try:
        raw = canonical_attestation_bytes(payload)
    except StrictJsonError as error:
        raise OperatorSignatureError("operator attestation payload is invalid") from error
    signature = _openssl_sign(raw, private_key)
    envelope = {
        "schemaVersion": SIGNED_ATTESTATION_SCHEMA,
        "issuer": {
            "keyId": key_id,
            "algorithm": ALGORITHM,
            "publicKeySha256": entry["publicKeySha256"],
        },
        "payload": deepcopy(payload),
        "payloadSha256": hashlib.sha256(raw).hexdigest(),
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }
    verify_operator_attestation_envelope(envelope)
    return envelope


def verify_operator_attestation_envelope(value: Any) -> dict[str, Any]:
    """Verify an exact envelope after JSON deserialization and return its payload."""
    try:
        validate_json_domain(value)
    except StrictJsonError as error:
        raise OperatorSignatureError("signed operator attestation JSON is invalid") from error
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "issuer", "payload", "payloadSha256", "signature",
    }:
        raise OperatorSignatureError("signed operator attestation schema is invalid")
    issuer, payload = value.get("issuer"), value.get("payload")
    if not isinstance(issuer, dict) or set(issuer) != {
        "keyId", "algorithm", "publicKeySha256",
    } or not isinstance(payload, dict):
        raise OperatorSignatureError("signed operator attestation issuer is invalid")
    key_id = issuer.get("keyId")
    if not isinstance(key_id, str):
        raise OperatorSignatureError("signed operator attestation key identifier is invalid")
    entry = _trusted_key(key_id)
    if issuer.get("algorithm") != ALGORITHM or issuer.get("publicKeySha256") != entry["publicKeySha256"]:
        raise OperatorSignatureError("signed operator attestation issuer does not match the pinned key")
    if not isinstance(value.get("payloadSha256"), str) or not SHA256.fullmatch(value["payloadSha256"]):
        raise OperatorSignatureError("signed operator attestation payload digest is invalid")
    raw = canonical_attestation_bytes(payload)
    if hashlib.sha256(raw).hexdigest() != value["payloadSha256"]:
        raise OperatorSignatureError("signed operator attestation payload digest differs")
    signature = _decode_signature(value.get("signature"))
    _verify_public_key_algorithm(entry["publicKeyPem"])
    _openssl_verify(raw, signature, entry["publicKeyPem"])
    return deepcopy(payload)


def signed_attestation_sha256(value: dict[str, Any]) -> str:
    """Digest the complete signed envelope, not its self-reported response hashes."""
    try:
        return hashlib.sha256(canonical_attestation_bytes(value)).hexdigest()
    except StrictJsonError as error:
        raise OperatorSignatureError("signed operator attestation is invalid") from error


def _trusted_key(key_id: str) -> Mapping[str, str]:
    if not isinstance(key_id, str) or not KEY_ID.fullmatch(key_id):
        raise OperatorSignatureError("operator signing key identifier is invalid")
    entry = TRUSTED_OPERATOR_KEY_REGISTRY.get(key_id)
    if not isinstance(entry, Mapping) or set(entry) != {
        "algorithm", "publicKeyPem", "publicKeySha256",
    }:
        raise OperatorSignatureError("operator signing key is not configured in the immutable registry")
    public_key, fingerprint = entry.get("publicKeyPem"), entry.get("publicKeySha256")
    if (
        entry.get("algorithm") != ALGORITHM
        or not isinstance(public_key, str)
        or not isinstance(fingerprint, str)
        or not SHA256.fullmatch(fingerprint)
        or hashlib.sha256(public_key.encode("utf-8")).hexdigest() != fingerprint
    ):
        raise OperatorSignatureError("immutable operator signing registry entry is invalid")
    return entry


def _validate_private_key_path(path: Path) -> None:
    if not isinstance(path, Path) or path.is_symlink() or any(
        parent.is_symlink() and parent not in {Path("/var"), Path("/tmp")}
        for parent in path.parents
    ):
        raise OperatorSignatureError("operator private key path is unsafe")
    try:
        metadata = path.stat()
    except OSError as error:
        raise OperatorSignatureError("operator private signing key is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise OperatorSignatureError("operator private signing key permissions are unsafe")


def _decode_signature(value: Any) -> bytes:
    if not isinstance(value, str) or not BASE64URL.fullmatch(value):
        raise OperatorSignatureError("operator signature encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except (ValueError, UnicodeError) as error:
        raise OperatorSignatureError("operator signature encoding is invalid") from error
    if len(decoded) != 64:
        raise OperatorSignatureError("operator signature length is invalid")
    return decoded


def _openssl_sign(payload: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="staging-operator-signature-") as directory:
        payload_file = Path(directory) / "payload.bin"
        _write_private_temp(payload_file, payload)
        signature = _run_openssl(
            (
                "openssl", "pkeyutl", "-sign", "-rawin", "-inkey",
                str(private_key), "-in", str(payload_file),
            ),
            b"",
        )
    if len(signature) != 64:
        raise OperatorSignatureError("operator signing algorithm is not Ed25519")
    return signature


def _openssl_verify(payload: bytes, signature: bytes, public_key_pem: str) -> None:
    with tempfile.TemporaryDirectory(prefix="staging-operator-signature-") as directory:
        root = Path(directory)
        public_key, signature_file, payload_file = (
            root / "public.pem", root / "signature.bin", root / "payload.bin"
        )
        _write_private_temp(public_key, public_key_pem.encode("utf-8"))
        _write_private_temp(signature_file, signature)
        _write_private_temp(payload_file, payload)
        _run_openssl(
            (
                "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey",
                str(public_key), "-sigfile", str(signature_file), "-in", str(payload_file),
            ),
            b"",
        )


def _verify_public_key_algorithm(public_key_pem: str) -> None:
    with tempfile.TemporaryDirectory(prefix="staging-operator-public-key-") as directory:
        public_key = Path(directory) / "public.pem"
        _write_private_temp(public_key, public_key_pem.encode("utf-8"))
        text = _run_openssl(
            ("openssl", "pkey", "-pubin", "-in", str(public_key), "-text", "-noout"),
            b"",
        )
    if not text.startswith(b"ED25519 Public-Key:"):
        raise OperatorSignatureError("operator registry key is not Ed25519")


def _write_private_temp(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _run_openssl(argv: tuple[str, ...], payload: bytes) -> bytes:
    completed = subprocess.run(
        list(argv), input=payload, shell=False, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise OperatorSignatureError("offline operator signature command failed")
    return completed.stdout
