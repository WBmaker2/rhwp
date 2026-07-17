---
kind: guide
status: active
canonical: mydocs/tech/README.md
last_verified: 2026-07-16
---

# tech 문서 지도

`mydocs/tech/`은 rhwp의 **기술 사실, 설계, 결정, 조사 근거**를 보존하는 문서 공간이다.
반복 작업 절차와 도구 사용법은 [manual 문서 지도](../manual/README.md)에서 찾는다.

## 권위 문서와 진입점

| 주제 | 권위 또는 우선 진입점 | 관련 상세 문서 |
| --- | --- | --- |
| HWP 5.0 구현 차이 | [HWP 5.0 스펙 문서 정오표](hwp_spec_errata.md) | [한글 문서 파일 형식 5.0 개정 1.3](한글문서파일형식_5.0_revision1.3.md), [HWP 제어 데이터](hwp_ctrl_data.md) |
| 포맷 파서와 공통 IR 책임 경계 | [포맷 파서와 공통 Document IR 경계](parser_architecture.md) | [HWP/HWPX IR 차이](hwp_hwpx_ir_differences.md) |
| HWPX와 HWP IR 차이 | [HWP/HWPX IR 차이](hwp_hwpx_ir_differences.md) | [HWPX 한컴 참조](hwpx_hancom_reference.md), [HWPX DVC 참조](hwpx_dvc_reference.md), [로컬 OWPML XML 스키마](../manual/owpml_schema_reference.md) |
| Document IR와 LineSeg 계약 | [Document IR LineSeg 표준](document_ir_lineseg_standard.md) | [Issue #310 LineSeg vpos 조사](investigations/issue-310/README.md), [HWPX LineSeg 검증](hwpx_lineseg_validation.md) |
| 렌더링 엔진 | [렌더링 엔진 설계](rendering_engine_design.md) | [Issue #516 다층 렌더링 후보 조사](investigations/issue-516/README.md), [Canvas 렌더링 분석](canvas_rendering_analysis.md) |
| 표 레이아웃 | [표 레이아웃 규칙](table_layout_rules.md) | [HWP 표 렌더링](hwp_table_rendering.md), [부분 표 흐름](partial_table_flow.md) |
| 폰트 대체와 충실도 | [폰트 fallback 전략](font_fallback_strategy.md) | [한컴 폰트 시스템 분석](hancom_font_system_analysis.md), [폰트 메트릭 크기 비교](font_metrics_size_comparison.md) |
| 편집 undo/redo | [편집 action undo/redo 아키텍처](edit_action_undo_redo_architecture.md) | 이슈별 실동작 조사 문서 |
| 기술 채택·비채택 | [ThorVG 결정 기록](thorvg_decision.md) | [ThorVG POC 인사이트](thorvg_poc_insights.md) |
| 이슈별 기술 조사 | [이슈별 기술 조사 지도](investigations/README.md) | [Issue #511 IR wrap 조사](investigations/issue-511/README.md), [Issue #1151 picture TAC 조사](investigations/issue-1151/README.md), [Issue #1584 이후 HWPX 잔여 IR 차이 조사](investigations/issue-1584/README.md), [Issue #1658 페이지네이션 조사](investigations/issue-1658/README.md), [Issue #1772 잔여 OVER 조사](investigations/issue-1772/README.md), [Issue #2125 font ownership 조사](investigations/issue-2125/README.md) |

## 현재 구조를 읽는 법

- `hwp_*`, `hwpx_*`, `document_ir_*`, `rendering_*`, `table_*`, `font_*` 문서는 장기 참조 후보이지만,
  파일명만으로 권위 문서라고 가정하지 않는다. 위 표 또는 각 문서의 명시적 링크를 우선한다.
- `task_m100_*`, `*_root_cause`, `*_diagnosis`, `*_investigation`은 이슈별 조사일 가능성이 높다. 다만
  장기 계약·기준선·설계 결론을 담은 문서는 `investigations/`로 자동 이동하지 않고 현행성 감사를 거쳐 분류한다.
- 현재 분리된 이슈별 조사는 `investigations/issue-####/`에서 관리한다. 각 디렉터리의 README가 해당
  스냅샷과 진단의 당시 범위, 최신성 제한, 관련 문서를 설명한다.
- `webhwp/` 하위 문서는 웹 편집기 기능별 reference 묶음이다.
- [archive/](archive/README.md)의 v1 roadmap처럼 대체된 계획은 historical 자료로 취급하며, 새 작업의
  근거로 직접 사용하지 않는다.

## 조사와 트러블슈팅 경계

- `tech/investigations/`는 특정 이슈의 가설·실험·관찰과 미확정 또는 기각 결론을 보존한다. 반복 작업의
  지침이나 장기 계약의 권위 문서는 아니다.
- [mydocs/troubleshootings/](../troubleshootings/README.md)는 재현 가능한 증상, 확정 원인, 적용 가능한 대응과 검증 방법을 보존한다.
  이후 작업의 사전 점검 자료로 사용한다.
- 조사 또는 트러블슈팅에서 장기 계약·스펙 정정·운영 절차가 확정되면 canonical 문서에 반영하고, 원 문서는
  근거 링크로 남긴다.

## 문서 역할과 생명주기

문서 역할(`kind`)과 생명주기(`status`)는 독립이다. 메타 블록을 추가하거나 갱신할 때는 다음 스키마를
쓴다.

| 필드 | 허용 값 | 의미 |
| --- | --- | --- |
| `kind` | `canonical`, `guide`, `reference`, `investigation`, `decision`, `snapshot`, `memory` | 문서가 수행하는 역할 |
| `status` | `active`, `historical`, `superseded` | 현재 사용 가능성 |
| `canonical` | 저장소 상대 경로 | 해당 상세 문서가 따르는 권위 문서 |
| `last_verified` | `YYYY-MM-DD` | 기술 사실을 마지막으로 확인한 날짜 |

canonical manifest와 분류가 끝난 `investigations`, `archive`, redirect 문서는 이 스키마를 CI에서
검사한다. 나머지 legacy 문서는 역할과 내용 현행성을 확인한 뒤 검사 범위에 추가한다.

## 링크와 이동 규칙

파일 이동 전과 후에 다음 명령을 실행한다.

```bash
python3 scripts/check_markdown_links.py
```

내부 참조는 이동 커밋에서 새 경로로 직접 바꾼다. redirect stub은 외부 이력 호환이 필요한 문서만
allowlist로 제한한다. 이동 stage에서는 `--forbid-path`로 이전 경로의 재참조가 없는지 일회성 검증한다.
고정 migration 목록은 영구 CI에 두지 않으며, 새 문서를 추가할 때 workflow YAML을 수정하지 않는다.
