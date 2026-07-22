# PR #2834 검토 — Task #2809 나눔정렬과 Canvas 음수 자간

- PR: [#2834](https://github.com/edwardkim/rhwp/pull/2834)
- 기준 브랜치: `upstream/devel` `58991a768`
- 작업 브랜치: `task/2809-distribute-align`
- 검토 대상 source head: `da97ef94ca2b43d6a3e93516efe53e5e98969957`
- 상태: Open PR 생성 완료, CI/CodeQL/Render Diff 진행 중

## 판정

승인 가능. `Alignment::Split`의 마지막 줄 분배 의미를 일반 `Justify`와 분리했고,
Canvas 2D가 음수 자간을 glyph 폭 축소로 잘못 적용하던 경로를 제한했다. `Split`
분배는 마지막 glyph의 실제 잉크 여유를 예약한다. 최종 화면은 첫 glyph 폭이
`28/28px`로 동일하고 마지막 `이`도 `22px` 온전히 표시된다. HWP 2020 PDF는 정상
기준으로 유지했다.

## 범위 검토

- 일반 `Justify`, 강제 줄바꿈과 자간 0% 행의 기존 동작은 유지된다.
- visual sweep의 `--dpi`가 SVG에도 적용되어 PDF/rhwp가 같은 배율로 비교된다.
- 이슈 원본 ZIP/HWP, 정상 기준 PDF, 최종 review PNG와 WASM E2E HTML이 포함됐다.
- golden 변경은 HWP 2022 기준에 가까워진 `Split` 좌표 2개로 제한된다.

## 검증

- 전체 lib: `2512 passed; 0 failed; 7 ignored`.
- SVG snapshot: `8 passed; 0 failed`.
- clippy `-D warnings`, fmt, diff, Python 구문 검사: 통과.
- WASM build와 rhwp Studio production build: 통과.
- rhwp Studio E2E assertion `7/7`, Canvas `1126×1587`, 실제 편집기 100% 캡처.
- visual sweep 144dpi: `flagged=0/1`.

상세 증적은 [`assets/task2809/README.md`](assets/task2809/README.md)와
[`task_m100_2809_report.md`](../report/task_m100_2809_report.md)를 따른다.

## PR 후속

1. CI/CodeQL/Render Diff 완료 후 결과를 이 문서에 반영한다.
2. merge 권한과 사용자 승인이 확인된 경우에만 후속 merge/issue close 절차를 수행한다.
