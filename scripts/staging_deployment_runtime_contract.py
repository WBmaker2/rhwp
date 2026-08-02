#!/usr/bin/env python3
"""Bounded runtime configuration for the staging Cloud Run services.

The deployment packet contains immutable image identities and the observed worker
targets, but it never contains secret values.  This module derives only the
approved non-secret environment values and Secret Manager references needed by
the Cloud Run templates.  Collaboration's URL is accepted only after it has
been returned by a read-after-deploy observation; it is never guessed.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


class RuntimeContractError(RuntimeError):
    """Raised when a service cannot be rendered from approved observations."""


SECRET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,254}$")
SERVICE_URL_RE = re.compile(r"^https://[a-z0-9-]+\.a\.run\.app$")


def cloud_run_runtime_configuration(
    project_id: str,
    resource: dict[str, Any],
    prepared: dict[str, Any],
    observed_urls: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Return exact env and secret-reference maps for one approved service."""
    firebase = prepared.get("firebase")
    if not isinstance(firebase, dict):
        raise RuntimeContractError("prepared firebase configuration is missing")
    bucket = _safe_value(firebase.get("storageBucket"), "FIREBASE_STORAGE_BUCKET")
    secret_name = _safe_secret(prepared.get("secretName"))
    name = resource.get("name")

    if name == "rhwp-collaboration-staging":
        return {
            "env": {"FIREBASE_STORAGE_BUCKET": bucket},
            "secrets": {"INTERNAL_API_TOKEN": f"{secret_name}:latest"},
        }

    if name == "rhwp-document-worker-staging":
        return {
            "env": {
                "FIREBASE_STORAGE_BUCKET": bucket,
                "RHWP_COLLABORATION_WORKER_BIN": "/usr/local/bin/rhwp-collaboration-worker",
                "ALLOW_EMULATOR_TASKS": "false",
            },
            "secrets": {},
        }

    if name == "rhwp-document-api-staging":
        tasks = prepared.get("cloudTasks")
        if not isinstance(tasks, dict):
            raise RuntimeContractError("prepared cloudTasks configuration is missing")
        parse = _worker_target(tasks, "parse", "/run/parse")
        export = _worker_target(tasks, "export", "/run/export")
        collaboration_url = observed_urls.get("cloud-run-collaboration", "")
        collaboration_url = _service_url(collaboration_url, "collaboration service URL")
        caller = _safe_value(tasks.get("callerServiceAccount"), "TASKS_SERVICE_ACCOUNT_EMAIL")
        return {
            "env": {
                "GCP_PROJECT_ID": _safe_value(project_id, "GCP_PROJECT_ID"),
                "GCP_LOCATION": "asia-northeast3",
                "FIREBASE_STORAGE_BUCKET": bucket,
                "PARSE_QUEUE": _safe_value(tasks.get("parse", {}).get("name"), "PARSE_QUEUE"),
                "PARSE_WORKER_URL": parse,
                "EXPORT_QUEUE": _safe_value(tasks.get("export", {}).get("name"), "EXPORT_QUEUE"),
                "EXPORT_WORKER_URL": export,
                "TASKS_SERVICE_ACCOUNT_EMAIL": caller,
                "TASK_DISPATCH_DEADLINE_SECONDS": "900",
                "COLLABORATION_FLUSH_URL": collaboration_url,
            },
            "secrets": {"COLLABORATION_INTERNAL_TOKEN": f"{secret_name}:latest"},
        }

    raise RuntimeContractError(f"unsupported Cloud Run service: {name}")


def cloud_run_deploy_argv(
    project_id: str,
    resource: dict[str, Any],
    prepared: dict[str, Any],
    observed_urls: dict[str, str],
    *,
    region: str = "asia-northeast3",
) -> tuple[str, ...]:
    """Build a fixed gcloud argv without secret values or shell evaluation."""
    runtime = resource.get("runtime")
    if not isinstance(runtime, dict):
        raise RuntimeContractError("Cloud Run runtime is missing")
    configuration = cloud_run_runtime_configuration(project_id, resource, prepared, observed_urls)
    argv: list[str] = [
        "gcloud", "run", "deploy", _safe_value(resource.get("name"), "service name"),
        f"--image={_safe_value(resource.get('image'), 'image')}@sha256:{_safe_value(resource.get('digest'), 'image digest')}",
        f"--region={region}", f"--project={project_id}",
        f"--service-account={_safe_value(resource.get('serviceAccount'), 'service account')}",
        f"--ingress={_safe_value(resource.get('ingress'), 'ingress')}",
        f"--cpu={_safe_value(runtime.get('cpu'), 'cpu')}",
        f"--memory={_safe_value(runtime.get('memory'), 'memory')}",
        f"--concurrency={runtime.get('containerConcurrency')}",
        f"--timeout={runtime.get('timeoutSeconds')}s",
        f"--min={runtime.get('minScale')}", f"--max={runtime.get('maxScale')}",
        f"--set-env-vars={_pairs(configuration['env'])}",
        "--no-allow-unauthenticated", "--quiet",
    ]
    if configuration["secrets"]:
        argv.insert(-2, f"--set-secrets={_pairs(configuration['secrets'])}")
    return tuple(argv)


def _worker_target(tasks: dict[str, Any], key: str, suffix: str) -> str:
    value = tasks.get(key)
    if not isinstance(value, dict):
        raise RuntimeContractError(f"prepared cloudTasks.{key} is missing")
    target = _safe_value(value.get("targetUrl"), f"{key} target URL")
    parsed = urlparse(target)
    if parsed.scheme != "https" or not parsed.netloc.endswith(".a.run.app") or parsed.path != suffix:
        raise RuntimeContractError(f"{key} target URL is not an observed Cloud Run URL")
    return target


def _service_url(value: str, label: str) -> str:
    if not SERVICE_URL_RE.fullmatch(value):
        raise RuntimeContractError(f"{label} must be an observed default run.app URL")
    return value


def _safe_secret(value: Any) -> str:
    if not isinstance(value, str) or not SECRET_RE.fullmatch(value.strip()):
        raise RuntimeContractError("Secret Manager name is invalid")
    return value.strip()


def _safe_value(value: Any, label: str) -> str:
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise RuntimeContractError(f"{label} is missing")
    normalized = str(value).strip()
    if any(char in normalized for char in ("\n", "\r", ",")):
        raise RuntimeContractError(f"{label} contains an unsafe delimiter")
    return normalized


def _pairs(values: dict[str, str]) -> str:
    return ",".join(f"{key}={value}" for key, value in values.items())
