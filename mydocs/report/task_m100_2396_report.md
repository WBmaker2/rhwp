# 최종 보고 — #2396 custom scheme 최상위 legacy 요청 회귀

- 이슈: #2396
- assignee: `postmelee`
- 브랜치: `codex/issue-2396-custom-scheme-legacy-request`
- 기준선: `upstream/devel@af5902b6`
- 수행계획서: `mydocs/plans/task_m100_2396.md`
- 구현계획서: `mydocs/plans/task_m100_2396_impl.md`

## 결론

WKWebView custom URL scheme으로 `rhwp-studio`를 최상위 문서에 로드했을 때 legacy
`rhwp-request`가 origin 검사에서 폐기되어 timeout되는 회귀를 수정했다.

HTTP(S)가 아닌 origin을 일반적으로 허용하지 않고, `parentWindow === hostWindow`인 top-level
same-window 환경만 window identity를 근거로 예외 처리했다. `event.source === parentWindow` 검사는 모든
환경에서 유지하므로 custom scheme iframe parent와 forged sibling 요청은 계속 거부된다.

## 계획 대비 결과

| 단계 | 계획 | 결과 | 커밋 |
|---|---|---|---|
| 계획 | 수행·구현계획과 승인 게이트 | 완료 | `af5e7f19` |
| Stage 1 | positive 회귀 재현, negative 보안 기준선 | 13/14, 의도한 timeout 재현 | `41128eed` |
| Stage 2 | runtime gate 최소 수정, focused 검증 | 14/14 PASS | `11af6aa2` |
| Stage 3 | 전체 frontend test/build | 전체 PASS | `33c17cc1` |
| Stage 4 | 최종 보고와 PR 준비 | 완료 | 이 문서와 PR 초안 |

계획한 파일과 조건만 변경했으며 protocol version, public API, renderer와 WASM 구현에는 변경이 없다.

## 구현

`rhwp-studio/src/embed/runtime.ts`의 runtime 설치 시 top-level identity를 계산한다.

```ts
const isTopLevelSameWindow = options.parentWindow === options.hostWindow;
```

초기 gate는 다음 두 경우만 거부한다.

1. message source가 parent window와 다른 경우
2. origin이 usable HTTP(S)가 아니면서 top-level same-window도 아닌 경우

기존 `isUsableParentOrigin()`과 connect/session/port binding, legacy handler는 변경하지 않았다.

## 회귀 계약

`rhwp-studio/tests/embed-protocol.test.ts`에 다음 두 테스트를 추가했다.

- custom scheme top-level same-window legacy `ready` 요청이 같은 custom origin으로 응답한다.
- custom scheme iframe parent와 forged sibling은 handler에 도달하지 않고 transferred port를 정리한다.

Stage 1에서 첫 테스트의 timeout을 재현하고, Stage 2 후 두 테스트를 포함한 focused 14건이 모두 통과했다.

## 최종 검증

| 게이트 | 결과 |
|---|---|
| Studio + editor Node tests | 364/364 PASS |
| focused embed protocol | 14/14 PASS |
| dev WASM package 생성 | PASS |
| Studio TypeScript + Vite production build | PASS |
| `git diff --check` | PASS |
| 추적 파일 범위 | 운영·계획·보고·runtime·test만 포함 |

`pkg/`, `target/`, `rhwp-studio/node_modules/`, `rhwp-studio/dist/`는 gitignored 생성물로 유지했다.

## 잔여 범위와 위험

- 실제 macOS WKWebView downstream representative suite는 이 저장소 환경에서 실행하지 않았다.
- iframe custom scheme origin 허용, custom scheme allowlist, host 인증 정책은 이번 범위에 포함하지 않는다.
- Vite chunk-size/browser externalization과 wasm-pack prebuilt fallback 경고는 기존 비차단 build 경고다.
- push, PR 생성과 이슈 close는 별도 작업지시자 승인 전까지 수행하지 않는다.

## 완료 판단

수행계획서의 기능·보안·검증 완료 기준을 모두 충족했다. 로컬 브랜치는 PR 준비 상태이며, PR 초안은
`mydocs/report/task_m100_2396_pr_draft.md`에 기록한다.
