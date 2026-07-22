# PR #2658 검토 기록

| 항목 | 내용 |
|---|---|
| PR | [#2658](https://github.com/edwardkim/rhwp/pull/2658) |
| 작성자 / base | [@postmelee](https://github.com/postmelee) / `devel` |
| reviewer | [@jangster77](https://github.com/jangster77), [@edwardkim](https://github.com/edwardkim) |
| 관련 이슈 | [#2656](https://github.com/edwardkim/rhwp/issues/2656) |
| 범위 | Chrome/Edge 설정 저장·복구, options 초기화·오류 처리, 다운로드 자동 열기 중복·fail-closed 방어 |
| 처리 경로 | collaborator self-PR head 보강 후 최신 CI와 재검토를 기다리는 경로 |

## 검토 결론

저장 실패를 성공으로 표시하던 options UI, 초기 로딩 경쟁, 설치 시 기본값 덮어쓰기, sync read 실패,
동일 download id 중복 탭 위험에 대한 기존 PR 보강은 유지할 수 있다.

[requested-changes review](https://github.com/edwardkim/rhwp/pull/2658#pullrequestreview-4745744846)에서
지적된 blocker는 local snapshot이 없는 기존 설치의 partial sync였다. update 직후 sync에서
`autoOpen`만 누락되면 기존 구현은 read 성공으로 판정해 기본값 `true`를 반환하고 local snapshot에도
굳혔다.

보강안은 다음 두 시점을 모두 방어한다.

- `update`와 `chrome_update`에서 현재 유효한 설정을 local snapshot으로 선보존한다.
- legacy key 또는 schema metadata만 남은 partial sync는 clean install과 구분하고, 유효한
  `autoOpen` 근거가 없으면 자동 동작을 fail-closed 처리한다. 이 상태의 default `true`는
  last-known-good snapshot으로 기록하지 않는다.

clean install의 `autoOpen=true` 기본 동작과 유효한 local snapshot 복구는 별도 회귀 테스트로 유지했다.
따라서 requested-changes의 재현 경로는 로컬 구현 기준으로 해소됐으며, 최신 PR head CI와 reviewer
재검토를 기다리는 후보로 판단한다.

## 렌더 영향과 시각 검증

변경 범위는 Chrome 확장의 storage와 Service Worker 제어 흐름, 테스트, 관련 문서다. Rust, WASM,
renderer, layout, golden, 샘플은 변경하지 않으므로 visual sweep 대상이 아니다.

## 로컬 검증

- 보강 전 red: 2 failed / 15 passed
- settings-store + lifecycle: 19 passed, 0 failed
- Chrome options + service worker: 41 passed, 0 failed
- shared + Firefox 다운로드 회귀: 76 passed, 0 failed
- Chrome/Firefox dist 계약: 3 passed, 0 failed
- Chrome/Firefox 확장 빌드: 각각 168 modules transformed, 성공
- source/dist `background.js`, `settings-store.js`, `extension-lifecycle.js`, `options.js` byte 비교: 통과
- 변경 JavaScript `node --check`: 통과
- `git diff --check`: 통과

## 작성 시점 참고 상태와 merge 전 조건

- 보강 작성 기준 원격 head: `7505db1d692d5c7a1525a2301a3d520ce5d5da1b`
- 작성 시점 참고값: `MERGEABLE` / `BEHIND` / `CHANGES_REQUESTED`
- 기존 원격 head의 GitHub Actions는 성공했지만, 보강 코드가 포함된 최신 head의 결과가 아니다.
- 최종 merge 조건:
  - 최신 `upstream/devel` 동기화 뒤 충돌 없음
  - 보강 코드가 포함된 최신 PR head 기준 GitHub Actions 통과
  - requested-changes reviewer 재검토
  - 이 review 문서와 기존 `mydocs/orders/20260721.md`가 PR diff에 포함됨
  - 작업지시자 merge 승인

requested-changes가 단일 동작 영역으로 수렴하고 실행 순서도 commit, devel sync, 재검증, push,
재검토 요청으로 고정되어 별도 `pr_2658_review_impl.md`는 작성하지 않는다.
