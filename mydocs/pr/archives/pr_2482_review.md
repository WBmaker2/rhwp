# PR #2482 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2482](https://github.com/edwardkim/rhwp/pull/2482) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | HWP5 각주·미주 닫는 장식 문자 `0` 보존 |
| 검토자 | @jangster77 (검토 전 지정) |
| 검토 스냅샷 | 2026-07-20 GitHub 조회: +61/-12, 2 files, `maintainerCanModify=true`, `mergeStateStatus=BEHIND` (동적 참고값) |
| 판단 | 누적 통합 PR에 수용 |

## 검토와 검증

- PR 본문은 닫는 장식 문자 `0`이 `)`로 오염되는 문제를 설명했고, PR 코멘트는 없었다.
- 기여자 변경 `d7a2e556d`를 충돌 없이 적용했다. serializer 보존 변경이며 visual sweep 대상은 아니다.
- HWP5 serializer focused 회귀와 최종 release-test, Clippy, WASM 빌드를 통과했다.

## 후속

- 최종 통합 PR의 최신 CI 통과 뒤 수용한다.
