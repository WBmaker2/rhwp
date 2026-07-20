# PR #2506 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2506](https://github.com/edwardkim/rhwp/pull/2506) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | Chrome extension version을 manifest 단일 소스로 전환 |
| 판단 | 메인터너 attribute 보정 후 누적 통합 PR에 수용 |

## 검토와 검증

- PR 본문은 content script와 DevTools helper의 고정 version literal을 manifest 읽기로 대체하는 범위를 설명했고, PR 코멘트는 없었다.
- 기여자 변경 `2c56f6a9b` 뒤 producer는 `data-hwp-extension-version`을 쓰는데 consumer가 다른 attribute를 읽는 결함을 메인터너가 `042ab976f`로 보정했다.
- source-level 회귀 15개, JavaScript syntax, Chrome production build와 최종 release-test·Clippy·WASM 빌드를 통과했다.

## 후속

- 최종 통합 PR의 최신 CI 통과 뒤 수용한다.
