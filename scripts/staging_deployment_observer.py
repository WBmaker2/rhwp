#!/usr/bin/env python3
"""Fixed, read-only observers for the staging deployment executor."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from scripts.staging_deployment_runtime_contract import (
    RuntimeContractError,
    cloud_run_runtime_configuration,
)


class DeploymentObserverError(RuntimeError):
    """Raised when a cloud observation is unavailable or ambiguous."""


REGION = "asia-northeast3"


def _read_json(argv: tuple[str, ...], *, not_found_ok: bool = True) -> Any:
    completed = subprocess.run(list(argv), shell=False, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.lower()
        if not_found_ok and (
            "not found" in stderr
            or "not_found" in stderr
            or "does not exist" in stderr
            or "cannot find service" in stderr
        ):
            return None
        raise DeploymentObserverError("read-only cloud observation failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DeploymentObserverError("read-only cloud observation was not structured JSON") from error


def _deep(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _seconds(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        match = re.fullmatch(r"([0-9]+)(?:s)?", value)
        if match:
            return int(match.group(1))
    return None


def _observe_cloud_run(
    project_id: str,
    resource: dict[str, Any],
    *,
    prepared: dict[str, Any] | None = None,
    observed_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    value = _read_json(("gcloud", "run", "services", "describe", resource["name"], f"--region={REGION}", f"--project={project_id}", "--format=json"))
    if value is None:
        return {"state": "missing", "resourceKind": "cloud-run-service", "matchesDesired": False}
    url = _deep(value, "status", "url")
    ready = next((item for item in (_deep(value, "status", "conditions") or []) if isinstance(item, dict) and item.get("type") == "Ready"), None)
    template = _deep(value, "spec", "template") or {}
    template_spec = _deep(template, "spec") or template
    containers = template_spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1 or not isinstance(containers[0], dict):
        return {"state": "incompatible", "resourceKind": "cloud-run-service", "matchesDesired": False}
    container = containers[0]
    annotations = _deep(template, "metadata", "annotations") or {}
    ingress = _deep(value, "spec", "ingress") or _deep(value, "metadata", "annotations", "run.googleapis.com/ingress")
    image = container.get("image")
    expected_image = f"{resource['image']}@sha256:{resource['digest']}"
    service_account = template_spec.get("serviceAccountName") or template_spec.get("serviceAccount")
    limits = _deep(container, "resources", "limits") or {}
    runtime = resource["runtime"]
    observed_runtime = {
        "containerConcurrency": template_spec.get("containerConcurrency") or _deep(template, "containerConcurrency"),
        "cpu": limits.get("cpu"),
        "memory": limits.get("memory"),
        "timeoutSeconds": _seconds(template_spec.get("timeoutSeconds") or _deep(template, "timeoutSeconds")),
        "minScale": annotations.get("autoscaling.knative.dev/minScale"),
        "maxScale": annotations.get("autoscaling.knative.dev/maxScale"),
    }
    normal_runtime = dict(observed_runtime)
    for key in ("containerConcurrency", "timeoutSeconds", "minScale", "maxScale"):
        if isinstance(normal_runtime[key], str) and normal_runtime[key].isdigit():
            normal_runtime[key] = int(normal_runtime[key])
    # The service identity is the safety boundary for a repair.  Runtime
    # configuration is deliberately kept outside this comparison because a
    # failed first deployment can leave the approved service with a correct
    # image/account but an incomplete template (for example, no env/secrets or
    # startup settings).  Such a service is repairable by the already bounded
    # deploy argv; a different identity must remain incompatible.
    identity_matches = (
        value.get("metadata", {}).get("name") == resource["name"]
        and image == expected_image
        and service_account == resource["serviceAccount"]
        and ingress == resource["ingress"]
    )
    runtime_matches = normal_runtime == runtime
    if not isinstance(ready, dict) or (ready.get("status") is not True and ready.get("status") != "True"):
        result = {"state": "missing" if identity_matches else "incompatible", "resourceKind": "cloud-run-service", "matchesDesired": False}
        if isinstance(url, str) and url:
            result["url"] = url
        return result
    matches = identity_matches and runtime_matches
    if matches and prepared is not None:
        try:
            expected = cloud_run_runtime_configuration(project_id, resource, prepared, observed_urls or {})
        except RuntimeContractError as error:
            raise DeploymentObserverError("Cloud Run runtime configuration is not yet observable") from error
        matches = _environment_matches(container.get("env"), expected)
    state = "present" if matches else "missing" if identity_matches else "incompatible"
    result = {"state": state, "resourceKind": "cloud-run-service", "matchesDesired": matches}
    if isinstance(url, str) and url:
        result["url"] = url
    return result


def _environment_matches(value: Any, expected: dict[str, dict[str, str]]) -> bool:
    if not isinstance(value, list):
        return False
    plain: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return False
        name = item["name"]
        if isinstance(item.get("value"), str):
            plain[name] = item["value"]
            continue
        source = item.get("valueFrom") or item.get("valueSource")
        if not isinstance(source, dict):
            return False
        reference = source.get("secretKeyRef")
        if not isinstance(reference, dict):
            return False
        secret = reference.get("name") or reference.get("secret")
        version = reference.get("key") or reference.get("version")
        if not isinstance(secret, str) or not isinstance(version, str):
            return False
        secrets[name] = f"{secret}:{version}"
    return all(plain.get(key) == value for key, value in expected["env"].items()) and all(
        secrets.get(key) == value for key, value in expected["secrets"].items()
    )


def _observe_queue(project_id: str, resource: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(("gcloud", "tasks", "queues", "describe", resource["name"], f"--location={REGION}", f"--project={project_id}", "--format=json"))
    if value is None:
        return {"state": "missing", "resourceKind": "cloud-tasks-queue", "matchesDesired": False}
    limits = value.get("rateLimits") or {}
    retry = value.get("retryConfig") or {}
    observed = {
        "dispatchDeadlineSeconds": _seconds(value.get("dispatchDeadline")),
        "maxConcurrentDispatches": _seconds(limits.get("maxConcurrentDispatches")),
        "maxDispatchesPerSecond": limits.get("maxDispatchesPerSecond"),
        "maxAttempts": _seconds(retry.get("maxAttempts")),
        "maxBackoffSeconds": _seconds(retry.get("maxBackoff")),
        "maxDoublings": _seconds(retry.get("maxDoublings")),
        "minBackoffSeconds": _seconds(retry.get("minBackoff")),
    }
    expected = {"dispatchDeadlineSeconds": resource["dispatchDeadlineSeconds"], **resource["rateLimits"], **resource["retry"]}
    expected = {"dispatchDeadlineSeconds": expected["dispatchDeadlineSeconds"], "maxConcurrentDispatches": expected["maxConcurrentDispatches"], "maxDispatchesPerSecond": expected["maxDispatchesPerSecond"], "maxAttempts": expected["maxAttempts"], "maxBackoffSeconds": expected["maxBackoffSeconds"], "maxDoublings": expected["maxDoublings"], "minBackoffSeconds": expected["minBackoffSeconds"]}
    matches = value.get("name", "").endswith(f"/locations/{REGION}/queues/{resource['name']}") and observed == expected
    return {"state": "present" if matches else "incompatible", "resourceKind": "cloud-tasks-queue", "matchesDesired": matches}


def _observe_iam(project_id: str, resource: dict[str, str]) -> dict[str, Any]:
    target = resource["resource"]
    if target == "project":
        argv = ("gcloud", "projects", "get-iam-policy", project_id, "--format=json")
    elif target.startswith("bucket:"):
        argv = ("gcloud", "storage", "buckets", "get-iam-policy", f"gs://{target[7:]}", "--format=json")
    elif target.startswith("secret:"):
        argv = ("gcloud", "secrets", "get-iam-policy", target[7:], f"--project={project_id}", "--format=json")
    elif target.startswith("serviceAccount:"):
        argv = ("gcloud", "iam", "service-accounts", "get-iam-policy", target[14:], "--format=json")
    elif target.startswith("cloudRun:"):
        argv = ("gcloud", "run", "services", "get-iam-policy", target[9:], f"--region={REGION}", f"--project={project_id}", "--format=json")
    elif target.startswith("queue:"):
        argv = ("gcloud", "tasks", "queues", "get-iam-policy", target[6:], f"--location={REGION}", f"--project={project_id}", "--format=json")
    else:
        raise DeploymentObserverError("IAM observation target is not allowlisted")
    policy = _read_json(argv)
    if policy is None:
        return {"state": "missing", "resourceKind": "iam-binding", "matchesDesired": False}
    present = any(binding.get("role") == resource["role"] and resource["principal"] in binding.get("members", []) for binding in policy.get("bindings", []) if isinstance(binding, dict))
    return {"state": "present" if present else "missing", "resourceKind": "iam-binding", "matchesDesired": present}


def observe_fixed(
    project_id: str,
    action: dict[str, Any],
    *,
    prepared: dict[str, Any] | None = None,
    observed_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    if action["resourceKind"] == "cloud-run-service":
        return _observe_cloud_run(project_id, action["resource"], prepared=prepared, observed_urls=observed_urls)
    if action["resourceKind"] == "cloud-tasks-queue":
        return _observe_queue(project_id, action["resource"])
    if action["resourceKind"] == "iam-binding":
        return _observe_iam(project_id, action["resource"])
    raise DeploymentObserverError("observer action kind is not allowlisted")
