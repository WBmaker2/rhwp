# 단계별 완료 보고서 — Task M100 #2400 Stage 2

## 1. 결론

다중 페이지 표의 pointer hit 경로가 현재 page의 표 fragment bbox만 사용하도록 수정했다.
UI 114쪽 `어 있는 경우` 첫 글자 앞 클릭은 HWP/HWPX 모두 표 객체 선택 없이
`cellParaIndex=2499`, `charOffset=77`에 캐럿이 진입한다. 같은 page fragment의 실제 하단
테두리 클릭은 계속 표 객체를 선택하므로 기존 ±5px 외곽 선택 계약도 보존된다.

수정은 table bbox 조회와 Studio hit 판정에 한정된다. pagination, line break, 폰트 metric,
selection rect semantic은 변경하지 않았다.

## 2. 구현

### native/WASM

- legacy `get_table_bbox_native()` / `getTableBBox()`의 첫 fragment 계약은 유지했다.
- `get_table_bbox_at_page_native()` / `getTableBBoxAtPage()`를 추가했다.
- 새 API는 지정 page tree 한 장만 조회하며 다른 page fragment로 fallback하지 않는다.
- 잘못된 표 참조, 범위 밖 page, 지정 page에 fragment가 없는 경우 오류를 반환한다.

### Studio

- `WasmBridge.getTableBBoxAtPage()` typed wrapper를 추가했다.
- 일반 셀 클릭, 선택된 표의 셀 재진입·이동 시작, 선택된 표 hover의 세 경로가 pointer
  `pageIdx`를 전달하도록 변경했다.
- 표 외부 탐색의 page layout 우선 경로는 유지하고 fallback에도 같은 page를 전달했다.
- ±5px 외곽 판정을 `isPointNearBoxBorder()` pure helper로 분리했다.

## 3. source 회귀

권위 HWP/HWPX 115쪽 샘플에서 다음 계약을 고정했다.

| 항목 | 결과 |
| --- | --- |
| legacy bbox | `pageIndex=0`, 기존 계약 유지 |
| page-scoped bbox | `pageIndex=113`, 현재 fragment 반환 |
| 재현점 `(142.8, 1057.3)` | legacy bbox에서는 border, 현재 bbox에서는 text |
| 범위 밖 `pageIndex=115` | 오류, 첫 fragment fallback 없음 |

Studio 테스트는 확정 좌표와 좌·우·상·하 ±5px 계약, 세 page 전달 경로를 검증한다.

## 4. 실제 pointer 검증

로컬 개발 WASM과 headless Chrome에서 HWP/HWPX를 각각 검증했다.

### #2400 직접 시나리오

| 입력 | HWP | HWPX |
| --- | --- | --- |
| UI 114쪽 offset 77 텍스트 클릭 | 표 선택 없음, offset 77 캐럿 | 표 선택 없음, offset 77 캐럿 |
| page 113 실제 fragment 하단 클릭 | 표 `sec=0, ppi=0, ci=2` 선택 | 동일 |

첫 fragment 하단과 클릭점 거리는 3.7px이지만 현재 fragment 하단과는 18.6px이다.
수정 후 native 경계 판정은 `false`였고 실제 pointer 결과도 일치했다.

### 인접 fragment 텍스트 클릭

HWP/HWPX 각각 다음 여섯 위치를 실제 pointer로 클릭했다. 12건 모두 표 객체 선택 없이
요청한 page·문단·offset에 캐럿이 진입했다.

| UI page 경계 | 앞 fragment | 뒤 fragment |
| --- | --- | --- |
| 1→2 | page 0 / para 17 / offset 162 | page 1 / para 17 / offset 170 |
| 56→57 | page 55 / para 1277 / offset 74 | page 56 / para 1277 / offset 82 |
| 114→115 | page 113 / para 2499 / offset 110 | page 114 / para 2499 / offset 118 |

### #2215 drag 회귀

UI 114→115 drag를 HWP/HWPX에서 실제 pointer로 다시 수행했다.

- 시작: page 113 / para 2499 / offset 40
- 끝: page 114 / para 2499 / offset 118
- 두 포맷 모두 selection 유지, highlight 3개, 복사 문자열 동일
- warm drag handler: HWP p95 5.0ms, HWPX p95 4.9ms
- selection rect: 두 포맷 p95 약 1.2ms

## 5. focused 검증 결과

| 검증 | 결과 |
| --- | --- |
| `cargo fmt --all -- --check` | 통과 |
| 신규 native #2400 HWP/HWPX 회귀 | 1 passed |
| legacy `test_get_table_bbox` | 1 passed |
| `issue_2215_selection_page_range` | 4 passed |
| `issue_717_table_cell_hit_test` | 4 passed |
| `issue_nested_table_border` | 2 passed |
| `issue_919_textbox_hit_test` | 5 passed |
| `npm --prefix rhwp-studio test` | 418 passed |
| `npm --prefix rhwp-studio run build` | 통과 |
| `git diff --check` | 통과 |

개발용 `wasm-pack build --dev --target web --out-dir pkg`도 통과했다. 실제 포인터 probe와
스크린샷은 일회성 검증 산출물이므로 `/private/tmp`에만 유지하고 PR에는 포함하지 않는다.

## 6. 남은 단계

수행·구현 계획에 따라 full CI는 focused 결과 공유와 별도 승인 뒤 PR 직전에 실행한다.

```text
cargo test --verbose
cargo clippy --all-targets -- -D warnings
```

full CI 통과 후 변경 요약과 실제 pointer 근거를 #2400에 공유하고 push/PR 생성 승인을
받는다.
