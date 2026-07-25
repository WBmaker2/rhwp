# Task 5 — Studio 로컬 편집 수집과 두 탭 협업 E2E 구현 계획

## 목표

Task 4에서 완성한 `CollaborationContext`, update validator, Rust apply API, WASM wrapper, `CollaborationDocumentAdapter`, `BroadcastChannelTransport`를 실제 로컬 편집 흐름에 연결한다.

최종 흐름은 다음과 같다.

```text
Studio 편집 완료 이벤트
→ LocalEditObserver
→ 현재 문단/셀 텍스트 WASM 조회
→ CollaborationUpdateFactory
→ BroadcastChannelTransport.send
→ 다른 탭 transport 수신
→ CollaborationDocumentAdapter.applyRemoteUpdate
→ Rust 문서 모델 변경
```

## 범위

### Task 5-1 LocalEditObserver

- 협업 가능한 편집 위치 이벤트를 구독한다.
- paragraph와 cell 위치를 지원한다.
- 동일 노드의 연속 변경은 debounce한다.
- 원격 update 적용 중에는 로컬 update를 발행하지 않는다.
- 같은 텍스트는 다시 발행하지 않는다.
- `flush()`와 `stop()`에서 보류 중인 변경을 처리한다.
- 구조 변경 이벤트를 받으면 안전하게 중단한다.

### Task 5-2 편집 이벤트 계약

`CollaborationEditableChange`를 정의한다.

- paragraph: `sectionIndex`, `paragraphIndex`
- cell: `sectionIndex`, `hostParagraphIndex`, `controlIndex`, `cellIndex`
- structure: manifest/registry를 무효화하는 구조 변경

Studio의 모든 일반 `document-changed` 이벤트를 협업 변경으로 간주하지 않는다. 실제 텍스트 편집 성공 지점에서 `collaboration-editable-changed` 이벤트를 발행하도록 연결한다.

### Task 5-3 텍스트 조회 API

Rust:

- `get_collaboration_paragraph_text`
- `get_collaboration_cell_text`

WASM:

- `getCollaborationParagraphText(...)`
- `getCollaborationCellText(...)`

조회 시에도 fingerprint, 위치, StableId를 다시 검증한다. 다중 문단 셀은 Task 4와 동일하게 MVP에서 거부한다.

### Task 5-4 CollaborationUpdateFactory

- `clientId`, `documentFingerprint`, sequence를 보유한다.
- update ID는 `<clientId>:<sequence>` 형식으로 생성한다.
- sequence는 0부터 단조 증가한다.
- paragraph/cell update를 동일 계약으로 생성한다.

### Task 5-5 LocalCollaborationController

- observer가 만든 update를 transport로 전송한다.
- transport가 받은 update를 adapter로 적용한다.
- start/stop 생명주기를 관리한다.
- 중복 start를 방지한다.
- stop 시 observer, transport, subscriber를 모두 정리한다.

### 마지막 단계: 두 탭 E2E

- 동일 session ID를 사용하는 두 브라우저 페이지를 연다.
- 탭 A paragraph 변경이 탭 B에 반영되는지 검증한다.
- 탭 B cell 변경이 탭 A에 반영되는지 검증한다.
- 자기 update 재적용과 무한 재발행이 없는지 검증한다.
- stop 이후 update가 전달되지 않는지 검증한다.

## 설계 제약

- Firebase, Firestore, Yjs, 공유 링크 UI는 변경하지 않는다.
- 현재 단계의 update는 문단/셀 전체 문자열 교체 방식이다.
- 표 구조와 문서 구조 변경은 협업 중 허용하지 않는다.
- 한글 IME 중간 조합 문자열은 발행하지 않고 편집 완료 이벤트만 사용한다.
- 기본 debounce는 200ms로 한다.
- 전체 Studio 빌드에 필요한 `node_modules`가 없으면 focused Node 테스트와 Rust 테스트를 우선 증거로 사용하고, 빌드 미검증 이유를 기록한다.

## TDD 순서

1. Rust text read API 실패 테스트
2. Rust read API 구현
3. WASM wrapper와 TypeScript declaration
4. UpdateFactory 테스트 및 구현
5. LocalEditObserver debounce/dedup/remote suppression/structure-stop 테스트 및 구현
6. LocalCollaborationController 연결 테스트 및 구현
7. Studio 편집 이벤트 emit 지점 최소 연결
8. 두 탭 E2E 작성 및 실행
9. Rust/TypeScript 회귀 테스트, format, diff 검증

## 완료 조건

- [x] paragraph/cell 현재 텍스트를 StableId 검증 후 읽을 수 있다.
- [x] update sequence와 ID가 결정적으로 증가한다.
- [x] 로컬 변경이 debounce 후 1회 전송된다.
- [x] 동일 텍스트는 재전송되지 않는다.
- [x] 원격 적용 중 로컬 update가 생성되지 않는다.
- [x] 구조 변경 시 controller가 안전하게 중단된다.
- [ ] 두 탭 간 paragraph와 cell 변경이 양방향 반영된다.
- [x] stop 이후 메시지가 전달되지 않는다.
- [x] 기존 Task 3/4 테스트가 회귀 없이 통과한다.
- [x] 커밋과 push는 수행하지 않는다.


## 구현 결과

- Task 5-1~5-5 구현 및 focused 테스트 완료.
- Rust collaboration read API와 WASM wrapper 구현 완료.
- Studio `InputHandler.afterEdit` 및 `afterPageLocalEdit`에서 `collaboration-editable-changed` 이벤트를 발행하도록 연결.
- 실제 Chromium 두 탭 E2E 스크립트 작성 완료.
- E2E 실행은 `rhwp-studio/node_modules`가 없어 `puppeteer-core` import 단계에서 중단됨. `npm ci`는 실행 승인 필요로 설치하지 못함.
- 따라서 두 탭 E2E 완료 조건 2개는 실행 검증 전 상태로 유지한다.
