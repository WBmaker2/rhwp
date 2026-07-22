# 구현계획서 — #2809 표 셀 나눔정렬 마지막 줄 정정

- 이슈: [#2809](https://github.com/edwardkim/rhwp/issues/2809)
- 수행계획서: [`task_m100_2809.md`](task_m100_2809.md)
- 브랜치: `task/2809-distribute-align` (`upstream/devel` @ `58991a768`)
- 작성일: 2026-07-22

## 1. 구현 계약

첨부 HWP의 문제 문단은 `Alignment::Split`(HWPX `DISTRIBUTE_SPACE`)이다. `Split`은
문단의 마지막 줄을 포함한 모든 줄에서 내부 공백에 남은 폭을 분배한다. 반면 일반
`Justify`는 기존처럼 마지막 줄과 강제 줄바꿈 줄의 분배를 억제한다.

셀 padding, 문단 여백, 저장 `LINE_SEG`, 공백 분배 산식은 현재 값이 HWP 2020
계약과 일치하므로 변경하지 않는다.

## 2. 변경 지점

### `src/renderer/layout/paragraph_layout.rs`

1. 정렬 종류와 마지막 줄/머리말·꼬리말/강제 줄바꿈 상태를 받아 공백 분배 여부를
   반환하는 `needs_word_distribution` 헬퍼를 둔다.
2. `Alignment::Split`은 마지막 줄에서도 `true`, `Alignment::Justify`는 기존 조건을
   유지하도록 분리한다.
3. `compute_line_extra_spacing`의 내부 공백 개수·slack 산식과 다른 정렬 경로는
   그대로 둔다.

## 3. 테스트 계획

- `paragraph_layout.rs` 단위 테스트:
  - 단일 마지막 줄에서 `Split=true`, `Justify=false`.
  - `다 같 이`의 두 내부 공백에 양의 slack이 균등하게 배분됨.
- 시각 회귀:
  - 이슈 첨부 HWP 2쪽의 셀 clip과 `다/같/이` 문자 x 좌표를 수정 전·후 비교.
- 명령:
  - `cargo test --lib issue_2809_split_alignment_tests`
  - `cargo test --lib`
  - `cargo test --test svg_snapshot`
  - `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings`

## 4. 시각 증적 계획

- 입력: 이슈 #2809 첨부 `jubo_20260104.hwp`.
- 기준: HWP 2020 변환 PDF 6쪽, SHA-256
  `a73d50620bf8fe96beaff72ba0e40cd34f396ec75de9798ac1fd0402e28f8e2b`.
- 비교: 문제 2쪽을 144dpi 상당으로 맞춰 라벨의 첫/가운데/마지막 글자와 셀 좌우
  경계를 대조한다. 이슈 원본 자체는 저장소에 추가하지 않는다.

## 5. 위험과 완화

| 위험 | 완화 |
|---|---|
| `Justify` 마지막 줄까지 함께 벌어짐 | `Split`과 `Justify` 판정을 헬퍼에서 명시적으로 분리하고 음성 테스트를 둔다. |
| 강제 줄바꿈 의미가 달라짐 | 기존 `Justify` 조건은 그대로 보존하고 `Split` 정렬에만 독립 계약을 적용한다. |
| 첨부 문서의 재배포 권한 불명 | 원본은 임시 시각 증적으로만 사용하고 영구 테스트는 코드 단위 최소 재현으로 만든다. |
| 폰트 fallback에 따른 폭 차이 | SVG 문자 좌표와 clip 경계를 직접 검증하고 HWP 2020 PDF를 최종 기준으로 둔다. |
