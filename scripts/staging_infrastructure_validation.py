"""Bounded JSON-domain validation for non-mutating staging artifacts."""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 1_000_000
MAX_DEPTH = 64
MAX_NODES = 10_000
MAX_STRING_BYTES = 16_384


class StrictJsonError(RuntimeError):
    pass


def parse_strict_json_bytes(raw: bytes, label: str = "JSON") -> Any:
    if not isinstance(raw, bytes) or len(raw) > MAX_JSON_BYTES:
        raise StrictJsonError(f"{label} exceeds JSON size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_reject_constant)
        validate_json_domain(value)
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise StrictJsonError(f"{label} is not valid JSON or strict UTF-8") from error


def read_bounded_json_file(path: Path, label: str) -> tuple[Any, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StrictJsonError(f"{label} must be a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_JSON_BYTES + 1)
    except OSError as error:
        raise StrictJsonError(f"{label} could not be read") from error
    finally:
        if descriptor >= 0:
            try: os.close(descriptor)
            except OSError: pass
    return parse_strict_json_bytes(raw, label), raw


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def validate_json_domain(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise StrictJsonError("json-domain-limit")
        if isinstance(current, float) and not math.isfinite(current):
            raise StrictJsonError("non-finite JSON number")
        if isinstance(current, float):
            continue
        if isinstance(current, str):
            try: encoded = current.encode("utf-8")
            except UnicodeEncodeError as error: raise StrictJsonError("invalid-unicode-string") from error
            if len(encoded) > MAX_STRING_BYTES:
                raise StrictJsonError("json-string-limit")
            continue
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise StrictJsonError("json-object-key-invalid")
                stack.append((item, depth + 1))
            continue
        if isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
            continue
        if current is None or isinstance(current, (bool, int)):
            continue
        raise StrictJsonError("json-value-type-invalid")


def canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    validate_json_domain(value)
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent, allow_nan=False)
        return (text + "\n").encode("utf-8")
    except UnicodeEncodeError as error:
        raise StrictJsonError("invalid-unicode-string") from error
