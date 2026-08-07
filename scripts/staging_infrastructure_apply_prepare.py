#!/usr/bin/env python3
"""Create the run-bound evidence artifact before the protected apply gate."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.staging_infrastructure_apply_approval import (
    MutationApprovalError,
    bind_run_approval,
)
from scripts.staging_infrastructure_operator_attestation import OperatorAttestationError
from scripts.staging_infrastructure_validation import (
    StrictJsonError,
    parse_strict_json_bytes,
)

MAX_REPOSITORY_VARIABLE_BYTES = 48 * 1024
MAX_JSON_BYTES = 1_000_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BASE64 = re.compile(rb"^[A-Za-z0-9+/]*={0,2}$")


class ApplyPrepareError(RuntimeError):
    pass


def decode_base64_file(path: Path, label: str) -> bytes:
    """Decode one repository-variable value without normalizing its payload."""
    try:
        encoded = path.read_bytes()
    except OSError as error:
        raise ApplyPrepareError(f"{label} could not be read") from error
    if not encoded or len(encoded) > MAX_REPOSITORY_VARIABLE_BYTES:
        raise ApplyPrepareError(f"{label} exceeds the repository-variable size limit")
    if b"\n" in encoded or b"\r" in encoded or not BASE64.fullmatch(encoded):
        raise ApplyPrepareError(f"{label} must be one-line strict base64")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ApplyPrepareError(f"{label} is not valid base64") from error
    if not decoded or len(decoded) > MAX_JSON_BYTES:
        raise ApplyPrepareError(f"{label} decoded JSON exceeds the size limit")
    return decoded


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = parse_strict_json_bytes(raw, label)
    except StrictJsonError as error:
        raise ApplyPrepareError(str(error)) from error
    if not isinstance(value, dict):
        raise ApplyPrepareError(f"{label} root must be an object")
    return value


def _write_exact_new(path: Path, raw: bytes) -> None:
    """Publish exact package bytes only to a new, non-symlink file."""
    if path.exists() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ApplyPrepareError("prepare output must be a new non-symlink file")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink() or temporary.is_symlink():
            raise ApplyPrepareError("prepare output changed during publication")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ApplyPrepareError("could not publish prepare output") from error


def prepare_run_bound_evidence(
    package_b64_file: Path,
    declaration_b64_file: Path,
    *,
    expected_package_sha256: str,
    run_id: str,
    run_attempt: int,
    package_output: Path,
    approval_output: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate repository inputs and bind them to the already-created run."""
    if not isinstance(expected_package_sha256, str) or not SHA256.fullmatch(expected_package_sha256):
        raise ApplyPrepareError("expected package SHA-256 is invalid")
    package_bytes = decode_base64_file(package_b64_file, "apply-ready package variable")
    declaration_bytes = decode_base64_file(
        declaration_b64_file, "approval declaration variable"
    )
    if hashlib.sha256(package_bytes).hexdigest() != expected_package_sha256:
        raise ApplyPrepareError("workflow package SHA-256 does not match exact package bytes")
    package = _json_object(package_bytes, "apply-ready package")
    declaration = _json_object(declaration_bytes, "approval declaration")
    try:
        approval = bind_run_approval(
            package,
            package_bytes,
            declaration,
            run_id=run_id,
            run_attempt=run_attempt,
            now=now,
        )
    except MutationApprovalError as error:
        raise ApplyPrepareError(str(error)) from error
    _write_exact_new(package_output, package_bytes)
    try:
        from scripts.staging_infrastructure_operator_attestation import write_new_canonical_json

        write_new_canonical_json(approval_output, approval)
    except (OSError, OperatorAttestationError) as error:
        raise ApplyPrepareError("could not publish run-bound approval") from error
    return {
        "status": "prepared-run-bound-evidence",
        "runId": run_id,
        "runAttempt": run_attempt,
        "packageSha256": hashlib.sha256(package_bytes).hexdigest(),
        "approvalSchemaVersion": approval["schemaVersion"],
        "artifactName": "staging-infrastructure-approved-evidence",
        "cloudMutationApproved": False,
        "deploymentApproved": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind a reviewed package to the current GitHub run before protected apply"
    )
    parser.add_argument("--package-b64-file", type=Path, required=True)
    parser.add_argument("--approval-declaration-b64-file", type=Path, required=True)
    parser.add_argument("--expected-package-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--package-output", type=Path, required=True)
    parser.add_argument("--approval-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_run_bound_evidence(
            args.package_b64_file,
            args.approval_declaration_b64_file,
            expected_package_sha256=args.expected_package_sha256,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            package_output=args.package_output,
            approval_output=args.approval_output,
        )
    except (ApplyPrepareError, OSError, ValueError) as error:
        print(f"staging apply prepare failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
