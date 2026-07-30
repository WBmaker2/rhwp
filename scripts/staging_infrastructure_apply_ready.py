#!/usr/bin/env python3
"""Promote reviewed evidence only through fixed live operator attestations."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.staging_infrastructure_apply_approval import (
    APPLY_READY_SCHEMA,
    MutationApprovalError,
    SCHEMA,
    _validate_review_package,
    validate_apply_ready_package,
)
from scripts.staging_infrastructure_apply_safety import (
    ApplySafetyError,
    reject_sensitive_string_leaves,
)
from scripts.staging_infrastructure_environment_attestation import (
    EnvironmentAttestationError,
    attest_environment,
)
from scripts.staging_infrastructure_operator_attestation import (
    IssuedOperatorAttestation,
    OperatorAttestationError,
    issued_attestation_document,
    write_new_canonical_json,
)
from scripts.staging_infrastructure_operator_signature import (
    OperatorSignatureError,
    preflight_operator_signature,
    sign_operator_attestation,
    signed_attestation_sha256,
)
from scripts.staging_infrastructure_validation import (
    StrictJsonError,
    read_bounded_json_file,
    validate_json_domain,
)
from scripts.staging_infrastructure_wif_attestation import (
    WifAttestationError,
    attest_wif,
)


class ApplyReadyError(RuntimeError):
    pass


def build_apply_ready_package(
    review: dict[str, Any], review_bytes: bytes,
    environment_attestation: IssuedOperatorAttestation,
    wif_attestation: IssuedOperatorAttestation, *,
    operator_signing_key_id: str | None = None,
    operator_signing_private_key: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the exact package form after operator tools supplied both objects.

    The receipt type rejects caller-supplied observation dictionaries. The
    public CLI below obtains receipts only from the fixed-query tools.
    """
    try:
        environment = issued_attestation_document(environment_attestation)
        wif = issued_attestation_document(wif_attestation)
        validate_json_domain(review)
        validate_json_domain(environment)
        validate_json_domain(wif)
        reject_sensitive_string_leaves(review, "review package")
        reject_sensitive_string_leaves(environment, "environment attestation")
        reject_sensitive_string_leaves(wif, "WIF attestation")
        _validate_review_package(review)
    except (
        StrictJsonError,
        ApplySafetyError,
        MutationApprovalError,
        OperatorAttestationError,
    ) as error:
        raise ApplyReadyError("promotion inputs are invalid") from error
    if not isinstance(review_bytes, bytes) or len(review_bytes) > 1_000_000:
        raise ApplyReadyError("review package bytes are invalid")
    if not isinstance(operator_signing_key_id, str) or not isinstance(operator_signing_private_key, Path):
        raise ApplyReadyError("operator signing proof is required for promotion")
    try:
        signed_environment = sign_operator_attestation(
            environment,
            key_id=operator_signing_key_id,
            private_key=operator_signing_private_key,
        )
        signed_wif = sign_operator_attestation(
            wif,
            key_id=operator_signing_key_id,
            private_key=operator_signing_private_key,
        )
    except OperatorSignatureError as error:
        raise ApplyReadyError("operator signing proof is invalid") from error
    result = {
        "schemaVersion": APPLY_READY_SCHEMA,
        "status": "ready-for-approved-apply",
        "reviewPackageSha256": hashlib.sha256(review_bytes).hexdigest(),
        "reviewPackage": review,
        "environmentAttestation": signed_environment,
        "environmentAttestationSha256": signed_attestation_sha256(signed_environment),
        "wifAttestation": signed_wif,
        "wifAttestationSha256": signed_attestation_sha256(signed_wif),
        "requiredApprovalRecordSchema": SCHEMA,
        "cloudMutationApproved": False,
        "deploymentApproved": False,
        "mutationCommands": [],
    }
    try:
        validate_apply_ready_package(result, now=now)
    except MutationApprovalError as error:
        raise ApplyReadyError("fixed-query live attestations are not apply-ready") from error
    return result


def build_operator_apply_ready_package(
    review: dict[str, Any], review_bytes: bytes, *, project_id: str,
    provider_resource_name: str, service_account: str,
    operator_signing_key_id: str,
    operator_signing_private_key: Path,
    environment_attestor: Callable[..., IssuedOperatorAttestation] = attest_environment,
    wif_attestor: Callable[..., IssuedOperatorAttestation] = attest_wif,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive attestation inputs from trusted fixed-query tools, not caller JSON."""
    try:
        preflight_operator_signature(
            operator_signing_key_id, operator_signing_private_key
        )
        _validate_review_package(review)
    except (MutationApprovalError, OperatorSignatureError) as error:
        raise ApplyReadyError("review package or operator signing configuration is invalid") from error
    if project_id != review["projectId"]:
        raise ApplyReadyError("operator project differs from the reviewed package")
    try:
        environment = environment_attestor(now=now)
        environment_document = issued_attestation_document(environment)
        wif = wif_attestor(
            project_id=project_id,
            provider_resource_name=provider_resource_name,
            service_account=service_account,
            repository_id=environment_document["repositoryId"],
            repository_owner_id=environment_document["repositoryOwnerId"],
            workflow_sha=review["executorCommit"]["sha"],
            now=now,
        )
    except (
        EnvironmentAttestationError,
        WifAttestationError,
        OperatorAttestationError,
        KeyError,
        TypeError,
    ) as error:
        raise ApplyReadyError("operator read-only attestation failed") from error
    return build_apply_ready_package(
        review,
        review_bytes,
        environment,
        wif,
        operator_signing_key_id=operator_signing_key_id,
        operator_signing_private_key=operator_signing_private_key,
        now=now,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote reviewed evidence using fixed read-only operator attestations"
    )
    parser.add_argument("--review-package", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--provider-resource-name", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--operator-signing-key-id", required=True)
    parser.add_argument("--operator-signing-private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        review, raw = read_bounded_json_file(args.review_package, "review package")
        if not isinstance(review, dict):
            raise ApplyReadyError("review package must be a JSON object")
        package = build_operator_apply_ready_package(
            review,
            raw,
            project_id=args.project_id,
            provider_resource_name=args.provider_resource_name,
            service_account=args.service_account,
            operator_signing_key_id=args.operator_signing_key_id,
            operator_signing_private_key=args.operator_signing_private_key,
        )
        write_new_canonical_json(args.output, package)
    except (
        ApplyReadyError,
        EnvironmentAttestationError,
        WifAttestationError,
        OperatorAttestationError,
        OSError,
        StrictJsonError,
    ) as error:
        print(f"staging apply-ready promotion failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": package["status"], "output": str(args.output),
        "cloudMutationApproved": False, "deploymentApproved": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
