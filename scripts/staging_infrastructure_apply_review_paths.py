"""Fail-closed filesystem boundary checks for apply-review publication."""
from __future__ import annotations

from pathlib import Path


class ApplyReviewPathError(RuntimeError):
    pass


def validate_cli_paths(
    plan: Path,
    approval: Path,
    execution: Path,
    json_output: Path,
    markdown_output: Path,
) -> None:
    marker = json_output.with_name(json_output.name + ".complete")
    temporary = tuple(
        path.with_name(path.name + ".tmp")
        for path in (json_output, markdown_output, marker)
    )
    inputs = (plan, approval, execution)
    outputs = (json_output, markdown_output, marker, *temporary)
    all_paths = (*inputs, *outputs)
    if any(_has_symlink_component(path) for path in all_paths):
        raise ApplyReviewPathError("input, output, marker, and temporary paths must not use symlinks")
    resolved = [path.resolve(strict=False) for path in all_paths]
    if len(set(resolved)) != len(resolved):
        raise ApplyReviewPathError("input, output, marker, and temporary paths must not overlap or alias")
    for index, left in enumerate(resolved):
        if any(left in right.parents or right in left.parents for right in resolved[index + 1:]):
            raise ApplyReviewPathError("input, output, marker, and temporary paths must not have parent-child overlap")
    if any(not path.exists() or not path.is_file() for path in inputs):
        raise ApplyReviewPathError("input paths must be existing regular files")
    if any(path.exists() and not path.is_file() for path in outputs):
        raise ApplyReviewPathError("output, marker, and temporary paths must be regular files when present")
    if any(path.exists() for path in temporary):
        raise ApplyReviewPathError("temporary output path already exists")
    for index, left in enumerate(all_paths):
        if not left.exists():
            continue
        for right in all_paths[index + 1:]:
            if right.exists() and left.samefile(right):
                raise ApplyReviewPathError("input, output, marker, and temporary paths must not be the same file")


def _has_symlink_component(path: Path) -> bool:
    return any(component.is_symlink() for component in (path, *path.parents))
