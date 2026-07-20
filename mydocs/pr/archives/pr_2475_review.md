# PR #2475 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2475](https://github.com/edwardkim/rhwp/pull/2475) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | HWPX 각주·미주 번호 모양과 시작 번호 왕복 보존 |
| 검토자 | @jangster77 (검토 전 지정) |
| 검토 스냅샷 | 2026-07-20 GitHub 조회: +92/-19, 1 file, `maintainerCanModify=true`, `mergeStateStatus=BEHIND` (동적 참고값) |
| 판단 | 누적 통합 PR에 수용 |

## 검토와 검증

- PR 본문은 footnote/endnote 번호 종류와 시작 번호의 저장 누락을 설명했고, PR 코멘트는 없었다.
- 기여자 변경 `48316fde5`를 충돌 없이 적용했다. serializer round-trip 변경으로 visual sweep 대상은 아니다.
- HWPX round-trip focused 회귀와 최종 release-test, Clippy, WASM 빌드를 통과했다.

## 후속

- 최종 통합 PR의 최신 CI 통과 뒤 수용한다.
