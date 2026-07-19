# PR #2398 리뷰 — custom scheme 최상위 legacy 요청 복구

## 메타데이터

| 항목 | 값 |
|---|---|
| PR | [#2398](https://github.com/edwardkim/rhwp/pull/2398) |
| 관련 이슈 | [#2396](https://github.com/edwardkim/rhwp/issues/2396) |
| 작성자 | `postmelee` |
| base / head | `devel` / `codex/issue-2396-custom-scheme-legacy-request` |
| 리뷰 경로 | collaborator self-merge 후보 |
| 최신 `devel` 통합 | `upstream/devel@9b2216c8`, merge commit `6f0d1cdc` |
| merge 전제 | 최종 PR head의 relevant checks 통과와 작업지시자 승인 |

## 변경 범위

- custom URL scheme으로 로드된 top-level same-window 문서에서 legacy `rhwp-request`만 허용한다.
- custom scheme top-level v1 `rhwp-connect`, iframe parent, forged sibling은 계속 거부한다.
- 거부된 MessageChannel port 정리와 이후 legacy 요청 복구를 회귀 테스트로 고정한다.
- protocol version, public API, renderer, WASM 구현은 변경하지 않는다.

## 리뷰 발견과 보정

최초 구현은 top-level same-window라는 조건만으로 unusable origin 예외를 적용해 custom scheme v1
`rhwp-connect`까지 허용했다. 이는 #2396의 의도인 legacy 호환 복구보다 넓은 권한이었다.

보정 커밋 `5e25b0b0`에서 예외 조건을 `event.data?.type === 'rhwp-request'`까지 제한했다. 추가 테스트는
custom scheme v1 connect가 binding을 만들지 않고 port를 닫는지, 그 거부 뒤에도 legacy `ready`가 정상
응답하는지를 함께 검증한다.

## 검증

| 게이트 | 결과 |
|---|---|
| focused embed protocol | 15/15 PASS |
| Studio + editor Node tests | 365/365 PASS |
| dev WASM package 생성 | PASS |
| Studio TypeScript + Vite production build | PASS |
| `git diff --check` | PASS |
| GitHub Actions (`5e25b0b0`) | CI, CodeQL, Render Diff PASS |
| 최신 `devel` 통합 | 충돌 없이 완료; 최종 head CI 재확인 필요 |

## 시각 검증 판단

renderer, DOM/CSS, 페이지 출력과 UI를 변경하지 않는 message gate 수정이므로 별도 visual sweep 대상이 아니다.

## 잔여 위험

- 실제 macOS WKWebView downstream representative suite는 이 저장소 환경에서 별도로 실행하지 않았다.
- custom scheme v1 MessageChannel connect와 iframe custom scheme origin 허용은 이번 변경 범위가 아니다.
- 최종 문서 커밋과 최신 `devel` 통합 뒤의 PR head checks는 merge 전에 다시 확인해야 한다.

## 최종 의견

코드 리뷰에서 발견한 권한 범위 확대는 보정됐고, 회귀 테스트와 로컬 검증 및 보정 커밋 CI가 통과했다.
최종 PR head의 relevant checks가 모두 통과하고 작업지시자가 승인하면 merge할 수 있다. merge 뒤 #2396의
자동 close 여부와 후속 문서 상태를 확인한다.
