# PR #2503 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2503](https://github.com/edwardkim/rhwp/pull/2503) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | `@rhwp/editor` funding metadata 추가 |
| 판단 | [#2504](https://github.com/edwardkim/rhwp/pull/2504)에 완전히 흡수됨 |

## 검토와 검증

- PR 본문은 funding field만 추가하는 범위이며, PR 코멘트는 없었다.
- #2504가 같은 funding field와 README metadata까지 포함하므로 #2503을 별도 cherry-pick하면 중복이다.
- #2504 기준 editor `npm test` 18개와 `npm pack --dry-run`을 통과했다.

## 후속

- 최종 통합 PR에서 #2504로 supersede 처리한다.
