# rhwp Collaboration Tasks 8–10 구현 계획

작성일: 2026-07-25  
대상 저장소: `WBmaker2/rhwp`  
기능 브랜치: `feat/firebase-collaboration-mvp-v1`  
대상 브랜치: `devel`  
Draft PR: `#1`

## 목표

`rhwp-studio`를 Firebase Auth와 Hocuspocus/Yjs 공동 편집 서버에 연결하고, 접속자와 원격 커서를 표시한다. Collaboration server와 Document API에 production Firebase/Cloud Run 어댑터와 staging-safe 배포 템플릿을 추가한다. 마지막으로 업로드, 파싱 요청, 공동 편집, snapshot 복구, HWPX export와 readonly 개체 보존을 자동 검증한다.

## 아키텍처 원칙

- Rust `Document` IR이 import/export의 권위 있는 원본이다.
- HWP는 import source이며 live state가 아니다.
- Yjs가 live collaboration state를 소유한다.
- TypeScript client는 raw document index를 직접 수정하지 않고 stable ID manifest와 patch를 사용한다.
- Awareness는 비영속 상태이며 snapshot과 Firestore에 저장하지 않는다.
- client가 전달한 UID, role, document ID를 신뢰하지 않고 server에서 다시 검증한다.
- owner/editor/viewer 역할을 유지한다.
- 문서당 최대 10개의 고유 Firebase UID를 허용한다.
- 동일 UID의 여러 탭은 한 명으로 계산한다.
- V1 편집 범위는 본문, 1차 표 셀 텍스트, 기본 이미지 참조다.
- 복잡 개체와 표 구조는 readonly다.
- Firebase Hosting, Rules, Cloud Run, Cloud Tasks 또는 다른 GCP resource를 명시적 승인 없이 배포하지 않는다.

## 상태 범례

- `[x]`: 코드와 focused test가 구현됨.
- `[~]`: 일부 구현 또는 인메모리 검증만 완료됨.
- `[ ]`: 아직 구현 또는 실제 환경 검증이 필요함.

## 전체 상태

- [x] Task 8A: Rust/WASM collaboration bridge
- [x] Task 8B: Yjs adapter와 Awareness model
- [x] Task 8C: Studio 연결, 접속자, 원격 커서
- [x] Task 9A: Collaboration server production entrypoint
- [x] Task 9B: Document API production entrypoint
- [x] Task 9C: staging-safe configuration template와 validator
- [~] Task 10: recovery/export E2E
- [ ] 실제 staging 배포와 smoke test

---

## Task 8A: Rust/WASM Collaboration Bridge

### 구현 파일

- `src/collaboration_wasm.rs`
- `src/lib.rs`
- `tests/collaboration_wasm_bridge.rs`
- `rhwp-studio/src/collaboration/wasm-adapter.ts`

### 공개 인터페이스

- `HwpDocument.getCollaborationManifest(sourceFingerprint): string`
- `HwpDocument.applyCollaborationPatch(manifestJson, patchJson): string`
- `RhwpCollaborationWasmAdapter.getManifest(sourceFingerprint?)`
- `RhwpCollaborationWasmAdapter.applyPatch(manifest, patch)`

### 작업 상태

- [x] missing bridge method를 확인하는 failing Rust test 작성.
- [x] collaboration manifest JSON 반환.
- [x] text, cell, image patch JSON DTO deserialize.
- [x] patch 적용 후 `set_document`로 layout state 재구축.
- [x] apply report를 camelCase JSON으로 반환.
- [x] TypeScript wrapper와 stable ID type 추가.
- [x] focused Rust bridge test 추가.

### 완료 기준

- manifest를 JSON으로 읽을 수 있다.
- 원격 본문과 표 셀 변경을 stable ID patch로 적용할 수 있다.
- externally applied patch 이후 page/layout state가 다시 생성된다.

---

## Task 8B: Yjs Adapter와 Awareness Model

### 구현 파일

- `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`
- `rhwp-studio/src/collaboration/PresenceController.ts`
- `rhwp-studio/tests/collaboration-yjs-adapter.test.ts`
- `rhwp-studio/tests/collaboration-presence.test.ts`
- `.github/workflows/rhwp-studio-collaboration.yml`

### 작업 상태

- [x] 문단과 표 셀을 독립 `Y.Text`로 초기화.
- [x] source fingerprint metadata 저장.
- [x] 서버 Yjs state가 비어 있을 때만 source manifest text 초기화.
- [x] 기존 서버 state가 있으면 recovered state를 WASM에 적용.
- [x] local document change를 전용 transaction origin으로 기록.
- [x] remote transaction만 WASM patch로 적용.
- [x] remote apply 중 local event 재기록 차단.
- [x] viewer local write 차단.
- [x] UID 기반 10색 palette index 계산.
- [x] Awareness payload validation.
- [x] local client를 제외한 remote participant projection.
- [x] Yjs와 Hocuspocus provider dependency lock.

### 완료 기준

