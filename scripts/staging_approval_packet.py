#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

ApprovalPhase = Literal["bootstrap", "deployment"]

PLACEHOLDER_PATTERN = re.compile(r"\$\{[A-Z0-9_]+\}")
APPROVAL_PHASES: tuple[ApprovalPhase, ...] = ("bootstrap", "deployment")
BOOTSTRAP_DEFERRED_PATHS = frozenset({
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
    "manifest.tasks.parse.targetUrl",
    "manifest.tasks.export.targetUrl",
    "manifest.operations.rollbackRevisionIds[0]",
    "manifest.operations.rollbackRevisionIds[1]",
    "manifest.operations.rollbackRevisionIds[2]",
})
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


class ApprovalPacketError(RuntimeError):
    pass


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ApprovalPacketError(f"{label} not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ApprovalPacketError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ApprovalPacketError(f"{label} root must be an object")
    return value


def validate_approval_inputs(
    manifest: dict[str, Any],
    static_report: dict[str, Any],
    live_report: dict[str, Any] | None = None,
    *,
    phase: ApprovalPhase = "deployment",
) -> list[str]:
    if phase not in APPROVAL_PHASES:
        raise ApprovalPacketError("phase must be bootstrap or deployment")
    if manifest.get("schemaVersion") != "rhwp.staging/v1":
        raise ApprovalPacketError("manifest schemaVersion must be rhwp.staging/v1")
    if manifest.get("environment") != "staging":
        raise ApprovalPacketError("manifest environment must be staging")
    operations = _mapping(manifest, "operations")
    if operations.get("cloudMutationApproved") is not False:
        raise ApprovalPacketError("operations.cloudMutationApproved must remain false")

    project_id = _string(_mapping(manifest, "project"), "id")
    _validate_report(static_report, mode="static", project_id=project_id)
    if static_report.get("status") != "pass":
        raise ApprovalPacketError("static report status must be pass")
    if static_report.get("cloudQueries") != []:
        raise ApprovalPacketError("static report cloudQueries must be empty")

    deferred_paths, blocking_paths = _classify_placeholders(manifest, phase)
    if blocking_paths:
        raise ApprovalPacketError(
            "unresolved placeholder at " + ", ".join(blocking_paths)
        )

    if phase == "bootstrap":
        if live_report is not None:
            raise ApprovalPacketError("bootstrap phase must not include a live report")
    else:
        if live_report is None:
            raise ApprovalPacketError("deployment phase requires a live report")
        _validate_report(live_report, mode="live", project_id=project_id)
        if live_report.get("status") not in {"pass", "review"}:
            raise ApprovalPacketError("live report status must be pass or review")
    return deferred_paths


def build_approval_packet(
    manifest: dict[str, Any],
    static_report: dict[str, Any],
    live_report: dict[str, Any] | None = None,
    *,
    phase: ApprovalPhase = "deployment",
) -> dict[str, Any]:
    deferred_paths = validate_approval_inputs(
        manifest,
        static_report,
        live_report,
        phase=phase,
    )
    project = _mapping(manifest, "project")
    firebase = _mapping(manifest, "firebase")
    budget = _mapping(manifest, "budget")
    operations = _mapping(manifest, "operations")
    cloud_run = _mapping(manifest, "cloudRun")
    tasks = _mapping(manifest, "tasks")
    secrets = _mapping(manifest, "secrets")
    iam = _mapping(manifest, "iam")

    if phase == "bootstrap":
        status = "ready-for-bootstrap-approval"
        generated_at = static_report.get("generatedAt")
    else:
        assert live_report is not None
        status = (
            "ready-for-deployment-approval"
            if live_report.get("status") == "pass"
            else "review-required"
        )
        generated_at = live_report.get("generatedAt")

    packet: dict[str, Any] = {
        "schemaVersion": "rhwp.staging-approval-packet/v1",
        "phase": phase,
        "generatedAt": generated_at,
        "status": status,
        "deferredValues": _deferred_value_entries(deferred_paths),
        "approval": {
            "reference": operations.get("approvalReference"),
            "cloudMutationApproved": False,
            "packetIsDeploymentApproval": False,
        },
        "project": {
            "id": project.get("id"),
            "number": project.get("number"),
            "billingAccount": project.get("billingAccount"),
            "region": project.get("region"),
            "forbiddenProjectIds": project.get("forbiddenProjectIds"),
        },
        "firebase": {
            "webAppId": firebase.get("webAppId"),
            "apiKeyReference": firebase.get("apiKeyReference"),
            "authDomain": firebase.get("authDomain"),
            "authorizedDomains": firebase.get("authorizedDomains"),
            "firestoreLocation": firebase.get("firestoreLocation"),
            "storageBucket": firebase.get("storageBucket"),
            "storageLocation": firebase.get("storageLocation"),
            "hostingSite": firebase.get("hostingSite"),
        },
        "budget": {
            "currency": budget.get("currency"),
            "amount": budget.get("amount"),
            "thresholds": budget.get("thresholds"),
            "notificationChannels": budget.get("notificationChannels"),
        },
        "iamDiff": _build_iam_diff(iam, live_report),
        "secrets": _build_secret_metadata(secrets, iam),
        "cloudRun": {
            key: _cloud_run_entry(_mapping(cloud_run, key))
            for key in ("collaboration", "documentApi", "documentWorker")
        },
        "cloudTasks": {
            "callerServiceAccount": tasks.get("callerServiceAccount"),
            "parse": _task_entry(_mapping(tasks, "parse")),
            "export": _task_entry(_mapping(tasks, "export")),
        },
        "internalFlush": {
            "decision": operations.get("internalFlushSecurityDecision"),
            "stagingBoundary": "public collaboration service with high-entropy internal token",
            "productionRecommendation": "split internal flush into a private service or private endpoint",
        },
        "rollback": {
            "deploymentStage": operations.get("deploymentStage"),
            "revisionIds": operations.get("rollbackRevisionIds"),
            "dataRetentionDays": operations.get("dataRetentionDays"),
            "automaticDeletionAllowed": False,
        },
        "acceptanceTests": _acceptance_tests(),
        "preflight": {
            "comparisonMode": "static-only" if phase == "bootstrap" else "live",
            "static": {
                "status": static_report.get("status"),
                "generatedAt": static_report.get("generatedAt"),
                "repositoryChecks": static_report.get("repositoryChecks", []),
                "warnings": static_report.get("warnings", []),
            },
            "live": (
                {
                    "status": live_report.get("status"),
                    "generatedAt": live_report.get("generatedAt"),
                    "cloudQueryCount": len(live_report.get("cloudQueries", [])),
                    "plannedChanges": live_report.get("plannedChanges", {}),
                    "warnings": live_report.get("warnings", []),
                }
                if live_report is not None
                else None
            ),
        },
        "security": {
            "readOnly": True,
            "containsCloudMutationCommands": False,
            "mutationCommands": [],
            "redactionApplied": True,
        },
    }
    return redact_sensitive(packet)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        if "-----BEGIN PRIVATE KEY-----" in value or value.startswith("Bearer "):
            return "[REDACTED]"
    return value


def render_markdown(packet: dict[str, Any]) -> str:
    safe = redact_sensitive(packet)
    phase = safe.get("phase")
    if phase not in APPROVAL_PHASES:
        raise ApprovalPacketError("packet phase must be bootstrap or deployment")
    phase_title = "Bootstrap" if phase == "bootstrap" else "Deployment"
    project = _mapping(safe, "project")
    budget = _mapping(safe, "budget")
    lines = [
        f"# rhwp Staging {phase_title} Approval Packet",
        "",
        "> This packet contains no cloud mutation commands and does not itself approve deployment.",
        "",
        f"- Phase: `{_md(phase)}`",
        f"- Status: `{_md(safe.get('status'))}`",
        f"- Approval reference: `{_md(_mapping(safe, 'approval').get('reference'))}`",
        f"- Generated at: `{_md(safe.get('generatedAt'))}`",
        "",
    ]
    deferred_values = safe.get("deferredValues", [])
    if phase == "bootstrap":
        lines.extend([
            "## Deferred values",
            "",
            "Only the resource-derived values below may remain unresolved during bootstrap approval.",
            "",
            "| Path | Reason |",
            "|---|---|",
        ])
        if isinstance(deferred_values, list):
            for item in deferred_values:
                if isinstance(item, dict):
                    lines.append(
                        f"| `{_md(item.get('path'))}` | {_md(item.get('reason'))} |"
                    )
        lines.append("")

    lines.extend([
        "## Project",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Project ID | `{_md(project.get('id'))}` |",
        f"| Project number | `{_md(project.get('number'))}` |",
        f"| Billing account | `{_md(project.get('billingAccount'))}` |",
        f"| Region | `{_md(project.get('region'))}` |",
        f"| Forbidden project IDs | {_md_list(project.get('forbiddenProjectIds'))} |",
        "",
        "## Budget",
        "",
        f"- Monthly budget: **{_md(budget.get('amount'))} {_md(budget.get('currency'))}**",
        f"- Thresholds: {_md_list(_percentages(budget.get('thresholds')))}",
        f"- Notification channels: {_md_list(budget.get('notificationChannels'))}",
        "",
        "## IAM diff",
        "",
        "| Principal | Role | Resource | State | Planned action |",
        "|---|---|---|---|---|",
    ])
    for entry in safe.get("iamDiff", []):
        lines.append(
            "| " + " | ".join(
                _md(entry.get(key))
                for key in ("principal", "role", "resource", "state", "plannedAction")
            ) + " |"
        )

    lines.extend(["", "## Secret metadata", ""])
    for key, secret in _mapping(safe, "secrets").items():
        lines.extend([
            f"### {_md(key)}",
            "",
            f"- Name: `{_md(secret.get('name'))}`",
            f"- Version: `{_md(secret.get('version'))}`",
            f"- Access principals: {_md_list(secret.get('accessPrincipals'))}",
            "",
        ])

    lines.extend(["## Cloud Run", ""])
    for key, service in _mapping(safe, "cloudRun").items():
        lines.extend([
            f"### {_md(key)}",
            "",
            f"- Service: `{_md(service.get('name'))}`",
            f"- Ingress: `{_md(service.get('ingress'))}`",
            f"- Reachability: `{_md(service.get('reachability'))}`",
            f"- Service account: `{_md(service.get('serviceAccount'))}`",
            f"- Image digest: `{_md(service.get('digest'))}`",
            f"- Runtime: `{_md(json.dumps(service.get('runtime'), sort_keys=True))}`",
            "",
        ])

    lines.extend(["## Cloud Tasks", ""])
    task_section = _mapping(safe, "cloudTasks")
    lines.append(
        f"- Caller service account: `{_md(task_section.get('callerServiceAccount'))}`"
    )
    lines.append("")
    for key in ("parse", "export"):
        queue = _mapping(task_section, key)
        lines.extend([
            f"### {_md(key)}",
            "",
            f"- Queue: `{_md(queue.get('name'))}`",
            f"- Location: `{_md(queue.get('location'))}`",
            f"- Target: `{_md(queue.get('targetUrl'))}`",
            f"- Dispatch deadline: `{_md(queue.get('dispatchDeadlineSeconds'))}` seconds",
            f"- Retry: `{_md(json.dumps(queue.get('retry'), sort_keys=True))}`",
            f"- Rate limits: `{_md(json.dumps(queue.get('rateLimits'), sort_keys=True))}`",
            "",
        ])

    internal = _mapping(safe, "internalFlush")
    rollback = _mapping(safe, "rollback")
    lines.extend([
        "## Internal flush security",
        "",
        f"- Decision: `{_md(internal.get('decision'))}`",
        f"- Staging boundary: {_md(internal.get('stagingBoundary'))}",
        f"- Production recommendation: {_md(internal.get('productionRecommendation'))}",
        "",
        "## Rollback",
        "",
        f"- Revision IDs: {_md_list(rollback.get('revisionIds'))}",
        f"- Data retention days: `{_md(rollback.get('dataRetentionDays'))}`",
        "- Automatic deletion: forbidden",
        "",
        "## Acceptance tests",
        "",
    ])
    for item in safe.get("acceptanceTests", []):
        lines.append(
            f"- [ ] **{_md(item.get('id'))}** — {_md(item.get('name'))}: {_md(item.get('expected'))}"
        )

    preflight = _mapping(safe, "preflight")
    static = _mapping(preflight, "static")
    live = preflight.get("live")
    lines.extend([
        "",
        "## Preflight evidence",
        "",
        f"- Comparison mode: `{_md(preflight.get('comparisonMode'))}`",
        f"- Static status: `{_md(static.get('status'))}`",
        f"- Static checks: {_md_list(static.get('repositoryChecks'))}",
    ])
    if isinstance(live, dict):
        lines.extend([
            f"- Live status: `{_md(live.get('status'))}`",
            f"- Read-only cloud query count: `{_md(live.get('cloudQueryCount'))}`",
            f"- Live warnings: {_md_list(live.get('warnings'))}",
            f"- Planned changes: `{_md(json.dumps(live.get('plannedChanges'), sort_keys=True))}`",
        ])
    lines.extend([
        "",
        "## Security assertion",
        "",
        "- The generator reads JSON files only.",
        "- The generated packet contains no cloud mutation commands.",
        "- Secret values, tokens, credentials, authorization data, passwords, and private keys are redacted.",
        "- A separate explicit approval is required before any cloud resource creation or deployment.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate read-only rhwp staging approval packet artifacts"
    )
    parser.add_argument(
        "--phase",
        choices=APPROVAL_PHASES,
        default="deployment",
        help=(
            "bootstrap permits only approved deferred resource values; "
            "deployment requires live evidence and concrete values"
        ),
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--static-report", type=Path, required=True)
    parser.add_argument("--live-report", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_json_object(args.manifest, "staging manifest")
        static_report = load_json_object(args.static_report, "static preflight report")
        live_report = (
            load_json_object(args.live_report, "live preflight report")
            if args.live_report is not None
            else None
        )
        packet = build_approval_packet(
            manifest,
            static_report,
            live_report,
            phase=args.phase,
        )
        markdown = render_markdown(packet)
        _atomic_write(
            args.json_output,
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write(args.markdown_output, markdown)
    except (ApprovalPacketError, OSError) as error:
        print(f"staging approval packet failed: {error}", file=sys.stderr)
        return 1

    legacy_status = (
        "ready-for-approval"
        if packet["status"] in {
            "ready-for-bootstrap-approval",
            "ready-for-deployment-approval",
        }
        else packet["status"]
    )
    print(json.dumps({
        "status": legacy_status,
        "packetStatus": packet["status"],
        "phase": packet["phase"],
        "projectId": packet["project"]["id"],
        "jsonOutput": str(args.json_output),
        "markdownOutput": str(args.markdown_output),
        "mutationCommands": [],
    }, ensure_ascii=False))
    return 0


def _validate_report(report: dict[str, Any], *, mode: str, project_id: str) -> None:
    if report.get("schemaVersion") != "rhwp.preflight-report/v1":
        raise ApprovalPacketError(
            f"{mode} report schemaVersion must be rhwp.preflight-report/v1"
        )
    if report.get("mode") != mode:
        raise ApprovalPacketError(f"{mode} report mode must be {mode}")
    if report.get("projectId") != project_id:
        raise ApprovalPacketError(
            f"{mode} report projectId must match manifest project.id"
        )
    if report.get("mutationCommands") != []:
        raise ApprovalPacketError(f"{mode} report mutationCommands must be empty")


def _find_placeholder_paths(value: Any, path: str = "manifest") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            paths.extend(_find_placeholder_paths(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_find_placeholder_paths(item, f"{path}[{index}]"))
    elif isinstance(value, str) and PLACEHOLDER_PATTERN.search(value):
        paths.append(path)
    return paths


def _classify_placeholders(
    manifest: dict[str, Any],
    phase: ApprovalPhase,
) -> tuple[list[str], list[str]]:
    paths = sorted(_find_placeholder_paths(manifest))
    if phase == "bootstrap":
        deferred = [path for path in paths if path in BOOTSTRAP_DEFERRED_PATHS]
        blocking = [path for path in paths if path not in BOOTSTRAP_DEFERRED_PATHS]
        return deferred, blocking
    return [], paths


def _deferred_value_entries(paths: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in paths:
        if path == "manifest.project.number":
            reason = "resolved when the staging project exists"
        elif path.startswith("manifest.firebase."):
            reason = "resolved after Firebase resource creation"
        elif path.startswith("manifest.cloudRun."):
            reason = "resolved after image build and digest lookup"
        elif path.startswith("manifest.tasks."):
            reason = "resolved after the document worker endpoint exists"
        elif path.startswith("manifest.operations.rollbackRevisionIds"):
            reason = "resolved after the first Cloud Run deployment"
        else:
            reason = "resolved before deployment approval"
        entries.append({"path": path, "reason": reason})
    return entries


def _build_iam_diff(
    iam: dict[str, Any],
    live_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    bindings = iam.get("bindings")
    if not isinstance(bindings, list):
        raise ApprovalPacketError("iam.bindings must be an array")
    existing = _existing_project_iam_bindings(live_report)
    result: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ApprovalPacketError("iam.bindings entries must be objects")
        principal = _string(binding, "principal")
        role = _string(binding, "role")
        resource = _string(binding, "resource")
        if resource == "project" and live_report is not None:
            present = (role, principal) in existing
            state = "present" if present else "missing"
            action = "none" if present else "grant-after-approval"
        else:
            state = "not-observed"
            action = "verify-before-grant"
        result.append({
            "principal": principal,
            "role": role,
            "resource": resource,
            "state": state,
            "plannedAction": action,
        })
    return result


def _existing_project_iam_bindings(
    live_report: dict[str, Any] | None,
) -> set[tuple[str, str]]:
    if live_report is None:
        return set()
    cloud_state = live_report.get("cloudState")
    if not isinstance(cloud_state, dict):
        return set()
    policy = cloud_state.get("iamPolicy")
    if not isinstance(policy, dict):
        return set()
    bindings = policy.get("bindings")
    if not isinstance(bindings, list):
        return set()
    result: set[tuple[str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get("role"), str):
            continue
        members = binding.get("members")
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, str):
                result.add((binding["role"], member))
    return result


def _build_secret_metadata(
    secrets: dict[str, Any],
    iam: dict[str, Any],
) -> dict[str, Any]:
    bindings = iam.get("bindings", [])
    result: dict[str, Any] = {}
    for key, value in secrets.items():
        if not isinstance(value, dict):
            raise ApprovalPacketError(f"secrets.{key} must be an object")
        name = _string(value, "name")
        principals = sorted({
            binding.get("principal")
            for binding in bindings
            if isinstance(binding, dict)
            and binding.get("role") == "roles/secretmanager.secretAccessor"
            and binding.get("resource") == f"secret:{name}"
            and isinstance(binding.get("principal"), str)
        })
        result[key] = {
            "name": name,
            "version": _string(value, "version"),
            "accessPrincipals": principals,
            "valueIncluded": False,
        }
    return result


def _cloud_run_entry(service: dict[str, Any]) -> dict[str, Any]:
    ingress = _string(service, "ingress")
    return {
        "name": _string(service, "name"),
        "image": _string(service, "image"),
        "digest": _string(service, "digest"),
        "serviceAccount": _string(service, "serviceAccount"),
        "ingress": ingress,
        "reachability": (
            "internet-reachable-application-auth-required"
            if ingress == "all"
            else "internal-only"
        ),
        "runtime": _mapping(service, "runtime"),
    }


def _task_entry(queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _string(queue, "name"),
        "location": _string(queue, "location"),
        "targetUrl": _string(queue, "targetUrl"),
        "dispatchDeadlineSeconds": queue.get("dispatchDeadlineSeconds"),
        "retry": _mapping(queue, "retry"),
        "rateLimits": _mapping(queue, "rateLimits"),
    }


def _acceptance_tests() -> list[dict[str, str]]:
    rows = (
        ("auth-acl", "Google sign-in and ACL", "owner, editor, and viewer permissions are enforced"),
        ("upload", "HWP upload", "owner uploads a supported non-empty HWP no larger than 200 MiB"),
        ("parse", "Parse worker", "the document reaches ready state without duplicate processing"),
        ("share", "Share-link acceptance", "a second account accepts a valid link and receives the intended role"),
        ("two-browser", "Two-browser concurrent editing", "both browser contexts converge on the same text and table-cell state"),
        ("reconnect", "WebSocket reconnect", "re-authentication and Yjs synchronization restore converged state"),
        ("recovery", "Collaboration restart recovery", "the latest snapshot restores after service restart"),
        ("export", "HWPX export", "owner or editor receives a ready export generated from the flushed snapshot"),
        ("reimport", "Exported HWPX re-import", "the exported file parses successfully as a new source"),
        ("preservation", "Content preservation", "edits persist and readonly complex objects remain preserved"),
        ("rollback", "Rollback readiness", "all three approved Cloud Run revision IDs are available for rollback"),
    )
    return [
        {"id": identifier, "name": name, "expected": expected, "status": "pending"}
        for identifier, name, expected in rows
    ]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ApprovalPacketError(f"{key} must be an object")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ApprovalPacketError(f"{key} must be a non-empty string")
    return item


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _md_list(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return ", ".join(f"`{_md(item)}`" for item in value)


def _percentages(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [f"{round(float(item) * 100)}%" for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
