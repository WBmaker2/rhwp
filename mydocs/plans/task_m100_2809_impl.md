# 구현계획서 — #2809 표 셀 나눔정렬 마지막 줄·잘림 정정

- 이슈: [#2809](https://github.com/edwardkim/rhwp/issues/2809)
- 수행계획서: [`task_m100_2809.md`](task_m100_2809.md)
- 브랜치: `task/2809-distribute-align` (`upstream/devel` @ `58991a768`)
- 작성일: 2026-07-22

## 1. 구현 계약

첨부 HWP의 문제 문단은 `Alignment::Split`(HWPX `DISTRIBUTE_SPACE`)이다. `Split`은
문단의 마지막 줄에서도 내부 공백에 남은 폭을 분배한다. 반면 일반 `Justify`는
기존처럼 마지막 줄과 강제 줄바꿈 줄의 분배를 억제한다. `Split`의 강제 줄바꿈
억제도 기존 동작을 유지한다.

셀 padding, 문단 여백과 저장 `LINE_SEG`는 변경하지 않는다. 다만 음수 자간에서는
마지막 글자의 advance가 실제 glyph ink보다 작으므로, `Split`의 slack 계산에 그
차이를 시각 점유 폭으로 되돌려 마지막 글자가 셀 clip을 넘지 않게 한다.

## 2. 변경 지점

### `src/renderer/layout/paragraph_layout.rs`

1. 정렬 종류와 마지막 줄/머리말·꼬리말/강제 줄바꿈 상태를 받아 공백 분배 여부를
   반환하는 `needs_word_distribution` 헬퍼를 둔다.
2. `Alignment::Split`은 강제 줄바꿈이 아닌 마지막 줄에서도 `true`,
   `Alignment::Justify`는 기존 조건을 유지하도록 분리한다.
3. `Split`과 음수 자간이 함께 쓰인 경우에만 마지막 가시 글자의 ink overhang을
   유효 사용 폭에 더한다. 일반 `Justify`와 다른 정렬 경로는 그대로 둔다.

## 3. 테스트 계획

- `paragraph_layout.rs` 단위 테스트:
  - 단일 마지막 줄에서 `Split=true`, `Justify=false`.
  - `다 같 이`의 두 내부 공백에 양의 slack이 균등하게 배분됨.
  - 음수 자간 `Split`의 최종 advance와 마지막 glyph ink가 셀 폭 안에 들어감.
- 시각 회귀:
  - 이슈 첨부 HWP 2쪽의 셀 clip과 `다/같/이` 문자 x 좌표를 수정 전·후 비교.
- 명령:
  - `cargo test --lib issue_2809_split_alignment_tests`
  - `cargo test --lib`
  - `cargo test --test svg_snapshot`
  - `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings`
  - `wasm-pack build --target web --out-dir pkg`
  - `cd rhwp-studio && npm run e2e:issue-2809`

## 4. 시각 증적 계획

- 입력: 이슈 #2809 첨부 `jubo_20260104.hwp`.
- 기준: HWP 2020 변환 PDF 6쪽, SHA-256
  `a73d50620bf8fe96beaff72ba0e40cd34f396ec75de9798ac1fd0402e28f8e2b`.
- 비교: 문제 2쪽을 144dpi로 맞춰 라벨의 첫/가운데/마지막 글자와 셀 좌우 경계를
  대조하고, WASM Canvas 2배율에서 동일 페이지를 다시 확인한다.
- 사용자의 명시 요청에 따라 테스트에 사용한 원본 ZIP/HWP, 기준 PDF, native sweep,
  WASM E2E, OVR 증적을 저장소에 함께 포함한다.

## 5. 위험과 완화

| 위험 | 완화 |
|---|---|
| `Justify` 마지막 줄까지 함께 벌어짐 | `Split`과 `Justify` 판정을 헬퍼에서 명시적으로 분리하고 음성 테스트를 둔다. |
| 강제 줄바꿈 의미가 달라짐 | `Justify`와 `Split` 모두 기존 강제 줄바꿈 억제를 보존하는 음성 테스트를 둔다. |
| 대용량 증적 누락 | 원본 HWP/PDF와 전체 산출물 압축본의 SHA-256을 증적 README에 고정한다. |
| 폰트 fallback에 따른 폭 차이 | SVG 문자 좌표와 clip 경계를 직접 검증하고 HWP 2020 PDF를 최종 기준으로 둔다. |
