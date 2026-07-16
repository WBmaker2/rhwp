# rhwp 문서 지도와 canonical manifest

이 문서는 저장소 문서의 진입점과 권위 관계를 기록한다. 상세 절차는
[manual 문서 지도](manual/README.md), 기술 근거는 [tech 문서 지도](tech/README.md)에서 찾는다.

## 시작 순서

1. 저장소 루트의 `AGENTS.md`와 `CLAUDE.md`를 읽는다.
2. 이 문서에서 작업 종류에 맞는 canonical 문서를 고른다.
3. 해당 문서가 가리키는 상세 가이드·기술 조사·트러블슈팅만 추가로 읽는다.

## 메타 규칙

- `kind`: 문서의 역할. `canonical`, `guide`, `reference`, `investigation`, `decision`, `snapshot`, `memory` 중 하나다.
- `status`: 생명주기. `active`, `historical`, `superseded` 중 하나다.
- `canonical`: 상세 문서가 따르는 권위 문서의 저장소 상대 경로다.
- `last_verified`: 이 manifest의 관계와 진입점이 마지막으로 확인된 날짜다. 문서 안의 모든 기술 사실을
  재검증했다는 뜻은 아니다.

## Canonical manifest

| 경로 | kind | status | canonical | last_verified |
| --- | --- | --- | --- | --- |
| [문서·Git 워크플로](manual/codex/docs_and_git_workflow.md) | canonical | active | `manual/codex/docs_and_git_workflow.md` | 2026-07-16 |
| [PR 리뷰·통합 워크플로](manual/pr_review_workflow.md) | canonical | active | `manual/pr_review_workflow.md` | 2026-07-16 |
| [개발 환경 가이드](manual/dev_environment_guide.md) | guide | active | `manual/dev_environment_guide.md` | 2026-07-16 |
| [CLI 명령어 매뉴얼](manual/cli_commands.md) | canonical | active | `manual/cli_commands.md` | 2026-07-16 |
| [시각 검증 문서 지도](manual/verification/README.md) | guide | active | `manual/verification/README.md` | 2026-07-16 |
| [시각 검증 거버넌스](manual/verification/visual_verification_governance.md) | canonical | active | `manual/verification/visual_verification_governance.md` | 2026-07-16 |
| [HWP 2020 MCP 사용법](manual/mcp_hwp2020Convert_usage.md) | guide | active | `manual/mcp_hwp2020Convert_usage.md` | 2026-07-16 |
| [HWP 5.0 스펙 문서 정오표](tech/hwp_spec_errata.md) | canonical | active | `tech/hwp_spec_errata.md` | 2026-07-16 |
| [한글 문서 파일 형식 5.0 개정 1.3](tech/한글문서파일형식_5.0_revision1.3.md) | reference | active | `tech/hwp_spec_errata.md` | 2026-07-16 |
| [Document IR LineSeg 표준](tech/document_ir_lineseg_standard.md) | canonical | active | `tech/document_ir_lineseg_standard.md` | 2026-07-16 |
| [렌더링 엔진 설계](tech/rendering_engine_design.md) | canonical | active | `tech/rendering_engine_design.md` | 2026-07-16 |
| [표 레이아웃 규칙](tech/table_layout_rules.md) | canonical | active | `tech/table_layout_rules.md` | 2026-07-16 |
| [폰트 fallback 전략](tech/font_fallback_strategy.md) | canonical | active | `tech/font_fallback_strategy.md` | 2026-07-16 |
| [편집 action undo/redo 아키텍처](tech/edit_action_undo_redo_architecture.md) | canonical | active | `tech/edit_action_undo_redo_architecture.md` | 2026-07-16 |
| [ThorVG 결정 기록](tech/thorvg_decision.md) | decision | active | `tech/thorvg_decision.md` | 2026-07-16 |
| [이전 개발 로드맵](tech/dev_roadmap_v1_backup.md) | snapshot | historical | `tech/dev_roadmap.md` | 2026-07-16 |

## Reference 자산

| 경로 | kind | status | canonical | last_verified |
| --- | --- | --- | --- | --- |
| [OWPML XML 스키마 reference](manual/owpml_schema_reference.md) | reference | active | `tech/hwpx_hancom_reference.md` | 2026-07-16 |

## 이동 규칙

문서 이동은 역할·현행성·참조 빈도를 검토한 독립 commit에서만 수행한다. 모든 내부 참조를 새 경로로
갱신하고, 외부 이력 호환이 필요한 옛 경로만 같은 commit의 redirect allowlist에 기록한다. 새 문서와
코드는 옛 경로를 참조하지 않는다.

```bash
python3 scripts/check_markdown_links.py
python3 scripts/check_markdown_links.py --forbid-path mydocs/manual/<이전-경로>.md
```
