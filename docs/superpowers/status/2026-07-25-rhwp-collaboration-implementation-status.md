# rhwp Firebase Collaboration MVP v1 구현 현황

작성일: 2026-07-25  
대상 저장소: `WBmaker2/rhwp`  
기능 브랜치: `feat/firebase-collaboration-mvp-v1`  
대상 브랜치: `devel`  
Draft PR: `#1`

## 1. 현재 요약

- Task 1–7: 구현 완료.
- Task 8: `rhwp-studio`의 Yjs 동기화, Firebase 로그인 경계, 접속자 목록, Awareness, 원격 커서 렌더링 구현 완료.
- Task 9: Collaboration server와 Document API의 Firebase/Cloud Run production 어댑터, HTTP 진입점, Dockerfile, staging 템플릿과 정적 검증 구현 완료.
- Task 10: 인메모리 프로세스 경계 E2E, Firebase 보안 규칙 Emulator 테스트, Rust HWPX 왕복 검증 구현 완료. 실제 Auth/Firestore/Storage Emulator와 두 서버 프로세스 및 WebSocket을 한 번에 구동하는 완전 통합 E2E는 아직 남아 있음.
- 실제 Firebase Hosting, Cloud Run, Cloud Tasks, Firestore, Storage 배포는 수행하지 않음.
- PR은 Draft이며 병합하지 않음.

## 2. Rust 협업 코어

### 구현됨

- 원본 문서 fingerprint와 구조 경로를 사용한 결정적 `StableId` 생성.
- collaboration manifest schema v1.
- 본문 문단과 1차 표 셀 텍스트를 편집 가능 대상으로 import.
- 표 구조와 지원하지 않는 개체를 readonly 대상으로 분류.
- 표 셀 문단과 중첩 표 내부 controls를 재귀 순회해 readonly 개체를 수집.
- 안정 ID 기반 본문·표 셀 텍스트 패치.
- PNG, JPEG, WebP 기본 이미지 삽입과 `BinData` 등록.
- readonly 또는 알 수 없는 target 수정 거부.
- HWPX serialize/reparse 왕복 검증.
- 대표 복잡 개체인 표 셀 내부 수식이 셀 텍스트 변경 후에도 보존되는 회귀 테스트.

### WASM 경계

- `src/collaboration_wasm.rs`에서 다음 메서드를 노출함.
  - `getCollaborationManifest(sourceFingerprint)`
  - `applyCollaborationPatch(manifestJson, patchJson)`
- 외부 Yjs 상태를 Document IR에 적용한 뒤 `set_document`로 레이아웃 상태를 재구축함.
- Studio 전용 TypeScript adapter가 raw document index 대신 stable ID manifest와 patch만 사용함.

### 관련 테스트

- `tests/collaboration_model.rs`
- `tests/collaboration_nested_objects.rs`
- `tests/collaboration_wasm_bridge.rs`
- `tests/collaboration_end_to_end.rs`

## 3. Collaboration server

### 구현됨

- Hocuspocus/Yjs WebSocket 서버.
- Firebase ID token 검증 인터페이스와 Firestore membership ACL.
- 역할: `owner`, `editor`, `viewer`.
- 문서별 최대 10개의 고유 UID 제한.
- 동일 UID의 여러 탭은 한 명으로 계산.
- snapshot debounce, size threshold, last-user, export, shutdown flush.
- snapshot SHA-256 checksum 검증.
- 손상되거나 없는 최신 snapshot에서 이전 정상 snapshot으로 fallback.
- 최신 10개 snapshot 유지.
- Storage object 기록 후 Firestore metadata pointer를 게시하는 순서 보장.

### production 어댑터

- Firebase Admin Auth verifier.
- Firestore membership store.
- Cloud Storage snapshot object store.
- Firestore snapshot metadata store.
- 환경 변수 검증.
- `SIGTERM`/`SIGINT`에서 snapshot flush 후 종료.
- Document API가 호출하는 내부 export flush HTTP 경계와 internal token 검증.
- Cloud Run용 Dockerfile과 service template.

### 주요 파일

