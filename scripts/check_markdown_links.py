#!/usr/bin/env python3
"""저장소 내부 Markdown 상대 링크를 검사한다.

외부 URL과 문서 내 앵커는 이 도구의 범위 밖이다. 파일 이동 전에 내부 경로가
깨지지 않았는지 확인하는 용도로 사용한다.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "README_EN.md",
    "CONTRIBUTING.md",
    "mydocs/README.md",
    "mydocs/manual",
    "mydocs/tech",
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\s*\)"
)
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(?:<([^>]+)>|([^\s]+))")


@dataclass(frozen=True)
class BrokenLink:
    source: Path
    line: int
    destination: str
    resolved: Path


@dataclass(frozen=True)
class ForbiddenLink:
    source: Path
    line: int
    destination: str
    resolved: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="저장소 내부 Markdown 상대 링크의 대상 파일 존재 여부를 검사합니다."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help="검사할 저장소 상대 파일 또는 디렉터리 (기본: 루트 안내 문서와 mydocs/manual·tech)",
    )
    parser.add_argument(
        "--forbid-path",
        action="append",
        default=[],
        metavar="PATH",
        help="새 참조를 금지할 저장소 상대 경로. 문서 이동 뒤 이전 경로를 검사할 때 반복 지정한다.",
    )
    return parser.parse_args()


def iter_markdown_files(raw_paths: list[str]) -> list[Path]:
    files: set[Path] = set()
    for raw_path in raw_paths:
        candidate = (REPOSITORY_ROOT / raw_path).resolve()
        try:
            candidate.relative_to(REPOSITORY_ROOT)
        except ValueError as error:
            raise SystemExit(f"저장소 밖 경로는 검사할 수 없습니다: {raw_path}") from error

        if candidate.is_file():
            if candidate.suffix.lower() == ".md":
                files.add(candidate)
            continue
        if candidate.is_dir():
            files.update(path.resolve() for path in candidate.rglob("*.md") if path.is_file())
            continue
        raise SystemExit(f"검사 경로가 없습니다: {raw_path}")
    return sorted(files)


def destinations_in_markdown(source: Path) -> list[tuple[int, str]]:
    destinations: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker[0] == fence_marker:
                in_fence = False
            continue
        if in_fence:
            continue

        for match in INLINE_LINK_RE.finditer(line):
            destinations.append((line_number, match.group(1) or match.group(2)))
        reference_match = REFERENCE_LINK_RE.match(line)
        if reference_match:
            destinations.append((line_number, reference_match.group(1) or reference_match.group(2)))
    return destinations


def resolve_local_destination(source: Path, destination: str) -> Path | None:
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc:
        return None

    path_text = unquote(parsed.path)
    if not path_text:
        return None
    if path_text.startswith("/"):
        resolved = REPOSITORY_ROOT / path_text.lstrip("/")
    else:
        resolved = source.parent / path_text
    return resolved.resolve()


def normalize_forbidden_paths(raw_paths: list[str]) -> set[Path]:
    normalized: set[Path] = set()
    for raw_path in raw_paths:
        candidate = (REPOSITORY_ROOT / raw_path).resolve()
        try:
            candidate.relative_to(REPOSITORY_ROOT)
        except ValueError as error:
            raise SystemExit(f"저장소 밖 금지 경로는 지정할 수 없습니다: {raw_path}") from error
        normalized.add(candidate)
    return normalized


def collect_broken_links(markdown_files: list[Path]) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    for source in markdown_files:
        for line, destination in destinations_in_markdown(source):
            resolved = resolve_local_destination(source, destination)
            if resolved is None:
                continue
            try:
                resolved.relative_to(REPOSITORY_ROOT)
            except ValueError:
                broken.append(BrokenLink(source, line, destination, resolved))
                continue
            if resolved.exists():
                continue
            broken.append(BrokenLink(source, line, destination, resolved))
    return broken


def collect_forbidden_links(
    markdown_files: list[Path], forbidden_paths: set[Path]
) -> list[ForbiddenLink]:
    forbidden: list[ForbiddenLink] = []
    for source in markdown_files:
        for line, destination in destinations_in_markdown(source):
            resolved = resolve_local_destination(source, destination)
            if resolved is not None and resolved in forbidden_paths:
                forbidden.append(ForbiddenLink(source, line, destination, resolved))
    return forbidden


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    markdown_files = iter_markdown_files(args.paths)
    broken_links = collect_broken_links(markdown_files)
    forbidden_links = collect_forbidden_links(
        markdown_files, normalize_forbidden_paths(args.forbid_path)
    )

    print(f"검사 문서: {len(markdown_files)}개")
    if not broken_links and not forbidden_links:
        print("내부 Markdown 상대 링크: 이상 없음")
        return 0

    if broken_links:
        print(f"깨진 내부 Markdown 상대 링크: {len(broken_links)}건")
    for broken in broken_links:
        print(
            f"- {display_path(broken.source)}:{broken.line}: "
            f"{broken.destination} -> {display_path(broken.resolved)}",
            file=sys.stderr,
        )
    if forbidden_links:
        print(f"금지된 이전 경로 참조: {len(forbidden_links)}건")
    for forbidden in forbidden_links:
        print(
            f"- {display_path(forbidden.source)}:{forbidden.line}: "
            f"{forbidden.destination} -> {display_path(forbidden.resolved)}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
