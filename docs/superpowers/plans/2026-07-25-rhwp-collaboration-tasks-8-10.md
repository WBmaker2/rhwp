# rhwp Firebase Collaboration MVP v1 구현 계획

작성일: 2026-07-25  
대상 저장소: `WBmaker2/rhwp`  
기능 브랜치: `feat/firebase-collaboration-mvp-v1`  
대상 브랜치: `devel`  
Draft PR: `#1`  
구현 상태 기준 커밋: `a4feb75329dd2c380fb511af8e415a9470d22dab`

## 1. 목적

대용량 HWP 문서를 서버에서 한 번 파싱한 뒤, Firebase 인증 사용자 최대 10명이 본문과 1차 표 셀 텍스트를 Yjs로 공동 편집하고 접속자·원격 커서를 확인하며, snapshot 복구를 거쳐 HWPX로 내보낼 수 있는 MVP를 완성한다.

이 문서는 Task 8–10의 구현 결과와 아직 남은 작업을 기준으로, **staging 배포 승인 전까지 수행할 실행 순서와 완료 조건**을 정의한다.

## 2. 고정 아키텍처 원칙

- Rust `Document` IR이 import와 export의 권위 있는 문서 모델이다.
- HWP 파일은 import source이며 실시간 공동 편집 상태가 아니다.
- Yjs가 live collaboration state를 소유한다.
- Studio는 raw 문서 인덱스를 직접 동기화하지 않고 stable ID manifest와 patch를 사용한다.
- Awareness는 접속자·커서용 비영속 상태이며 snapshot이나 Firestore에 저장하지 않는다.
- 클라이언트가 전달한 UID, role, document ID를 신뢰하지 않고 서버가 Firebase token과 membership을 다시 검증한다.
- 역할은 `owner`, `editor`, `viewer`다.
- 문서당 최대 10개의 고유 UID를 허용하고 동일 UID의 여러 탭은 한 명으로 계산한다.
- V1 편집 범위는 본문, 1차 표 셀 텍스트, 기본 이미지 참조다.
- 표 구조와 수식·도형·OLE 등 복잡 개체는 readonly다.
- 명시적 승인 전에는 merge, Firebase 배포, Cloud Run 배포를 수행하지 않는다.

## 3. 상태 범례

- `[x]`: 코드와 focused test가 구현됨.
- `[~]`: 핵심 계약은 구현됐지만 실제 multi-process 또는 staging 검증이 남음.
- `[ ]`: 구현 또는 검증이 아직 필요함.

## 4. 전체 진행 상태

- [x] Task 8A: Rust/WASM collaboration bridge
- [x] Task 8B: Yjs adapter와 Awareness model
- [x] Task 8C: Studio 연결, 접속자 목록, 원격 커서 UI
- [x] Task 9A: Collaboration server Firebase/Cloud Run entrypoint
- [x] Task 9B: Document API Firebase/Cloud Run entrypoint
- [x] Task 9C: staging-safe 구성 템플릿과 정적 validator
- [~] Task 10: recovery/export E2E
- [ ] parse worker와 export worker production process
- [ ] Local Emulator 기반 실제 multi-process E2E
- [ ] 브라우저 두 세션 시각적 smoke test
- [ ] staging 배포와 운영 검증

## 5. Task 8 계획과 구현 결과

### 5.1 Rust/WASM bridge

구현 파일:

- `src/collaboration_wasm.rs`
- `src/lib.rs`
- `tests/collaboration_wasm_bridge.rs`
- `rhwp-studio/src/collaboration/wasm-adapter.ts`

완료 항목:

- [x] `getCollaborationManifest(sourceFingerprint)` 공개.
- [x] `applyCollaborationPatch(manifestJson, patchJson)` 공개.
- [x] 본문·표 셀·기본 이미지 patch JSON 처리.
- [x] patch 적용 후 `set_document`로 layout state 재구축.
- [x] camelCase apply report 반환.
- [x] Studio TypeScript adapter에서 stable ID 경계 제공.

완료 기준:

- Studio가 Rust manifest를 JSON으로 읽을 수 있다.
- remote Yjs 변경을 stable ID patch로 Document IR에 적용할 수 있다.
- patch 이후 페이지와 레이아웃 상태가 재구축된다.

### 5.2 Yjs adapter와 Awareness

구현 파일:

- `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`
- `rhwp-studio/src/collaboration/PresenceController.ts`
- `rhwp-studio/tests/collaboration-yjs-adapter.test.ts`
- `rhwp-studio/tests/collaboration-presence.test.ts`

완료 항목:

