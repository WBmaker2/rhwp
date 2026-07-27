"""Bounded JSON-domain validation for non-mutating staging artifacts."""
from __future__ import annotations

import json
import math
from typing import Any

MAX_JSON_BYTES = 1_000_000
MAX_DEPTH = 64
MAX_NODES = 10_000
MAX_STRING_BYTES = 16_384


class StrictJsonError(RuntimeError):
    pass


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
