# 구현계획서 — HWP 반복 표 fresh-page placement 기준점 정합 (M100 #2439)

- **이슈**: [edwardkim/rhwp#2439](https://github.com/edwardkim/rhwp/issues/2439)
- **브랜치**: `codex/task2439`
- **수행계획서**: [`task_m100_2439.md`](task_m100_2439.md)
- **작성일**: 2026-07-19

## 1. 구현 계약

`typeset_block_table`에서 같은 host의 후속 RowBreak float가 fits-fresh orphan 가드로
새 페이지/단으로 이동하면, 그 표의 placement/exclusion 좌표는 새 페이지의
`current_height`를 기준으로 계산한다. 원 host의 `para_start_height`는 분할 예산 계약이
필요한 곳에만 남긴다. 같은 visible host의 zero-offset/positive-offset 표 쌍은 앞 표의
전체 exclusion을 보존하고, 표 그룹 뒤의 host 텍스트는 마지막 표 아래에서 시작한다.

## 2. 예상 코드 변경

### `src/renderer/typeset.rs`

1. co-anchored fits-fresh orphan 가드 직전 placement 기준을 지역 변수로 둔다.
2. 가드가 `advance_column_or_new_page()`를 실행한 경우에만 이 값을 새
   `st.current_height`로 갱신한다.
3. 바로 뒤 whole-fit `place_table_with_text` 호출에서 갱신된 placement 기준을 전달한다.
4. `budget_para_start_height`와 빈-host split 예산 계산은 변경하지 않는다.
5. 선행 co-anchored float가 있는 양수 offset 표는 저장 상단과 현재 flow의 최댓값에서
   배치해 밀린 만큼 exclusion 높이가 잘리지 않게 한다.
6. 표 그룹 뒤 post-text를 배치하기 전에 visible-float exclusion을 적용한다.

### `src/renderer/layout.rs`

1. zero-offset visible float 뒤에 co-anchored 표가 더 있으면 첫 표도 exclusion을 남긴다.
2. 같은 owner 문단의 일반 텍스트는 기존 #1549 계약대로 exclusion을 무시하지만, 같은
   owner의 표 항목 뒤에 emit된 post-text는 exclusion을 소비한다.

예상 형태:

```rust
let mut placement_para_start_height = para_start_height;

if should_defer_whole_coanchored_table {
    st.advance_column_or_new_page();
    placement_para_start_height = st.current_height;
}

// whole-fit placement/exclusion에만 page-local 기준 사용
self.place_table_with_text(
    /* ... */
    placement_para_start_height,
    /* ... */
);
```

실제 구현에서는 이 지역값이 orphan 가드 외 다른 advance 경로까지 잘못 전파되지 않도록
whole-fit 분기 범위를 확인한다.

## 3. 회귀 테스트

### 신규 `tests/issue_2439.rs`

- 페이지 경계 이전에 시작한 visible host의 첫 RowBreak 표가 현재 페이지에 남는다.
- 같은 host의 양수 offset 후속 표는 fresh 페이지로 통째 이월된다.
- 이월된 표의 bbox가 새 페이지 본문 안에서 양의 높이를 가지며, 다음 일반 문단 bbox는
  표의 배타 영역과 겹치지 않는다.
- 대상 페이지의 행/셀 bbox가 37px 같은 비정상 압축 조각으로 붕괴하지 않는다.
- 페이지 수와 PageItem 배치 순서를 핀한다.

### fixture

- 우선 `samples/issue1663_coanchored_float_orphan.hwpx` 또는
  `samples/hwpx/issue1535_coanchored_float_exclusion.hwpx` Clone and Narrow.
- HWP5 전용 경로가 아니면 재현되지 않을 경우, 공개 첨부 원본은 로컬 오라클로만 두고
  핵심 helper/상태 전이 단위 테스트를 추가한다. 원본 HWP의 저장소 편입은 사용자 동의
  없이는 하지 않는다.

### 관련 회귀

```sh
cargo test --test issue_2439
cargo test --test issue_1510 --test issue_1535 --test issue_1549
cargo test --test issue_1663 --test issue_1860
cargo test --test issue_2322_fullpage_form_table_pair
```

## 4. 재현 문서 검증

```sh
RHWP_TABLE_DRIFT=1 RHWP_DIAG_FLOW=1 cargo run --quiet --bin rhwp -- \
  export-svg "/Users/melee/Downloads/고위험의료기기 일별 점검표(버그 제보용).hwp" \
  -o /private/tmp/rhwp-issue2439-after
```

확인값:

- `LAYOUT_OVERFLOW` 미출력
- 이월된 `pi=39 ci=1`의 exclusion이 fresh 페이지 기준으로 생성됨
- `pi=40` 이후 typeset 흐름이 표 배타 영역을 건너뜀
- `pi=52 ci=1`이 본문 하단 37.3px 조각으로 잘리지 않음
- `외형 점검`, `전원선 상태`, `Accessory상태`, `Setting 점검` 라벨이 각 셀에 한 번씩 배치

수정 후 출력은 9쪽이다. 한컴 2024 편집 화면의 10쪽과 다른 마지막 양식 제목 나눔은
가로가 정상인 Microsoft Print to PDF 파일을 확보한 뒤 별도 호환성 항목으로 추적한다.
#2439에서는 반복 표 겹침과 overflow 제거를 완료 조건으로 삼는다.

한컴 2024 PDF는 페이지 수, 내용 순서, 표 비겹침을 비교하는 보조 오라클로 사용한다.
다만 PDF 1쪽의 표가 A4 landscape 페이지 왼쪽에 치우친 출력 설정 차이가 있으므로,
가로 위치의 `visual_accuracy_proxy_percent`는 산출하지 않는다. before/after page 6
raster 또는 SVG를 나란히 검토하고, 가로 배치는 사용자가 제공한 한컴 2024 1쪽 화면을
우선 참조한다.

## 5. 문서·커밋 계획

- Stage 1: fixture/test + `mydocs/working/task_m100_2439_stage1.md`
- Stage 2: `typeset.rs` point-fix + `mydocs/working/task_m100_2439_stage2.md`
- Stage 3: 시각/focused 검증 + `mydocs/working/task_m100_2439_stage3.md`
- 최종: `mydocs/report/task_m100_2439_report.md`, 오늘할일 상태 갱신

커밋·push·PR 생성은 저장소 승인 절차에 따라 별도로 수행한다.
