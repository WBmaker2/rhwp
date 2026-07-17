#!/usr/bin/env python3
"""권위 문서와 분류된 문서 클러스터의 front matter를 검사한다."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "mydocs/README.md",
    "mydocs/manual/README.md",
    "mydocs/manual/cli_commands.md",
    "mydocs/manual/ai_pair_programming_guide.md",
    "mydocs/manual/codex/MEMORY.md",
    "mydocs/manual/codex/README.md",
    "mydocs/manual/codex/docs_and_git_workflow.md",
    "mydocs/manual/dev_environment_guide.md",
    "mydocs/manual/dump_command.md",
    "mydocs/manual/export_png_command.md",
    "mydocs/manual/hyper_waterfall_docs_guide.md",
    "mydocs/manual/ir_diff_command.md",
    "mydocs/manual/mcp_hwp2020Convert_usage.md",
    "mydocs/manual/memory/MEMORY.md",
    "mydocs/manual/onboarding_guide.md",
    "mydocs/manual/owpml_schema_reference.md",
    "mydocs/manual/pr_review_workflow.md",
    "mydocs/manual/publish_guide.md",
    "mydocs/manual/rhwp_cli_skill_guide.md",
    "mydocs/manual/rhwp_studio_ui_conventions.md",
    "mydocs/manual/verification",
    "mydocs/tech/README.md",
    "mydocs/tech/archive",
    "mydocs/tech/ci_cache_policy_1664.md",
    "mydocs/tech/document_ir_lineseg_standard.md",
    "mydocs/tech/edit_action_undo_redo_architecture.md",
    "mydocs/tech/font_fallback_strategy.md",
    "mydocs/tech/hwp_spec_errata.md",
    "mydocs/tech/hwp_ole_chart_renderer_architecture_decision_1251.md",
    "mydocs/tech/investigations",
    "mydocs/tech/parser_architecture.md",
    "mydocs/tech/rendering_engine_design.md",
    "mydocs/tech/table_layout_rules.md",
    "mydocs/tech/thorvg_decision.md",
    "mydocs/tech/한글문서파일형식_5.0_revision1.3.md",
    "mydocs/troubleshootings",
)
REDIRECT_SCAN_PATHS = ("mydocs/manual", "mydocs/tech")
REQUIRED_FIELDS = ("kind", "status", "canonical", "last_verified")
ALLOWED_KINDS = {
    "canonical",
    "guide",
    "reference",
    "investigation",
    "decision",
    "snapshot",
    "memory",
}
ALLOWED_STATUSES = {"active", "historical", "superseded"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def repository_path(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def iter_markdown_files(raw_paths: tuple[str, ...]) -> set[Path]:
    files: set[Path] = set()
    for raw_path in raw_paths:
        path = REPOSITORY_ROOT / raw_path
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            files.update(path.rglob("*.md"))
        else:
            raise SystemExit(f"메타데이터 검사 경로가 없습니다: {raw_path}")
    return files


def parse_front_matter(path: Path) -> tuple[dict[str, str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}, lines

    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, lines

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, lines[end + 1 :]


def is_redirect_stub(path: Path) -> bool:
    _, body = parse_front_matter(path)
    return any(line.strip() == "# 이동됨" for line in body[:3])


def validate_file(path: Path) -> list[str]:
    metadata, _ = parse_front_matter(path)
    errors: list[str] = []
    display = repository_path(path)

    for field in REQUIRED_FIELDS:
        if not metadata.get(field):
            errors.append(f"{display}: 필수 메타데이터 누락: {field}")

    kind = metadata.get("kind")
    if kind and kind not in ALLOWED_KINDS:
        errors.append(f"{display}: 허용되지 않은 kind: {kind}")

    status = metadata.get("status")
    if status and status not in ALLOWED_STATUSES:
        errors.append(f"{display}: 허용되지 않은 status: {status}")
    if is_redirect_stub(path) and status != "superseded":
        errors.append(f"{display}: redirect stub의 status는 superseded여야 함")

    canonical = metadata.get("canonical")
    if canonical:
        canonical_path = REPOSITORY_ROOT / canonical
        if canonical_path.resolve().is_relative_to(REPOSITORY_ROOT.resolve()):
            if not canonical_path.exists():
                errors.append(f"{display}: canonical 경로가 없음: {canonical}")
        else:
            errors.append(f"{display}: canonical 경로가 저장소 밖임: {canonical}")

    last_verified = metadata.get("last_verified")
    if last_verified and not DATE_RE.fullmatch(last_verified):
        errors.append(f"{display}: last_verified 형식 오류: {last_verified}")
    return errors


def main() -> int:
    required_files = iter_markdown_files(REQUIRED_PATHS)
    redirect_candidates = iter_markdown_files(REDIRECT_SCAN_PATHS)
    required_files.update(path for path in redirect_candidates if is_redirect_stub(path))

    errors: list[str] = []
    for path in sorted(required_files):
        errors.extend(validate_file(path))

    print(f"메타데이터 검사 문서: {len(required_files)}개")
    if not errors:
        print("문서 메타데이터: 이상 없음")
        return 0

    print(f"문서 메타데이터 오류: {len(errors)}건", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
