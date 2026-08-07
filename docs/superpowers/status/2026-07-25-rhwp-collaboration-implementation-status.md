# rhwp Firebase Collaboration MVP v1 구현 현황

작성일: 2026-07-25  
대상 저장소: `WBmaker2/rhwp`  
기능 브랜치: `feat/firebase-collaboration-mvp-v1`  
대상 브랜치: `devel`  
Draft PR: `#1`  
구현 상태 기준 커밋: `a4feb75329dd2c380fb511af8e415a9470d22dab`

## 1. 현재 요약

- Task 1–7은 구현 완료 상태다.
- Task 8의 Rust/WASM bridge, Yjs 동기화, Firebase 로그인 경계, 접속자 목록, Awareness, 원격 커서 UI가 구현됐다.
- Task 9의 Collaboration server와 Document API production-facing 어댑터, HTTP entrypoint, Dockerfile, Firebase Hosting·Cloud Run staging-safe 템플릿과 정적 validator가 구현됐다.
- Task 10의 인메모리 service-level recovery/export E2E, Firebase Rules Emulator 테스트, Rust HWPX 재파싱 검증이 구현됐다.
- 실제 Auth·Firestore·Storage Emulator와 두 Node server process, Hocuspocus WebSocket, parse/export worker를 함께 구동하는 완전한 multi-process E2E는 남아 있다.
- 실제 Firebase Hosting, Rules, Cloud Run, Cloud Tasks 배포는 수행하지 않았다.
- PR은 Draft이며 merge되지 않았다.

## 2. PR 상태

구현 상태 기준:

- PR: `WBmaker2/rhwp#1`
- 상태: open
- Draft: true
- Mergeable: true
- Merged: false
- 기능 브랜치: `feat/firebase-collaboration-mvp-v1`
- 기준 브랜치: `devel`

문서 갱신 커밋은 구현 상태 기준 커밋 이후에 추가되므로, 실제 branch head는 이 문서의 기준 커밋보다 앞설 수 있다.

## 3. Rust 협업 코어

### 구현됨

- source fingerprint와 구조 경로를 이용한 결정적 `StableId`.
- collaboration manifest schema v1.
- 본문 문단과 1차 표 셀 텍스트 import.
- 표 구조와 지원하지 않는 개체의 readonly 분류.
- 표 셀 문단 및 중첩 표 controls의 재귀 readonly 수집.
- stable ID 기반 본문·표 셀 텍스트 patch.
- PNG, JPEG, WebP 기본 이미지 삽입과 `BinData` 등록.
- readonly 또는 알 수 없는 target 수정 거부.
- HWPX serialize/reparse 왕복 검증.
- 표 셀 내부 수식이 셀 텍스트 변경 뒤에도 보존되는 대표 회귀 테스트.

### WASM 경계

- `HwpDocument.getCollaborationManifest(sourceFingerprint)`.
- `HwpDocument.applyCollaborationPatch(manifestJson, patchJson)`.
- patch 적용 후 `set_document`로 레이아웃 상태 재구축.
- Studio TypeScript adapter는 raw index 대신 stable ID manifest와 patch만 사용.

### 주요 테스트

- `tests/collaboration_model.rs`
- `tests/collaboration_nested_objects.rs`
- `tests/collaboration_wasm_bridge.rs`
- `tests/collaboration_end_to_end.rs`

## 4. Collaboration server

### 기본 서버

- Hocuspocus/Yjs WebSocket server.
- Firebase ID token 검증 경계.
- Firestore membership ACL.
- `owner`, `editor`, `viewer` 역할.
- 문서별 최대 10개의 고유 UID 제한.
- 동일 UID 여러 탭을 한 명으로 계산.
- snapshot debounce, size threshold, last-user, export, shutdown flush.
- snapshot SHA-256 checksum 검증.
- 최신 snapshot 손상 또는 누락 시 이전 정상 snapshot fallback.
- 최신 10개 snapshot 유지.
- Storage object 기록 후 Firestore metadata pointer 게시.

### production-facing 어댑터