- 두 client가 동일 문단과 셀의 Yjs state에 수렴한다.
- local/remote transaction origin이 분리된다.
- viewer는 remote state만 수신한다.
- Awareness state가 문서 snapshot에 포함되지 않는다.

---

## Task 8C: Studio 연결, 접속자, 원격 커서

### 구현 파일

- `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`
- `rhwp-studio/src/collaboration/CollaborationController.ts`
- `rhwp-studio/src/collaboration/PresenceView.ts`
- `rhwp-studio/src/collaboration/RemoteCursorLayer.ts`
- `rhwp-studio/src/collaboration/StudioCursorSource.ts`
- `rhwp-studio/src/collaboration/bootstrap.ts`
- `rhwp-studio/src/collaboration-entry.ts`
- `rhwp-studio/src/engine/input-handler.ts`
- `rhwp-studio/src/main.ts`
- `rhwp-studio/index.html`
- `rhwp-studio/tests/collaboration-controller.test.ts`

### 작업 상태

- [x] Firebase Web SDK Google sign-in.
- [x] Firestore membership role 조회.
- [x] ID token을 Hocuspocus provider token으로 전달.
- [x] initial sync timeout과 auth failure cleanup.
- [x] owner/editor/viewer session state.
- [x] viewer read-only adapter 구성.
- [x] local cursor와 selection snapshot 생성.
- [x] stable paragraph/cell target ID 계산.
- [x] 접속자 목록 UI.
- [x] remote caret와 selection overlay.
- [x] zoom과 virtual scroll 좌표 반영.
- [x] zoom/document view change에서 cursor rerender.
- [x] collaboration 환경이 완전할 때만 bootstrap.
- [x] destroy에서 timer, listeners, provider, Y.Doc 정리.
- [ ] 실제 브라우저 두 세션의 시각적 smoke test.

### 완료 기준

- editor 두 명이 Hocuspocus room에 연결된다.
- 접속자 목록과 원격 cursor가 local client를 제외하고 표시된다.
- viewer는 문서를 수정하지 못한다.
- page zoom과 scroll 이후 cursor 위치가 다시 계산된다.

---

## Task 9A: Collaboration Server Production Entrypoint

### 구현 파일

- `services/collaboration-server/src/firebase-adapters.ts`
- `services/collaboration-server/src/internal-http.ts`
- `services/collaboration-server/src/main.ts`
- `services/collaboration-server/src/index.ts`
- `services/collaboration-server/Dockerfile`
- `services/collaboration-server/tests/firebase-adapters.test.ts`
- `services/collaboration-server/tests/server.test.ts`

### 작업 상태

- [x] Firebase Admin Auth verifier.
- [x] Firestore membership store.
- [x] Cloud Storage snapshot object store.
- [x] Firestore snapshot metadata store.
- [x] 환경 변수 검증.
- [x] Hocuspocus server와 snapshot persistence composition.
- [x] internal token으로 보호된 export flush HTTP route.
- [x] `SIGTERM`/`SIGINT` snapshot flush와 graceful shutdown.
- [x] Node 22 container image 정의.
- [ ] 실제 Cloud Run instance에서 WebSocket timeout, concurrency, memory 검증.

### 완료 기준

- Cloud Run process가 Firebase Admin default credentials로 시작한다.
- WebSocket 요청에서 token과 membership을 검증한다.
- shutdown 전에 등록된 문서 snapshot을 flush한다.
- 내부 export flush route는 shared internal token 없이는 접근할 수 없다.

---

## Task 9B: Document API Production Entrypoint

### 구현 파일

- `services/document-api/src/firebase-adapters.ts`
- `services/document-api/src/collaboration-client.ts`
- `services/document-api/src/http-server.ts`
- `services/document-api/src/main.ts`
- `services/document-api/src/index.ts`
- `services/document-api/Dockerfile`
- `services/document-api/tests/firebase-adapters.test.ts`
- `services/document-api/tests/http-server.test.ts`

### 작업 상태

- [x] Firebase Admin ID token verifier.
- [x] Firestore membership lookup.
- [x] Cloud Storage source metadata adapter.
- [x] Firestore transaction parse lease store.
- [x] OIDC Cloud Tasks parse/export enqueue adapter.
- [x] collaboration internal flush HTTP client.
- [x] `/healthz` route.
- [x] upload completion과 export route dispatch.
- [x] JSON body limit과 error response.
- [x] graceful HTTP shutdown.
- [x] Node 22 container image 정의.
- [ ] 실제 parse worker process 구현.
- [ ] 실제 export worker process 구현.
- [ ] Cloud Tasks queue와 worker IAM integration test.

### 완료 기준

- API process가 Firebase Admin default credentials로 시작한다.
- 업로드 완료 요청이 source object와 ACL을 검증한다.
- parse lease와 Cloud Tasks enqueue가 원자적 계약을 유지한다.
- export는 collaboration flush 결과 snapshot을 queue payload에 포함한다.

---

## Task 9C: Staging-safe Configuration

### 구현 파일

