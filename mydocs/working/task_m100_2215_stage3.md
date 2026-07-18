# 단계별 완료 보고서 — Task M100 #2215 Stage 3-A/3-B

## 1. 결론

GREEN 구현 전에 page 후보 계약과 native/WASM 경계의 RED를 고정했다.

- 115장 host에서 same-page hint는 1장만 선택한다.
- p54→p55와 역방향 p55→p54는 `[54, 55]` 두 장만 선택한다.
- missing, 한쪽만 존재, host 밖 hint는 115장 full fallback을 유지한다.
- HWP/HWPX의 정상 same-page·cross-page rect/copy oracle은 유지된다.
- 기존 #658 selection rect 2건은 계속 GREEN이다.
- `getSelectionRectsInCellEx`가 아직 page hints를 소비하지 않으므로 split paragraph의
  다음-page same-page 선택 6건은 의도대로 RED다.

Stage 3-A에서는 후보 helper를 실제 selection 계산에 연결하지 않았다. 따라서 production
selection 동작과 성능은 아직 바뀌지 않았다.

## 2. 추가한 후보 계약

`src/document_core/queries/cursor_nav.rs`에 다음 내부 계획을 추가했다.

```text
SelectionPagePlan::Hinted(Vec<u32>)
SelectionPagePlan::FullFallback(Vec<u32>)
```

`plan_selection_pages()`는 host page 목록과 optional start/end hint만 받아 결과를 만드는 pure
helper다. production 계산과 분리되어 있으며 unit test 4건으로 다음을 고정했다.

| 입력 | 결과 |
|------|------|
| host `0..114`, hints `54,54` | `Hinted([54])` |
| host `0..114`, hints `54,55` | `Hinted([54,55])` |
| host `0..114`, hints `55,54` | `Hinted([54,55])` |
| missing/한쪽만 존재/`999` | `FullFallback(0..114)` |
| sparse host `[2,4,9,10]`, hints `4,10` | `Hinted([4,9,10])` |

검증 결과:

```text
running 4 tests
4 passed; 0 failed
```

## 3. 정상 selection oracle

신규 `tests/issue_2215_selection_page_range.rs`는 HWP/HWPX 각각 다음 범위를 기존
`getSelectionRectsInCellEx`로 조회한다.

| 범위 | native 계약 |
|------|-------------|
| p5 0..10 | rect 1개 / p0, 대표 좌표 ±0.5px, copy `1.1.1 수면비행` |
| p1250 0..1 | rect 1개 / p54, 대표 좌표 ±0.5px, copy `8` |
| p1250:0→p1275:1 | rect 45개 / p54–55, copy 1,517자와 prefix/suffix |

각 rect JSON과 copy text의 BLAKE3를 HWP/HWPX 사이에서 byte-level 비교해 두 형식이 같은
결과임도 고정했다.

Stage 2의 SHA-256은 WASM 실행에서 확보한 값이다. native 실행은 첫 rect 폭이 WASM 111.7px,
native 112.0px로 0.3px 달랐다. 이는 native/WASM font metric 실행 대상 차이이므로 native
테스트에서 WASM JSON을 byte-level로 강제하지 않았다.

- native: 구조·페이지·좌표 ±0.5px와 HWP/HWPX byte 동등성
- WASM/Studio: Stage 2의 기존 SHA-256 oracle

이렇게 대상별 oracle을 분리해 실제 회귀를 잡으면서 플랫폼 metric 차이로 인한 가짜 실패를
피한다.

검증 결과:

```text
issue_2215_hwp_and_hwpx_preserve_normal_selection_oracles ... ok
1 passed; 0 failed; finished in 193.73s
```

현재 full host-page 탐색이 유지되어 이 RED 단계의 native test가 오래 걸린다. Stage 3-B
GREEN 뒤 hinted path가 연결되면 같은 테스트 시간이 후보 page 수에 맞게 줄어야 한다.

## 4. split paragraph RED

