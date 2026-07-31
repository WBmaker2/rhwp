#!/usr/bin/env python3
"""Create a sanitized Environment attestation from fixed read-only GitHub APIs.

The normal CLI has no JSON observation input and does not print raw API output.
Only unit tests may inject a runner that returns synthetic bytes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.staging_infrastructure_apply_review_policy import REPOSITORY, protected_environment_spec
from scripts.staging_infrastructure_operator_attestation import (
    ATTESTATION_ENCODING,
    ENVIRONMENT_ATTESTATION_SCHEMA,
    ENVIRONMENT_QUERY_CONTRACT,
    MAX_ATTESTATION_TTL,
    NUMERIC_ID,
    IssuedOperatorAttestation,
    OperatorAttestationError,
    environment_required_contract,
    _issue_fixed_query_attestation,
    response_sha256,
    utc_now,
    utc_text,
    validate_environment_attestation,
    write_new_attestation,
)
from scripts.staging_infrastructure_validation import StrictJsonError, parse_strict_json_bytes

OWNER, REPO = REPOSITORY.split("/", 1)
ENVIRONMENT = protected_environment_spec()["name"]
API_VERSION = "2026-03-10"
GITHUB_HOST = "github.com"
PAGE_SIZE = 30
MAX_PAGES = 100
Runner = Callable[[tuple[str, ...]], bytes]


class EnvironmentAttestationError(RuntimeError):
    pass


def attest_environment(
    *, runner: Runner | None = None, now: datetime | None = None
) -> IssuedOperatorAttestation:
    """Query only fixed GitHub read endpoints and verify the complete contract."""
    run = runner or _run_fixed_gh
    try:
        repository_raw = run(_gh_argv(f"/repos/{OWNER}/{REPO}"))
        environment_raw = run(_gh_argv(f"/repos/{OWNER}/{REPO}/environments/{ENVIRONMENT}"))
        repository = _json_object(repository_raw, "repository")
        environment = _json_object(environment_raw, "environment")
        branch_pages, branch_policies = _collect_pages(
            run,
            f"/repos/{OWNER}/{REPO}/environments/{ENVIRONMENT}/deployment-branch-policies",
            "branch_policies",
        )
        variable_pages, variables = _collect_pages(
            run,
            f"/repos/{OWNER}/{REPO}/environments/{ENVIRONMENT}/variables",
            "variables",
        )
        result = _build_attestation(
            repository,
            environment,
            branch_policies,
            variables,
            response_digests={
                "repository": response_sha256(repository_raw),
                "environment": response_sha256(environment_raw),
                "branchPolicyPages": [response_sha256(item) for item in branch_pages],
                "variablePages": [response_sha256(item) for item in variable_pages],
            },
            now=now or utc_now(),
        )
        validate_environment_attestation(result, now=now or utc_now())
        return _issue_fixed_query_attestation(result)
    except (EnvironmentAttestationError, OperatorAttestationError):
        raise
    except Exception as error:
        raise EnvironmentAttestationError("GitHub Environment read-only query failed") from error


def _build_attestation(
    repository: dict[str, Any], environment: dict[str, Any],
    branch_policies: list[dict[str, Any]], variables: list[dict[str, Any]], *,
    response_digests: dict[str, Any], now: datetime,
) -> dict[str, Any]:
    repo_id, owner_id = _numeric(repository.get("id")), _numeric(repository.get("owner", {}).get("id") if isinstance(repository.get("owner"), dict) else None)
    environment_id = _numeric(environment.get("id"))
    if repository.get("full_name") != REPOSITORY or not all((repo_id, owner_id, environment_id)):
        raise EnvironmentAttestationError("GitHub repository or Environment identity is invalid")
    if environment.get("name") != ENVIRONMENT:
        raise EnvironmentAttestationError("GitHub Environment name differs from the fixed contract")
    required = _required_reviewers(environment)
    policy = environment.get("deployment_branch_policy")
    expected = environment_required_contract()
    if policy != {
        "protected_branches": expected["deploymentBranchPolicy"]["protectedBranches"],
        "custom_branch_policies": expected["deploymentBranchPolicy"]["customBranchPolicies"],
    }:
        raise EnvironmentAttestationError("GitHub Environment branch policy mode is not exact")
    observed_branches = sorted(_branch_policy(item) for item in branch_policies)
    if observed_branches != expected["deploymentBranchPolicy"]["branchPolicies"]:
        raise EnvironmentAttestationError("GitHub Environment branch policy names are not exact")
    names = sorted(_variable_name(item) for item in variables)
    if names != expected["variableNames"] or len(set(names)) != len(names):
        raise EnvironmentAttestationError("GitHub Environment variable names are not exact")
    admin_bypass = _admin_bypass_observation(environment)
    return {
        "schemaVersion": ENVIRONMENT_ATTESTATION_SCHEMA,
        "queryContractVersion": ENVIRONMENT_QUERY_CONTRACT,
        "status": "verified",
        "verified": True,
        "encoding": ATTESTATION_ENCODING,
        "environmentName": ENVIRONMENT,
        "repository": REPOSITORY,
        "repositoryId": repo_id,
        "repositoryOwnerId": owner_id,
        "environmentId": environment_id,
        "requiredContract": expected,
        "observed": {
            "requiredReviewerCount": required,
            "preventSelfReview": False,
            "canAdminsBypass": admin_bypass,
            "deploymentBranchPolicy": expected["deploymentBranchPolicy"],
            "variableNames": expected["variableNames"],
        },
        "responseDigests": response_digests,
        "observedAt": utc_text(now),
        "expiresAt": utc_text(now + MAX_ATTESTATION_TTL),
    }


def _required_reviewers(environment: dict[str, Any]) -> int:
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        raise EnvironmentAttestationError("GitHub Environment protection rules are unavailable")
    matching = [item for item in rules if isinstance(item, dict) and item.get("type") == "required_reviewers"]
    if len(matching) != 1:
        raise EnvironmentAttestationError("GitHub Environment required-reviewer rule is invalid")
    rule = matching[0]
    reviewers = rule.get("reviewers")
    if rule.get("prevent_self_review") is not False or not isinstance(reviewers, list) or not reviewers:
        raise EnvironmentAttestationError("GitHub Environment reviewer or self-review policy is invalid")
    return len(reviewers)


def _admin_bypass_observation(environment: dict[str, Any]) -> bool | str:
    """Record only an exact false value or the approved official-REST omission."""
    if "can_admins_bypass" not in environment:
        return "unavailable-in-official-rest"
    if environment["can_admins_bypass"] is False:
        return False
    raise EnvironmentAttestationError(
        "GitHub admin-bypass state is unsafe or malformed"
    )


def _collect_pages(run: Runner, endpoint: str, key: str) -> tuple[list[bytes], list[dict[str, Any]]]:
    pages: list[bytes] = []
    entries: list[dict[str, Any]] = []
    expected_total: int | None = None
    for page in range(1, MAX_PAGES + 1):
        raw = run(_gh_argv(f"{endpoint}?per_page={PAGE_SIZE}&page={page}"))
        body = _json_object(raw, "GitHub pagination response")
        total = body.get("total_count")
        items = body.get(key)
        if isinstance(total, bool) or not isinstance(total, int) or total < 0 or not isinstance(items, list):
            raise EnvironmentAttestationError("GitHub pagination response is malformed")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise EnvironmentAttestationError("GitHub pagination total changed during attestation")
        if any(not isinstance(item, dict) for item in items):
            raise EnvironmentAttestationError("GitHub pagination item is malformed")
        pages.append(raw)
        entries.extend(items)
        if len(entries) >= total:
            if len(entries) != total:
                raise EnvironmentAttestationError("GitHub pagination returned too many items")
            return pages, entries
        if not items:
            raise EnvironmentAttestationError("GitHub pagination ended before total_count")
    raise EnvironmentAttestationError("GitHub pagination exceeds the fixed safety limit")


def _gh_argv(endpoint: str) -> tuple[str, ...]:
    return (
        "gh", "api", "--hostname", GITHUB_HOST, "--method", "GET",
        "--header", "Accept: application/vnd.github+json",
        "--header", f"X-GitHub-Api-Version: {API_VERSION}", endpoint,
    )


def _run_fixed_gh(argv: tuple[str, ...]) -> bytes:
    completed = subprocess.run(
        list(argv), shell=False, check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise EnvironmentAttestationError("fixed GitHub read-only command failed")
    return completed.stdout


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = parse_strict_json_bytes(raw, label)
    except StrictJsonError as error:
        raise EnvironmentAttestationError("GitHub read-only response is not strict JSON") from error
    if not isinstance(value, dict):
        raise EnvironmentAttestationError("GitHub read-only response must be an object")
    return value


def _numeric(value: Any) -> str | None:
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    return text if isinstance(text, str) and NUMERIC_ID.fullmatch(text) else None


def _branch_policy(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value.get("name"), str) or value.get("type") not in {"branch", "tag"}:
        raise EnvironmentAttestationError("GitHub branch policy item is invalid")
    return {"name": value["name"], "type": value["type"]}


def _variable_name(value: dict[str, Any]) -> str:
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise EnvironmentAttestationError("GitHub Environment variable item is invalid")
    return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attest the fixed staging Environment with read-only gh api")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_new_attestation(args.output, attest_environment().document)
    except (EnvironmentAttestationError, OperatorAttestationError, OSError) as error:
        print(f"staging Environment attestation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "verified", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