- Firebase Admin Auth verifier.
- Firestore membership store.
- Cloud Storage snapshot object store.
- Firestore snapshot metadata store.
- 환경 변수 검증.
- internal token으로 보호된 export flush HTTP route.
- `SIGTERM`과 `SIGINT`에서 snapshot flush 후 graceful shutdown.
- Node.js 22 Dockerfile과 Cloud Run service template.

### 아직 검증되지 않음

- 실제 Cloud Run WebSocket timeout.
- instance concurrency와 memory 한도.
- Cloud Run instance restart 이후 socket reconnect.
- staging service account IAM.

## 5. Document API

### 구현됨

- canonical Storage path와 traversal 차단.
- upload completion API.
- Firestore transaction 기반 parse lease.
- 동일 source generation의 중복 parse enqueue 억제.
- 원본 HWP 100–200 MiB와 media type 검증.
- owner/editor ACL.
- export 전에 collaboration server flush 호출.
- viewer export 거부.
- `/healthz`, upload completion, export route.
- JSON body 1 MiB 제한과 일관된 오류 응답.
- graceful HTTP shutdown.

### production-facing 어댑터

- Firebase Admin ID token verifier.
- Firestore membership lookup.
- Cloud Storage source metadata adapter.
- Firestore parse lease store.
- OIDC Cloud Tasks parse/export enqueue adapter.
- Collaboration server internal flush client.
- Node.js 22 Dockerfile과 Cloud Run service template.

### 아직 구현되지 않음

- 실제 parse worker process.
- 실제 export worker process.
- worker container와 retry policy.
- Cloud Tasks queue와 worker IAM integration test.

## 6. Firebase 보안 규칙

### Firestore

- 문서 metadata와 export metadata 읽기는 member에게만 허용.
- owner만 title, member, share link 관리 가능.
- parse 상태, snapshot pointer, derived 결과, export 상태 등 server-managed field의 client write 차단.

### Cloud Storage

- owner만 canonical source path에 HWP create 허용.
- 원본 크기 100–200 MiB 검증.
- owner/editor만 user image 업로드.
- 이미지 최대 20 MiB, PNG/JPEG/WebP 제한.
- uploader UID metadata 위조와 overwrite 차단.
- snapshot client read/write 차단.
- export 결과는 document member만 읽기 허용.

### 검증

- Firestore와 Storage Local Emulator Suite 계약 테스트가 있다.
- 실제 Firebase project에는 rules를 배포하지 않았다.

## 7. rhwp-studio 공동 편집

### Yjs adapter

- manifest의 문단과 표 셀을 독립 `Y.Text`로 관리.
- server Yjs state가 비어 있을 때만 source manifest로 초기화.
- 기존 state가 있으면 recovered state를 WASM Document IR에 적용.
- local transaction origin과 remote transaction 분리.
- remote apply echo loop 차단.
- viewer local write 차단.

### 인증과 연결

- Firebase Web SDK Google sign-in.
- Firestore membership role 조회.
- Firebase ID token을 Hocuspocus provider token으로 전달.
- initial sync timeout과 인증 실패 cleanup.
- reconnect 가능한 controller lifecycle.
- collaboration 환경과 `collabDocument` query parameter가 모두 있을 때만 bootstrap.

### Awareness와 UI

Awareness payload:

- `userId`
- `displayName`
- `photoURL`
- UID 기반 `colorIndex`
- stable `targetId`
- `targetKind`
- `anchorOffset`
- `headOffset`
- `lastActiveAt`

구현된 UI:

- local client를 제외한 접속자 목록.
- remote caret과 selection overlay.
- zoom, page offset, virtual scroll을 반영한 cursor 재배치.
- InputHandler의 collaboration selection snapshot.
- disconnect와 destroy 시 timer, listener, provider, Y.Doc 정리.

남은 검증:

- 실제 브라우저 두 context의 remote cursor 시각적 smoke test.
- viewer UI의 모든 편집 command 차단 회귀.
- network disconnect와 reconnect 후 state convergence.

## 8. Staging-safe 배포 구성

### 구현됨