기존 `getSelectionRectsInCellEx` options에 `startPageHint`와 `endPageHint`를 넣었지만 현재
WASM adapter가 두 key를 무시하므로 전체 115쪽의 첫 fragment를 선택한다.

| 형식 | cell paragraph | 기대 | 실제 | 결과 |
|------|---------------:|------|------|------|
| HWP | 17 / 166..170 | p1, page 폭 안 | p0, x=670.9, width=516.2 | RED |
| HWP | 1277 / 78..82 | p56, page 폭 안 | p55, x=670.6, width=473.7 | RED |
| HWP | 2499 / 114..118 | p114, page 폭 안 | p113, x=670.6, width=463.4 | RED |
| HWPX | 17 / 166..170 | p1, page 폭 안 | p0, x=670.9, width=516.2 | RED |
| HWPX | 1277 / 78..82 | p56, page 폭 안 | p55, x=670.6, width=473.7 | RED |
| HWPX | 2499 / 114..118 | p114, page 폭 안 | p113, x=670.6, width=463.4 | RED |

모든 실제 rect는 page width 793.7px를 벗어난다. Stage 2의 기존 원인과 일치하며 Stage 3-B가
해결해야 할 정확한 GREEN 목표다.

## 5. 기존 회귀

```text
cargo test --test issue_658_text_selection_rects
2 passed; 0 failed; finished in 0.10s
```

`cargo fmt --check`도 통과했다.

## 6. 변경 파일

| 파일 | 변경 |
|------|------|
| `src/document_core/queries/cursor_nav.rs` | page 후보 pure helper와 unit test 4건 |
| `tests/issue_2215_selection_page_range.rs` | HWP/HWPX 정상 oracle 및 split RED |
| `mydocs/working/task_m100_2215_stage3.md` | Stage 3-A 결과 기록 |

`src/wasm_api.rs`, Studio source, page-tree build 경로는 아직 변경하지 않았다.

## 7. Stage 3-A 당시 다음 승인 단계

Stage 3-B에서는 승인된 구현계획에 따라 다음만 수행한다.

1. `get_selection_rects_native()`가 optional page hints를 받도록 내부 경계를 확장한다.
2. candidate page 목록만 cached build하는 pass를 분리한다.
3. endpoint/segment 미해소 시 full host-page fallback한다.
4. `getSelectionRectsInCellEx`가 두 optional hint를 파싱해 전달한다.
5. 이 보고서의 6개 split RED를 GREEN으로 전환한다.

Studio 전달과 실제 pointer E2E는 Stage 3-C/3-D이며 Stage 3-B에 섞지 않는다.

---

## 8. Stage 3-B GREEN 결론

2026-07-19 최신 `upstream/devel@af5902b6`에 RED 커밋을 rebase한 뒤 native candidate 제한과
정확성 fallback을 구현했다.

- `getSelectionRectsInCellEx`가 optional `startPageHint`/`endPageHint`를 파싱한다.
- 두 hint가 유효하면 same-page 1장 또는 endpoint 사이 host page만 조회한다.
- hinted 후보만 shared `build_page_tree_cached()`를 사용한다.
- 필요한 line segment를 모두 해소하지 못하면 기존 full host-page path로 한 번 재시도한다.
- positional, missing, one-sided, invalid hint의 full fallback은 기존 uncached 함수 로컬 tree
  수명을 유지한다.
- Stage 3-A의 split RED 6건은 모두 GREEN으로 전환됐다.

Studio source는 아직 변경하지 않았으므로 실제 mouse drag는 계속 positional API를 사용한다.
이번 GREEN은 native/WASM options 경계까지만 완료한 상태다.

## 9. native 구현

`get_selection_rects_native()`에 내부 `Option<(u32, u32)>` page hints를 추가했다.

```text
host pages 조회
→ plan_selection_pages()
→ Hinted: 제한된 page만 shared cache로 build
→ FullFallback: 기존 전체 page를 함수 로컬 tree로 build
→ line segment별 rect 계산
→ expected_segments != rendered_segments이면 hints 없이 full retry
```