- [x] 문단과 표 셀을 각각 독립 `Y.Text`로 관리.
- [x] source fingerprint metadata 저장.
- [x] 서버 Yjs state가 비어 있을 때만 source manifest로 초기화.
- [x] 기존 snapshot state가 있으면 해당 상태를 WASM에 적용.
- [x] local transaction origin과 remote transaction 분리.
- [x] remote apply 중 local event echo 차단.
- [x] viewer local write 차단.
- [x] UID 기반 10색 palette.
- [x] Awareness payload validation.
- [x] local client를 제외한 participant projection.

### 5.3 Studio 인증·연결·UI

구현 파일:

- `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`
- `rhwp-studio/src/collaboration/CollaborationController.ts`
- `rhwp-studio/src/collaboration/PresenceView.ts`
- `rhwp-studio/src/collaboration/RemoteCursorLayer.ts`
- `rhwp-studio/src/collaboration/StudioCursorSource.ts`
- `rhwp-studio/src/collaboration/bootstrap.ts`
- `rhwp-studio/src/collaboration-entry.ts`
- `rhwp-studio/src/engine/input-handler.ts`
- `rhwp-studio/src/main.ts`

완료 항목:

- [x] Firebase Google 로그인과 Firestore membership role 조회.
- [x] Firebase ID token을 Hocuspocus provider에 전달.
- [x] initial sync timeout과 인증 실패 cleanup.
- [x] owner/editor/viewer session 처리.
- [x] local cursor와 selection snapshot 생성.
- [x] stable paragraph/cell target ID 계산.
- [x] 접속자 목록 UI.
- [x] remote caret와 selection overlay.
- [x] zoom, page offset, virtual scroll을 반영한 위치 재계산.
- [x] destroy 시 timer, listener, provider, Y.Doc 정리.
- [ ] 실제 브라우저 두 세션에서 시각적 smoke test.

## 6. Task 9 계획과 구현 결과

### 6.1 Collaboration server production-facing entrypoint

구현 파일:

- `services/collaboration-server/src/firebase-adapters.ts`
- `services/collaboration-server/src/internal-http.ts`
- `services/collaboration-server/src/main.ts`
- `services/collaboration-server/Dockerfile`
- `deploy/cloudrun/collaboration-server.service.yaml`

완료 항목:

- [x] Firebase Admin ID token verifier.
- [x] Firestore membership store.
- [x] Cloud Storage snapshot object store.
- [x] Firestore snapshot metadata store.
- [x] Hocuspocus server와 snapshot persistence composition.
- [x] internal token으로 보호된 export flush route.
- [x] `SIGTERM`/`SIGINT` snapshot flush와 graceful shutdown.
- [x] Node.js 22 container 정의.
- [ ] 실제 Cloud Run에서 WebSocket timeout, concurrency, memory 검증.

### 6.2 Document API production-facing entrypoint

구현 파일:

- `services/document-api/src/firebase-adapters.ts`
- `services/document-api/src/collaboration-client.ts`
- `services/document-api/src/http-server.ts`
- `services/document-api/src/main.ts`
- `services/document-api/Dockerfile`
- `deploy/cloudrun/document-api.service.yaml`

완료 항목:

- [x] Firebase Admin ID token verifier와 Firestore membership lookup.
- [x] Cloud Storage source metadata adapter.
- [x] Firestore transaction parse lease store.
- [x] OIDC Cloud Tasks parse/export enqueue adapter.
- [x] collaboration internal flush HTTP client.
- [x] `/healthz`, upload completion, export HTTP routing.
- [x] JSON body 제한과 graceful shutdown.
- [x] Node.js 22 container 정의.
- [ ] 실제 parse worker process.
- [ ] 실제 export worker process.
- [ ] Cloud Tasks queue와 worker IAM 통합 검증.

### 6.3 Staging-safe 구성

구현 파일:

- `firebase/.firebaserc.example`
- `firebase/firebase.json`
- `firebase/staging.env.example`
- `firebase.json`
- `firestore.rules`
- `storage.rules`
- `deploy/cloudrun/*.service.yaml`
- `scripts/validate_staging_config.py`
- `.github/workflows/staging-config-validate.yml`

완료 항목:

- [x] Firebase Hosting output을 `rhwp-studio/dist`로 지정.
- [x] Auth, Firestore, Storage Emulator port 구성.
- [x] 실제 project ID 대신 staging placeholder 유지.
- [x] immutable image digest placeholder.
- [x] dedicated service account placeholder.
- [x] Secret Manager reference 사용.
- [x] mutable tag, inline secret, credential 파일, 불완전 placeholder 차단 validator.
- [ ] 실제 Firebase/GCP staging project 선택.
- [ ] service account와 최소 IAM role 생성.
- [ ] Secret Manager secret과 Cloud Tasks queue 생성.
- [ ] container build/push와 digest 확정.
- [ ] Firebase Hosting/Rules와 Cloud Run staging 배포.

## 7. Task 10 완료 범위

구현 파일:

- `services/e2e/tests/collaboration-flow.test.ts`
- `tests/collaboration_end_to_end.rs`
- `.github/workflows/collaboration-e2e.yml`