- Firebase Hosting public directory: `rhwp-studio/dist`.
- Auth, Firestore, Storage Emulator port.
- `.firebaserc.example`과 staging 환경 변수 예제.
- Collaboration server와 Document API Cloud Run YAML.
- digest-pinned image placeholder.
- dedicated service account placeholder.
- Secret Manager reference로 internal token 주입.
- mutable image tag, inline secret, credential 파일, 불완전 placeholder를 차단하는 validator.
- staging configuration validation workflow.

### 수행하지 않음

- 실제 GCP/Firebase staging project 확정.
- service account와 IAM role 생성.
- Secret Manager secret 생성.
- Cloud Tasks queue 생성.
- container image build/push.
- Firebase Hosting/Rules 배포.
- Cloud Run 배포.
- staging smoke test.

## 9. Task 10 검증 현황

### 완료된 검증

- upload completion idempotency.
- 동일 generation에서 parse enqueue 1회.
- 두 Yjs editor의 본문과 표 셀 state convergence.
- snapshot 저장과 최신 snapshot 손상.
- restart model에서 이전 정상 snapshot fallback.
- export flush가 queue보다 먼저 실행됨.
- viewer export가 flush와 queue 전에 거부됨.
- 동일 UID 여러 탭을 한 명으로 계산.
- 11번째 고유 UID 거부.
- HWPX export 후 Rust 재파싱.
- 본문, 표 셀, 기본 이미지 보존.
- 표 셀 내부 readonly 수식 보존.
- Firebase Rules Emulator 계약.

### 남은 검증

현재 `services/e2e/tests/collaboration-flow.test.ts`는 service interface와 Yjs, storage/metadata 일부를 인메모리로 조합한다.

아직 실제로 검증되지 않은 항목:

- Auth Emulator token으로 Studio, Document API, Collaboration server 인증.
- Firestore Emulator membership, lease, snapshot metadata 기록.
- Storage Emulator source, snapshot, export object 기록.
- 실제 Hocuspocus WebSocket 두 client 연결.
- Collaboration server process restart와 socket reconnect.
- Document API HTTP 요청부터 parse/export worker까지의 실행.
- parse/export worker container.
- 브라우저 두 세션 접속자·원격 커서 시각 검증.

## 10. CI 상태

구현 상태 기준 커밋 `a4feb75329dd2c380fb511af8e415a9470d22dab`에서 확인된 GitHub Actions 결과다.

### 성공

- Collaboration WASM bridge
- Nested collaboration objects
- rhwp-studio collaboration
- Firebase rules
- Staging configuration
- Collaboration recovery E2E
- Render Diff
- CodeQL

### 실패

- Rust CI
- Collaboration server
- Document API

따라서 최신 구현 상태는 아직 merge-ready 또는 staging-ready가 아니다. 실패 workflow의 test/build 로그를 분석하고 수정한 뒤, 문서 갱신 이후의 최신 head에서 전체 gate를 다시 확인해야 한다.

## 11. 알려진 제한

- V1 공동 편집 범위는 본문, 1차 표 셀 텍스트, 기본 이미지 참조다.
- 행·열 추가/삭제, 셀 병합/분할, 복잡 개체 편집은 지원하지 않는다.
- 표 셀 내부 수식 보존 테스트는 대표 회귀이며 모든 HWP control 조합의 완전 보존을 의미하지 않는다.
- parse/export worker가 아직 production process로 구현되지 않았다.
- 현재 E2E는 완전한 multi-process Emulator 통합 테스트가 아니다.
- staging/production project별 IAM, Secret, queue, region이 확정되지 않았다.

## 12. 배포 차단 항목

- 최신 head의 모든 필수 workflow 성공.
- parse/export worker 구현과 container test.
- Local Emulator multi-process E2E.
- 브라우저 remote cursor smoke test.
- staging project, region, IAM, Secret Manager, Cloud Tasks queue 확정.
- immutable container image digest 확정.
- 비용 한도, 로그, 오류 alert 설정.
- 사용자 명시적 staging 배포 승인.

위 항목이 해소되기 전에는 staging 또는 production 배포를 진행하지 않는다.