fallback 판단은 non-empty line segment 수와 실제 rect segment 수를 비교한다. 따라서 hinted
범위가 일부 rect만 반환하는 경우 부분 결과를 노출하지 않는다. page hints가 없거나 host
집합 밖이면 처음부터 full fallback을 사용하므로 재귀는 한 번을 넘지 않는다.

full fallback까지 shared cache를 사용하면 115개 tree가 호출 뒤에도 남아 메모리 체류가
증가할 수 있다. 그래서 cache는 정상 hinted 후보에만 적용하고 positional/fallback은 기존
수명을 보존했다.

## 10. WASM options 호환

`src/wasm_api.rs`의 기존 positional API는 `page_hints=None`으로 호출한다. `Ex`만 두 optional
key를 `zip()`해 둘 다 있을 때 native hinted path로 전달한다.

| 호출 | 동작 |
|------|------|
| positional | 기존 full host-page 탐색 |
| `Ex` hints 없음 | 기존 full host-page 탐색 |
| `Ex` 한 hint만 존재 | 기존 full host-page 탐색 |
| `Ex` host 밖 hints | 기존 full host-page 탐색 |
| `Ex` 유효 same-page hints | endpoint page 1장 |
| `Ex` 유효 cross-page hints | endpoint 사이 host pages |
| `Ex` 유효하지만 endpoint miss | full host-page 재시도 |

public positional signature와 JSON 반환 형식은 바뀌지 않았다.

## 11. GREEN 검증

### #2215 통합 회귀

```text
cargo test --test issue_2215_selection_page_range -- --nocapture --test-threads=1
3 passed; 0 failed; finished in 99.25s
```

세부 결과:

- HWP/HWPX 정상 same-page·cross-page rect/copy oracle 유지
- HWP의 valid-but-stale p0 hint로 p54 endpoint 조회 시 full fallback 결과 유지
- missing, one-sided, invalid hints가 positional 결과와 동일
- p1, p56, p114 same-page split rect가 HWP/HWPX 모두 기대 page와 page 폭 안에 존재

Stage 3-A full target은 정상 oracle의 초기 과엄격 metric assertion을 포함한 상태에서
238.34초였고, GREEN target은 stale full-fallback 회귀까지 추가하고도 99.25초였다. 이 값에는
두 형식 parse와 의도적인 115-page fallback이 포함되므로 최종 drag p95로 해석하지 않는다.

### 후보 helper와 기존 회귀

```text
cargo test --lib issue_2215_selection_page_plan_tests
4 passed; 0 failed

cargo test --test issue_658_text_selection_rects
2 passed; 0 failed; finished in 0.08s

cargo fmt --check
통과
```

## 12. Stage 3-B 변경 파일

| 파일 | 변경 |
|------|------|
| `src/document_core/queries/cursor_nav.rs` | hinted candidate 연결, 제한된 cached tree, segment fallback |
| `src/wasm_api.rs` | `Ex` optional page hints 파싱과 positional 호환 |
| `tests/issue_2215_selection_page_range.rs` | stale/missing/one-sided/invalid fallback 회귀 추가 |

## 13. 다음 승인 단계

Stage 3-C에서는 다음 Studio 전달만 구현한다.

1. `WasmBridge.getSelectionRectsInCell()`에 optional hints를 추가한다.
2. 두 hints가 있을 때만 `getSelectionRectsInCellEx`를 호출한다.
3. `InputHandler.updateSelection()`이 ordered endpoint의 `cursorRect?.pageIndex`를 전달한다.
4. bridge dispatch 단위 테스트를 추가한다.

mouse rAF, auto-scroll, rendering 또는 pagination 정책은 변경하지 않는다. 실제 pointer drag
E2E와 p95 측정은 Stage 3-D 승인 뒤 수행한다.
