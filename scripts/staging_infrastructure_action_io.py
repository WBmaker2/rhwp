"""Atomic, marker-backed output publication for infrastructure action manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ActionIoError(RuntimeError):
    pass


def publish(json_output: Path, markdown_output: Path, json_text: str, markdown: str) -> Path:
    marker = json_output.with_name(json_output.name + ".complete")
    temporary = tuple(path.with_name(path.name + ".tmp") for path in (json_output, markdown_output, marker))
    _validate_paths(json_output, markdown_output, marker, temporary)
    backups = {path: path.read_bytes() if path.exists() else None for path in (json_output, markdown_output, marker)}
    published: list[Path] = []
    try:
        for path in (json_output, markdown_output): path.parent.mkdir(parents=True, exist_ok=True)
        marker.unlink(missing_ok=True)
        temporary[0].write_text(json_text); temporary[1].write_text(markdown)
        temporary[0].replace(json_output); published.append(json_output)
        temporary[1].replace(markdown_output); published.append(markdown_output)
        temporary[2].write_text(json.dumps({"jsonOutput": str(json_output), "markdownOutput": str(markdown_output), "jsonSha256": _sha(json_output), "markdownSha256": _sha(markdown_output)}) + "\n")
        temporary[2].replace(marker); published.append(marker)
    except OSError as error:
        for path in temporary:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        for path in published + ([marker] if backups[marker] is not None else []):
            try:
                if backups[path] is None: path.unlink(missing_ok=True)
                else: path.write_bytes(backups[path])
            except OSError: pass
        raise ActionIoError(str(error)) from error
    return marker


def _validate_paths(json_output: Path, markdown_output: Path, marker: Path, temporary: tuple[Path, ...]) -> None:
    all_paths = (json_output, markdown_output, marker, *temporary)
    resolved = [path.resolve(strict=False) for path in all_paths]
    if any(path.is_symlink() for path in all_paths) or len(set(resolved)) != len(resolved):
        raise ActionIoError("output and marker paths must not overlap or alias")
    if any(path.exists() for path in temporary):
        raise ActionIoError("temporary output path already exists")
    if any(path.exists() and path.is_dir() for path in (json_output, markdown_output, marker)):
        raise ActionIoError("output path must not be a directory")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