완료된 계약:

- [x] upload completion idempotency.
- [x] 동일 source generation의 parse enqueue 1회.
- [x] 두 Yjs editor의 본문·표 셀 state convergence.
- [x] snapshot 저장과 최신 snapshot 손상 시 이전 정상 snapshot fallback.
- [x] export flush가 queue보다 먼저 실행됨.
- [x] viewer export 거부.
- [x] 동일 UID 여러 탭을 한 명으로 계산.
- [x] 11번째 고유 UID 거부.
- [x] HWPX export 후 재파싱.
- [x] 본문, 표 셀, 기본 이미지 보존.
- [x] 표 셀 내부 readonly 수식 보존.
- [x] Firebase Rules Emulator 계약 실행.

현재 한계:

- service interface와 storage/metadata 일부를 인메모리로 조합한 E2E다.
- Auth, Firestore, Storage Emulator와 두 Node server process를 동시에 구동하지 않는다.
- 실제 Hocuspocus WebSocket reconnect와 server restart를 검증하지 않는다.
- parse/export worker container가 아직 없다.

## 8. 남은 구현 순서

### 단계 1: 최신 CI 실패 안정화

1. Document API workflow 실패 로그를 분석하고 test/build를 복구한다.
2. Collaboration server workflow 실패 로그를 분석하고 test/build를 복구한다.
3. Rust CI 실패 job을 확인하고 format, Clippy, WASM 또는 test 문제를 수정한다.
4. 모든 변경은 focused RED→GREEN 테스트와 별도 커밋으로 유지한다.

### 단계 2: parse/export worker 구현

1. parse Cloud Tasks payload schema와 idempotency key를 고정한다.
2. source HWP를 Storage에서 읽고 Rust parser를 실행하는 worker를 추가한다.
3. manifest와 derived 자산을 canonical Storage path에 기록한다.
4. export worker가 snapshot, 원본 IR, 사용자 이미지를 읽어 HWPX를 생성한다.
5. export 결과를 재파싱하고 Firestore export 상태를 원자적으로 갱신한다.
6. worker Dockerfile과 timeout, memory, retry policy를 정의한다.

### 단계 3: Local Emulator multi-process E2E

1. Auth Emulator test user와 ID token helper를 추가한다.
2. Firestore Emulator에 document, member, lease, snapshot metadata fixture를 작성한다.
3. Storage Emulator에 source, snapshot, export object fixture를 작성한다.
4. Collaboration server와 Document API를 child process로 시작한다.
5. 실제 Hocuspocus provider 두 개를 연결해 본문·셀 수렴을 검증한다.
6. 최신 snapshot을 손상시키고 server restart 후 fallback과 reconnect를 검증한다.
7. Document API export 요청부터 worker 실행과 HWPX 재파싱까지 검증한다.

### 단계 4: 브라우저 smoke test

1. owner/editor 두 브라우저 context를 실행한다.
2. 접속자 목록과 원격 caret/selection을 확인한다.
3. zoom과 scroll 뒤 cursor 재배치를 확인한다.
4. viewer 입력과 export가 차단되는지 확인한다.
5. 연결 끊김과 재연결 후 문서 상태가 수렴하는지 확인한다.

### 단계 5: staging 준비

1. staging project ID와 region을 확정한다.
2. service account별 최소 IAM role을 검토한다.
3. Secret Manager secret과 Cloud Tasks queue를 생성한다.
4. container image를 build/push하고 digest를 고정한다.
5. 비용 한도, 로그 기반 alert, 오류 추적을 설정한다.
6. 사용자 명시적 승인 후에만 staging 배포를 실행한다.

## 9. CI 게이트

구현 상태 기준 커밋 `a4feb75329dd2c380fb511af8e415a9470d22dab`에서 확인된 결과:

성공:

- Collaboration WASM bridge
- Nested collaboration objects
- rhwp-studio collaboration
- Firebase rules
- Staging configuration
- Collaboration recovery E2E
- Render Diff
- CodeQL

실패:

- Rust CI
- Collaboration server
- Document API

따라서 현재 상태를 staging-ready 또는 merge-ready로 판단하지 않는다.

## 10. 배포 승인 전 완료 조건

- [ ] 최신 head의 모든 필수 workflow 성공.
- [ ] parse/export worker와 container test 성공.
- [ ] 실제 multi-process Emulator E2E 성공.
- [ ] 브라우저 두 세션 remote cursor smoke test 성공.
- [ ] staging project, region, IAM, Secret, queue 확정.
- [ ] immutable image digest 확정.
- [ ] 비용 한도와 운영 alert 설정.
- [ ] staging 배포에 대한 사용자 명시적 승인.

위 조건이 완료되기 전에는 merge 또는 deploy하지 않는다.
