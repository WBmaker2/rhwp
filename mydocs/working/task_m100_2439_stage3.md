# Task M100-2439 Stage 3 — focused·시각 검증

- 이슈: [#2439](https://github.com/edwardkim/rhwp/issues/2439)
- 브랜치: `codex/task2439`
- 작성일: 2026-07-19

## 1. focused 테스트

통과:

- `cargo test --test issue_2439 -- --nocapture` — 2/2
- `issue_1510` — 4/4
- `issue_1535` — 1/1
- `issue_1549` — 2/2
- `issue_1663` — 2/2
- `issue_2322_fullpage_form_table_pair` — 2/2

`issue_1535` fixture의 기존 filler 문단 overflow 진단은 출력되지만 테스트 단언은
통과했고, #2439 원본 재출력에는 `LAYOUT_OVERFLOW`가 없다.

## 2. 원본 HWP 재검증

- 수정 전: rhwp 8쪽, 0-based page 5 `para=53`에서 3.8px overflow와 표 겹침.
- 수정 후: rhwp 9쪽, overflow 진단 없음.
- 반복 양식의 두 표는 각 191.6px 높이를 유지하며 순서대로 배치된다.
- 문제 페이지와 최종 페이지를 PDF raster로 확인해 표/라벨/서명/안내문 비겹침을 확인했다.

## 3. 남은 차이

이 단계 당시에는 가로가 정상인 Microsoft Print to PDF 결과 파일이 없어, 한컴 10쪽과
rhwp 9쪽의 차이를 별도 호환성 항목으로 남겼다. 이후 전달된 정답지의 정밀 비교 결과는
`task_m100_2439_stage4.md`에 기록한다.