- `services/collaboration-server/src/auth.ts`
- `services/collaboration-server/src/participants.ts`
- `services/collaboration-server/src/persistence.ts`
- `services/collaboration-server/src/firebase-adapters.ts`
- `services/collaboration-server/src/internal-http.ts`
- `services/collaboration-server/src/main.ts`

## 4. Document API

### 구현됨

- 정규 Storage 경로 생성과 path traversal 차단.
- 업로드 완료 API.
- 원자적 parse lease.
- 동일 generation에 대한 중복 parse 요청 억제.
- 원본 HWP 크기 100–200 MiB와 media type 검증.
- owner/editor 권한 검증.
- HWPX export 요청 전에 collaboration server의 `flushForExport` 강제 호출.
- viewer export 거부.
- `/healthz`, upload completion, export HTTP routing.
- JSON body 1 MiB 제한과 오류 응답.

### production 어댑터

- Firebase Admin ID token verifier.
- Firestore member lookup.
- Cloud Storage object metadata 조회.
- Firestore transaction 기반 parse lease store.
- OIDC가 포함된 Cloud Tasks parse/export enqueue adapter.
- Collaboration server 내부 flush HTTP client.
- Node HTTP listener와 graceful shutdown.
- Cloud Run용 Dockerfile과 service template.

### 주요 파일

- `services/document-api/src/firebase-adapters.ts`
- `services/document-api/src/collaboration-client.ts`
- `services/document-api/src/http-server.ts`
- `services/document-api/src/main.ts`
- `services/document-api/src/routes/complete-upload.ts`
- `services/document-api/src/routes/export-hwpx.ts`

## 5. Firebase 보안 규칙

### Firestore

- 문서 metadata와 export metadata 읽기는 문서 member에게만 허용.
- owner만 title, member, share link 관리 가능.
- parse 상태, snapshot pointer, derived 결과, export 상태 등 서버 관리 필드의 client write 차단.

### Cloud Storage

- 원본 HWP는 owner가 정규 경로에 create-only로 업로드.
- 원본 크기 100–200 MiB 검증.
- 사용자 이미지는 owner/editor만 업로드.
- 이미지 최대 20 MiB, PNG/JPEG/WebP 제한.
- uploader UID metadata 위조와 overwrite 차단.
- snapshot client read/write 차단.
- export 결과는 member만 다운로드.

### 검증

- Firestore와 Storage Local Emulator Suite 계약 테스트.
- 실제 Firebase 프로젝트에는 rules를 배포하지 않음.

## 6. rhwp-studio 공동 편집

### Yjs adapter

- manifest의 본문 문단과 표 셀을 각각 독립된 `Y.Text`로 초기화.
- local document change를 전용 transaction origin으로 Yjs에 반영.
- remote transaction만 WASM patch로 적용해 echo loop 차단.
- 기존 서버 Yjs state가 있으면 source text를 덮어쓰지 않고 recovered state를 Document IR에 적용.
- viewer 세션은 remote state를 수신하지만 local document change를 Yjs에 기록하지 않음.

### 인증과 연결

- Firebase Web SDK Google sign-in.
- Firestore membership 조회.
- Firebase ID token을 Hocuspocus provider token으로 전달.
- 초기 sync timeout과 인증 실패 정리.
- reconnect 가능한 controller lifecycle과 destroy 정리.
- 환경 설정과 `collabDocument` query parameter가 모두 있을 때만 collaboration bootstrap.

### Awareness와 UI

- Awareness payload:
  - `userId`
  - `displayName`
  - `photoURL`
  - UID 기반 `colorIndex`
  - stable `targetId`
  - `targetKind`
  - `anchorOffset`
  - `headOffset`
  - `lastActiveAt`
- local client를 제외한 접속자 목록.
- 원격 caret과 selection overlay.
- zoom, page offset, virtual scroll 좌표를 반영한 remote cursor 재배치.
- InputHandler에서 collaboration selection snapshot을 제공.
- Awareness 상태는 snapshot이나 Firestore에 영속화하지 않음.

### 주요 파일

