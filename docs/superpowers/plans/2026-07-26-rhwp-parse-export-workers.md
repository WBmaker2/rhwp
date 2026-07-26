# rhwp Parse/Export Workers Implementation Plan

> Execute task-by-task with focused tests. Do not deploy, merge, or create cloud resources.

**Goal:** Cloud Tasks가 호출하는 production-facing worker가 200 MiB 이하 HWP 원본을 native Rust로 파싱해 collaboration manifest를 저장하고, Yjs snapshot을 HWPX로 내보낸 뒤 재파싱 검증과 Firestore 상태 갱신을 완료한다.

**Architecture:** Node.js worker는 Cloud Tasks HTTP, Firebase Storage/Firestore, Yjs snapshot 해석, idempotency를 담당한다. `rhwp-collaboration-worker` native Rust binary는 원본 파싱, deterministic manifest 생성, stable-ID patch 적용, HWPX 직렬화와 재파싱 검증을 담당한다. 원본 문서는 임시 파일로 내려받아 200 MiB 파일을 JS/WASM 메모리에 중복 적재하지 않는다.

## Fixed contracts

- Parse payload: `{ schemaVersion: 1, documentId, sourceGeneration, sourcePath }`.
- Export payload: `{ schemaVersion: 1, documentId, exportId, snapshotPath }`.
- Source path: `documents/{documentId}/source/original.hwp`.
- Manifest path: `documents/{documentId}/derived/collaboration-manifest.json`.
- Export path: `documents/{documentId}/exports/{exportId}.hwpx`.
- Source size: `0 < size <= 200 MiB`.
- Yjs keys: `collaboration:metadata`, `sourceFingerprint`, `paragraph:{stableId}`, `cell:{stableId}`.
- No raw image bytes in Yjs. V1 worker exports paragraph and first-level table-cell text; inserted-image collaboration remains a later task.
- Cloud Tasks retries are idempotent through Firestore task claims.
- No Firebase/Cloud Run/Cloud Tasks deployment without explicit user approval.

### Task 1: Native Rust collaboration worker

- [x] Add `src/bin/rhwp-collaboration-worker.rs` with `import` and `export` commands.
- [x] Compute `blake3:<hex>` source fingerprint.
- [x] Reject a manifest created from another source generation.
- [x] Apply stable-ID paragraph/cell patch.
- [x] Serialize HWPX and reparse before atomic publication.
- [x] Add native roundtrip and fingerprint mismatch integration tests.

### Task 2: Worker payload and Yjs patch contracts

**Files:** `services/document-worker/src/contracts.ts`, `yjs-patch.ts`, tests.

- [ ] Strictly validate payload schema and safe IDs/paths.
- [ ] Decode Yjs snapshot update and verify source fingerprint/schema version.
- [ ] Build minimal paragraph/cell replacement patch from manifest.
- [ ] Reject unknown or mismatched collaboration metadata.

### Task 3: Worker orchestration and idempotency

**Files:** `services/document-worker/src/worker.ts`, `runner.ts`, tests.

- [ ] Parse: stat source, validate generation/type/size, claim task, download, run native import, upload manifest, mark ready.
- [ ] Export: claim export, download source/manifest/snapshot, build patch, run native export, upload HWPX, mark ready.
- [ ] Mark retryable failure without publishing ready pointers.
- [ ] Always clean temporary files.

### Task 4: Firebase adapters and Cloud Tasks HTTP

**Files:** Firebase adapters, HTTP server, main entrypoint, Dockerfile, tests.

- [ ] Use file-backed Storage downloads/uploads.
- [ ] Use Firestore transactions for parse/export claims and status updates.
- [ ] Require Cloud Tasks request headers outside emulator mode.
- [ ] Add `/healthz`, `/run/parse`, `/run/export`.
- [ ] Add graceful shutdown and Node.js 22 container.

### Task 5: Document API queue contract

- [ ] Generate a safe export ID before enqueue.
- [ ] Include `schemaVersion` and `exportId` in task payloads.
- [ ] Return canonical export path based on export ID, not the full Cloud Tasks resource name.
- [ ] Add payload/idempotency tests.

### Task 6: CI and staging-safe templates

- [ ] Add worker npm lockfile and focused workflow.
- [ ] Build and test the native binary plus Node worker.
- [ ] Add digest-pinned Cloud Run template with dedicated service account and resource limits.
- [ ] Extend static staging validator.
- [ ] Keep all deployment actions disabled.