- `firebase/.firebaserc.example`
- `firebase/firebase.json`
- `firebase/staging.env.example`
- `firebase.json`
- `firestore.rules`
- `storage.rules`
- `deploy/cloudrun/collaboration-server.service.yaml`
- `deploy/cloudrun/document-api.service.yaml`
- `deploy/cloudrun/README.md`
- `scripts/validate_staging_config.py`
- `.github/workflows/staging-config-validate.yml`

### 작업 상태

- [x] Hosting output을 `rhwp-studio/dist`로 지정.
- [x] Auth, Firestore, Storage Emulator port 구성.
- [x] staging project placeholder 유지.
- [x] digest-pinned container image placeholder.
- [x] dedicated service account placeholder.
- [x] Secret Manager token reference.
- [x] credential 형태와 mutable image tag 차단 validator.
- [x] inline internal secret 차단 validator.
- [x] staging configuration validation workflow.
- [ ] 실제 Firebase/GCP staging project 선택.
- [ ] service account와 최소 IAM role 생성.
- [ ] Secret Manager secret 생성.
- [ ] Cloud Tasks queue 생성.
- [ ] image build/push와 digest 확정.
- [ ] Firebase Hosting/Rules와 Cloud Run staging 배포.

### 완료 기준

- repository에는 secret이나 실제 service-account key가 없다.
- templates는 immutable image digest와 Secret Manager reference를 강제한다.
- 실제 배포는 별도 승인 단계에서만 실행한다.

---

## Task 10: Recovery와 Export 종단 검증

### 구현 파일

- `services/e2e/package.json`
- `services/e2e/package-lock.json`
- `services/e2e/tests/collaboration-flow.test.ts`
- `tests/collaboration_end_to_end.rs`
- `.github/workflows/collaboration-e2e.yml`

### 완료된 범위

- [x] upload completion idempotency.
- [x] 동일 source generation에서 parse enqueue 1회.
- [x] 두 Yjs editor의 본문과 셀 state convergence.
- [x] snapshot 저장과 최신 snapshot 손상.
- [x] restart 후 이전 정상 snapshot fallback.
- [x] export flush가 queue보다 먼저 실행됨.
- [x] viewer export 거부.
- [x] 동일 UID 여러 탭을 한 명으로 계산.
- [x] 11번째 고유 UID 거부.
- [x] HWPX export 후 재파싱.
- [x] 본문, 셀, 기본 이미지 보존.
- [x] 표 셀 내부 readonly 수식 보존.
- [x] Firebase rules Emulator 계약을 같은 E2E workflow에서 실행.

### 부분 완료 또는 남은 범위

- [~] process-level E2E는 service interface와 storage/metadata를 인메모리로 조합함.
- [ ] Auth Emulator token으로 실제 세 service 인증.
- [ ] Firestore Emulator에 실제 membership, lease, snapshot metadata 기록.
- [ ] Storage Emulator에 실제 source, snapshot, export object 기록.
- [ ] 실제 Hocuspocus WebSocket 두 client 연결.
- [ ] Collaboration server process restart와 socket reconnect.
- [ ] Document API HTTP 요청부터 실제 worker까지 실행.
- [ ] parse worker와 export worker container 검증.
- [ ] browser-level remote cursor smoke test.

### 다음 구현 순서

1. `services/e2e`에 emulator process harness를 추가한다.
2. Auth Emulator test user와 ID token 발급 helper를 추가한다.
3. Firestore와 Storage Emulator에 document, member, source object fixture를 작성한다.
4. Collaboration server와 Document API를 child process로 시작한다.
5. 실제 Hocuspocus provider 두 개를 연결하고 text/cell convergence를 검증한다.
6. snapshot object를 의도적으로 손상시킨 뒤 Collaboration server를 재시작한다.
7. Document API export 요청으로 flush와 export worker를 실행한다.
8. 생성된 HWPX를 Rust parser로 재파싱한다.
9. readonly nested object와 삽입 이미지가 보존됐는지 확인한다.
10. staging 배포 전 모든 CI gate를 승인·재실행한다.

---

## CI와 승인 게이트

문서 작성 직전 PR head `97003137099b064eae7667d6b0e9329d6366b336`의 GitHub Actions는 `action_required` 상태였다. 최신 head가 검증됐다고 간주하지 않는다.

다음 workflow가 모두 성공해야 staging 준비 완료로 판단한다.

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

## 배포 승인 전 최종 체크리스트

- [ ] 최신 head의 모든 CI workflow 성공.
- [ ] actual emulator multi-process E2E 성공.
- [ ] parse/export worker 구현과 container test 성공.
- [ ] staging project ID와 region 확정.
- [ ] service account와 IAM 검토.
- [ ] Secret Manager와 Cloud Tasks queue 준비.
- [ ] container image digest 확정.
- [ ] 비용 한도와 로그/오류 알림 설정.
- [ ] staging 배포에 대한 사용자 명시적 승인.

위 항목이 완료되기 전에는 merge 또는 deploy하지 않는다.
