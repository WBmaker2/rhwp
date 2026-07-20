# PR #2501 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2501](https://github.com/edwardkim/rhwp/pull/2501) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | 네 workflow의 cache, artifact, checkout action 버전 통일 |
| 판단 | 누적 통합 PR에 수용 |

## 검토와 검증

- PR 본문은 `full-renderer-sweep.yml`, `npm-publish.yml`, `release-binary.yml`, `render-diff.yml`의 v4 참조를 현행 버전으로 바꾸는 범위를 설명했고, PR 코멘트는 없었다.
- 기여자 변경 `4b9dd1627`을 충돌 없이 적용했다. 이는 [#2488](https://github.com/edwardkim/rhwp/pull/2488), [#2490](https://github.com/edwardkim/rhwp/pull/2490), [#2499](https://github.com/edwardkim/rhwp/pull/2499)의 workflow 변경을 포괄한다.
- YAML 파싱과 baseline shellcheck 정보 경고를 제외한 actionlint를 통과했고, 변경 버전이 `ci.yml`·`deploy-pages.yml`과 일치함을 확인했다.

## 후속

- workflow 변경이므로 최종 통합 PR head의 GitHub Actions 성공을 확인한 뒤 수용한다.
