"""Shared fail-closed safety checks for review, promotion, and approval data."""
from __future__ import annotations

import re
from typing import Any

_SENSITIVE = (
    re.compile(r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|CERTIFICATE)-----", re.I),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9._~-])ya29\.[A-Za-z0-9._~-]{16,}(?![A-Za-z0-9._~-])"),
    re.compile(r"\b(?:password|api[_-]?key)\s*=", re.I),
    re.compile(r"(?<![A-Za-z0-9_-])GOCSPX-[A-Za-z0-9_-]{12,}(?![A-Za-z0-9_-])"),
    re.compile(r"\b(?:oauth_)?client[_-]?secret\s*[:=]\s*[A-Za-z0-9._~-]{8,}", re.I),
    re.compile(r"(?:[\"']?type[\"']?\s*[:=]\s*[\"']?service_account[\"']?|[\"']?(?:private_key_id|client_email)[\"']?\s*[:=])", re.I),
    re.compile(r"(?:\"?(?:private_key|client_secret|refresh_token|access_token)\"?\s*[:=])", re.I),
)


class ApplySafetyError(RuntimeError):
    pass


def reject_sensitive_string_leaves(value: Any, label: str, path: tuple[str, ...] = ()) -> None:
    """Reject credential-shaped values without including the offending value."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_sensitive_string_leaves(item, label, (*path, key))
    elif isinstance(value, list):
        for item in value:
            reject_sensitive_string_leaves(item, label, path)
    elif isinstance(value, str) and not _inert_enum_path(path, value):
        if any(pattern.search(value) for pattern in _SENSITIVE):
            raise ApplySafetyError(f"{label} contains a credential-shaped string value")


def _inert_enum_path(path: tuple[str, ...], value: str) -> bool:
    """The only value allowlist is inert, schema-checked permission enums."""
    return path[-1:] == ("id-token",) and value in {"none", "write"}