- `rhwp-studio/src/collaboration/CollaborationController.ts`
- `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`
- `rhwp-studio/src/collaboration/PresenceController.ts`
- `rhwp-studio/src/collaboration/PresenceView.ts`
- `rhwp-studio/src/collaboration/RemoteCursorLayer.ts`
- `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`
- `rhwp-studio/src/collaboration/StudioCursorSource.ts`
- `rhwp-studio/src/collaboration/bootstrap.ts`
- `rhwp-studio/src/collaboration-entry.ts`

## 7. Staging-safe 배포 구성

### 구현됨

- Firebase Hosting이 `rhwp-studio/dist`를 제공하도록 구성.
- Auth, Firestore, Storage Emulator port 구성.
- `.firebaserc.example`과 staging 환경 변수 예제.
- Collaboration server와 Document API Cloud Run service YAML.
- digest-pinned container image placeholder.
- dedicated service account placeholder.
- Secret Manager reference를 통한 internal token 주입.
- credential 형태, mutable `latest` tag, inline secret, 불완전 placeholder를 차단하는 정적 validator.

### 수행하지 않음

- 실제 GCP/Firebase project ID 확정.
- 실제 service account, IAM role, Secret Manager secret, Cloud Tasks queue 생성.
- container image build/push.
- Firebase Hosting/Rules 배포.
- Cloud Run 배포.
- staging smoke test.

## 8. Task 10 검증 현황

### 완료된 검증

- upload completion idempotency와 한 번의 parse enqueue.
- 두 Yjs editor state convergence.
- snapshot 저장, 최신 snapshot 손상, process restart 이후 이전 정상 snapshot fallback.
- export 전에 snapshot flush가 queue보다 먼저 실행됨.
- viewer export가 flush와 queue 전에 거부됨.
- 동일 UID 여러 탭을 1명으로 계산.
- 11번째 고유 UID 거부.
- HWPX export 후 재파싱.
- 본문, 표 셀, 삽입 이미지 보존.
- 표 셀 내부 readonly 수식 보존.
- Firebase rules Emulator 계약.

### 아직 남은 검증

현재 `services/e2e/tests/collaboration-flow.test.ts`는 service interfaces와 Yjs를 인메모리로 조합한다. 다음 항목은 아직 실제 프로세스 수준으로 검증되지 않았다.

- Auth Emulator에서 발급한 token으로 Studio/Document API/Collaboration server 인증.
- Firestore Emulator에 실제 membership, lease, snapshot metadata 기록.
- Storage Emulator에 실제 source/snapshot/export object 기록.
- 실제 Hocuspocus WebSocket 두 client 연결과 server restart.
- 실제 Document API HTTP 요청에서 Cloud Tasks 대체 worker까지의 흐름.
- parse worker와 export worker의 실제 container 구현 및 실행.
- 브라우저 두 세션에서 접속자와 원격 커서의 시각적 smoke test.

## 9. CI 상태

문서 작성 직전 PR head `97003137099b064eae7667d6b0e9329d6366b336`에서 관련 GitHub Actions는 `action_required` 상태였다. 따라서 최신 head의 CI 성공을 주장하지 않는다. 승인 또는 재실행 후 다음 workflow를 다시 확인해야 한다.

- Rust CI
- Collaboration WASM bridge
- Nested collaboration objects
- rhwp-studio collaboration
- Collaboration server
- Document API
- Firebase rules
- Staging configuration
- Collaboration recovery E2E
- CodeQL

## 10. 알려진 제한과 배포 차단 항목

- V1 공동 편집 범위는 본문, 1차 표 셀 텍스트, 기본 이미지 참조다.
- 행/열/셀 병합 구조와 복잡 개체 편집은 지원하지 않는다.
- 중첩 수식 보존 회귀는 대표 사례이며 모든 HWP control 조합의 완전 보존을 의미하지 않는다.
- parse/export Cloud Tasks worker가 아직 실제 production process로 구현·배포되지 않았다.
- 현재 E2E는 완전한 multi-process Emulator 통합 테스트가 아니다.
- staging/production project별 IAM과 Secret 설정이 확정되지 않았다.
- 최신 head CI가 아직 성공으로 확인되지 않았다.

위 차단 항목이 해소되기 전에는 staging 배포도 승인하지 않는다.
