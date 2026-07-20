# PR #2511 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2511](https://github.com/edwardkim/rhwp/pull/2511) |
| 작성자 / base | kevin9327 / `devel` |
| 범위 | 브라우저 확장의 `.hml` URL 확장자 인식 |
| 판단 | Safari 원격 검증 보강 후 누적 통합 PR에 수용 |

## 검토와 검증

- PR 본문은 HML 확장자 pattern을 Chrome·Firefox·Safari link detection에 추가하는 범위를 설명했고, PR 코멘트는 없었다.
- 기여자 변경 `76aa00d5f`과 URL resolver 회귀 `301bb07a0`을 적용했다. Safari는 별도 signature gate가 있어 HWPML root·Version을 검사하는 공유 helper를 추가 보정했다.
- HML URL 및 signature regression, Chrome/Firefox build, Safari unsigned Xcode build, 최종 release-test·Clippy·WASM 빌드를 통과했다.

## 후속

- 로컬 Safari signed build의 인증서 부재는 source 결함이 아니며, 최신 CI 통과 뒤 수용한다.
