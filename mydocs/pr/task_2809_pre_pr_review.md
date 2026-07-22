# Task #2809 사전 PR 검토

- 기준 브랜치: `upstream/devel` `58991a768`
- 작업 브랜치: `task/2809-distribute-align`
- 상태: 로컬 검토 완료, push/PR 생성 승인 대기

## 판정

승인 가능. `Alignment::Split`의 마지막 줄 분배 의미를 일반 `Justify`와 분리했고,
음수 자간에서 마지막 glyph의 ink가 advance보다 넓어 rhwp 셀 clip에 잘리던 문제를
`Split` 범위 안에서 보정했다. PDF는 정상 기준으로 유지했다.

## 범위 검토

- 일반 `Justify`, 강제 줄바꿈과 자간 0% 행의 기존 동작은 유지된다.
- visual sweep의 `--dpi`가 SVG에도 적용되어 PDF/rhwp가 같은 배율로 비교된다.
- 이슈 원본 ZIP/HWP, 정상 기준 PDF, native/WASM/OVR 증적이 모두 포함됐다.
- golden 변경은 HWP 2022 기준에 가까워진 `Split` 좌표 2개로 제한된다.

## 검증

- 전체 lib: `2512 passed; 0 failed; 7 ignored`.
- SVG snapshot: `8 passed; 0 failed`.
- clippy `-D warnings`, fmt, diff, Python 구문 검사: 통과.
- WASM build: 통과. rhwp Studio E2E assertion `4/4`, Canvas `1126×1587`.
- visual sweep 144dpi: `flagged=0/1`; 대상 glyph 잘림 없음.
- OVR5: 5개 샘플, 개체 회귀 0건.

상세 증적은 [`assets/task2809/README.md`](assets/task2809/README.md)와
[`task_m100_2809_report.md`](../report/task_m100_2809_report.md)를 따른다.

## PR 생성 후 후속

1. 문서명을 `pr_{번호}_review.md`로 바꾸고 PR URL·head SHA를 고정한다.
2. PR 본문에 `Closes #2809`와 증적 링크를 포함한다.
3. CI/CodeQL 완료 후 결과를 검토문서에 반영한다.
4. merge 권한과 사용자 승인이 확인된 경우에만 후속 merge/issue close 절차를 수행한다.
