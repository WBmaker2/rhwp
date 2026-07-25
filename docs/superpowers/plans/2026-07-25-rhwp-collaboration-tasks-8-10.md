# rhwp Collaboration Tasks 8–10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect `rhwp-studio` to the authenticated Hocuspocus/Yjs collaboration service, add production Firebase/Cloud Run adapters and staging-safe deployment configuration, and verify the complete recovery/export path against local emulators without deploying resources.

**Architecture:** `rhwp-studio` owns authentication UI, awareness, Yjs synchronization, and rendering of participants/cursors. Rust/WASM exposes collaboration manifest and patch APIs so the TypeScript adapter never edits raw document indices directly. Cloud Run services receive concrete Firebase Admin, Firestore, Cloud Storage, and Cloud Tasks adapters through environment-driven entrypoints. End-to-end verification runs only against the Firebase Local Emulator Suite and in-process service boundaries.

**Tech Stack:** Rust, wasm-bindgen, TypeScript 7, Vite 8, Yjs 13, Hocuspocus 4, Firebase Web/Admin SDK, Firestore/Storage Emulator, Node.js 22, GitHub Actions.

## Global Constraints

- Work only in `WBmaker2/rhwp` on `feat/firebase-collaboration-mvp-v1` targeting `devel`.
- Keep PR #1 as Draft; do not merge or submit upstream.
- Do not deploy Firebase Hosting, Firebase rules, Cloud Run, Cloud Tasks, or any Google Cloud resource.
- Authentication and authorization must be revalidated by the services; client-supplied roles are not trusted.
- HWP remains an import source; Yjs remains the live collaboration state.
- V1 editable scope is body text, table-cell text, and basic image references; unsupported objects remain readonly.
- Maximum participants is 10 unique Firebase UIDs; multiple tabs for one UID count once.
- Every behavior follows RED → GREEN and receives a focused CI gate.

---

### Task 8A: Rust/WASM Collaboration Bridge

**Files:**
- Modify: `src/collaboration/apply.rs`
- Modify: `src/wasm_api.rs`
- Modify: `rhwp-studio/src/core/wasm-bridge.ts`
- Create: `tests/collaboration_wasm_bridge.rs`

**Interfaces:**
- Produces: `HwpDocument.getCollaborationManifest(sourceFingerprint): string`
- Produces: `HwpDocument.applyCollaborationPatch(manifestJson, patchJson): string`
- Produces: `WasmBridge.getCollaborationManifest(sourceFingerprint?)`
- Produces: `WasmBridge.applyCollaborationPatch(manifest, patch)`

- [ ] **Step 1: Add a failing Rust bridge contract test**
- [ ] **Step 2: Run the focused test and observe missing bridge methods**
- [ ] **Step 3: Add serde contracts for text/image patches and apply reports**
- [ ] **Step 4: Expose manifest generation and patch application through wasm-bindgen**
- [ ] **Step 5: Rebuild document layout after externally applied patches**
- [ ] **Step 6: Add typed `WasmBridge` wrappers and run Rust/studio builds**

---

### Task 8B: Yjs Adapter and Awareness Model

**Files:**
- Modify: `rhwp-studio/package.json`
- Modify: `rhwp-studio/package-lock.json`
- Create: `rhwp-studio/src/collaboration/types.ts`
- Create: `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`
- Create: `rhwp-studio/src/collaboration/PresenceController.ts`
- Create: `rhwp-studio/tests/collaboration-yjs-adapter.test.ts`
- Create: `rhwp-studio/tests/collaboration-presence.test.ts`
- Create: `.github/workflows/rhwp-studio-collaboration.yml`

**Interfaces:**
- Produces: deterministic `colorIndexForUser(uid)` over a 10-color palette
- Produces: validated awareness payload with stable target ID and anchor/head offsets
- Produces: `RhwpYjsAdapter.initialize(manifest)` and `destroy()`
- Consumes: local `document-changed` events and remote Yjs transactions

- [ ] **Step 1: Write failing awareness and transaction-origin tests**
- [ ] **Step 2: Run focused Node tests and observe missing modules**
- [ ] **Step 3: Implement section/paragraph/cell Yjs initialization**
- [ ] **Step 4: Mirror local text to Yjs using a local transaction origin**
- [ ] **Step 5: Apply remote Yjs state through the WASM patch bridge without echo loops**
- [ ] **Step 6: Implement non-persistent awareness state and deterministic colors**
- [ ] **Step 7: Lock dependencies and run tests/build**

---

### Task 8C: Studio Connection, Participants, and Remote Cursors

**Files:**
- Create: `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`
- Create: `rhwp-studio/src/collaboration/CollaborationController.ts`
- Create: `rhwp-studio/src/collaboration/PresenceView.ts`
- Create: `rhwp-studio/src/collaboration/RemoteCursorLayer.ts`
- Create: `rhwp-studio/src/collaboration/bootstrap.ts`
- Modify: `rhwp-studio/src/engine/input-handler.ts`
- Modify: `rhwp-studio/src/main.ts`
- Create: `rhwp-studio/tests/collaboration-controller.test.ts`

**Interfaces:**
- Consumes: `VITE_FIREBASE_*`, `VITE_COLLABORATION_URL`, and `collabDocument` URL parameter
- Produces: Google sign-in/connect/disconnect UI
- Produces: participant list and remote cursor overlays
- Produces: local selection snapshot from `InputHandler`

- [ ] **Step 1: Write failing controller lifecycle and presence projection tests**
- [ ] **Step 2: Add a readonly-safe local cursor snapshot API**
- [ ] **Step 3: Connect Firebase Auth token to `HocuspocusProvider`**
- [ ] **Step 4: Publish cursor/selection awareness on editor activity**
- [ ] **Step 5: Render participants and remote cursors; exclude the local client**
- [ ] **Step 6: Bootstrap collaboration only when a document ID and complete environment exist**
- [ ] **Step 7: Verify viewer mode, reconnect, destroy, and production build**

---

### Task 9A: Collaboration Server Production Entrypoint

**Files:**
- Create: `services/collaboration-server/src/firebase-adapters.ts`
- Create: `services/collaboration-server/src/main.ts`
- Modify: `services/collaboration-server/src/index.ts`
- Modify: `services/collaboration-server/package.json`
- Modify: `services/collaboration-server/package-lock.json`
- Create: `services/collaboration-server/tests/firebase-adapters.test.ts`
- Create: `services/collaboration-server/tests/main.test.ts`
- Create: `services/collaboration-server/Dockerfile`

**Interfaces:**
- Produces: Firebase Admin token/membership adapters
- Produces: Cloud Storage snapshot object store
- Produces: Firestore snapshot metadata store
- Produces: environment-validated Hocuspocus process entrypoint with graceful shutdown

- [ ] **Step 1: Write failing adapter and environment tests**
- [ ] **Step 2: Implement object and metadata stores with canonical paths and transactions**
- [ ] **Step 3: Compose `SnapshotStore`, `YjsSnapshotPersistence`, and collaboration server**
- [ ] **Step 4: Add SIGTERM/SIGINT shutdown flush and container health behavior**
- [ ] **Step 5: Build and test the container entrypoint**

---

### Task 9B: Document API Production Entrypoint

**Files:**
- Create: `services/document-api/src/firebase-adapters.ts`
- Create: `services/document-api/src/http-server.ts`
- Create: `services/document-api/src/main.ts`
- Modify: `services/document-api/src/index.ts`
- Modify: `services/document-api/package.json`
- Modify: `services/document-api/package-lock.json`
- Create: `services/document-api/tests/firebase-adapters.test.ts`
- Create: `services/document-api/tests/http-server.test.ts`
- Create: `services/document-api/Dockerfile`

**Interfaces:**
- Produces: Firebase Auth, Firestore membership and transactional parse-lease adapters
- Produces: Cloud Storage object metadata adapter
- Produces: Cloud Tasks parse/export queue adapters
- Produces: authenticated HTTP routes for upload completion, export, and health checks

- [ ] **Step 1: Write failing adapter and routing tests**
- [ ] **Step 2: Implement Firebase Admin and Cloud Storage adapters**
- [ ] **Step 3: Implement Firestore parse lease transactions**
- [ ] **Step 4: Implement OIDC Cloud Tasks enqueue adapters**
- [ ] **Step 5: Compose the Node HTTP listener and graceful shutdown**
- [ ] **Step 6: Run tests and TypeScript build**

---

### Task 9C: Staging-Safe Configuration

**Files:**
- Create: `firebase/.firebaserc.example`
- Modify: `firebase/firebase.json`
- Create: `firebase/staging.env.example`
- Create: `deploy/cloudrun/collaboration-server.service.yaml`
- Create: `deploy/cloudrun/document-api.service.yaml`
- Create: `deploy/cloudrun/README.md`
- Create: `.github/workflows/staging-config-validate.yml`

**Interfaces:**
- Produces: placeholder-only staging configuration with no project IDs or secrets
- Produces: validation that rejects committed service-account keys, unresolved image tags, public buckets, and unauthenticated service settings

- [ ] **Step 1: Write failing staging configuration validation**
- [ ] **Step 2: Add Hosting rewrites, emulator ports, and environment examples**
- [ ] **Step 3: Add Cloud Run service templates with least-privilege service accounts and secret references**
- [ ] **Step 4: Validate configuration without deploying**

---

### Task 10: Emulator End-to-End Recovery and Export Verification

**Files:**
- Create: `services/e2e/package.json`
- Create: `services/e2e/package-lock.json`
- Create: `services/e2e/src/harness.ts`
- Create: `services/e2e/tests/collaboration-flow.test.ts`
- Create: `services/e2e/fixtures/README.md`
- Create: `.github/workflows/collaboration-e2e.yml`
- Modify: `docs/superpowers/plans/2026-07-24-rhwp-firebase-collaboration-v1.md`

**Interfaces:**
- Verifies: upload completion is idempotent and acquires one parse lease
- Verifies: two editors converge, viewer writes are rejected, and repeated tabs share one UID slot
- Verifies: the 11th unique UID is rejected
- Verifies: snapshot corruption falls back to the prior valid snapshot after process restart
- Verifies: export flushes current Yjs state and writes/reparses HWPX
- Verifies: readonly nested objects remain present after export

- [ ] **Step 1: Write a failing process-level E2E scenario**
- [ ] **Step 2: Start Auth, Firestore, and Storage emulators with isolated test data**
- [ ] **Step 3: Exercise upload → parse lease → Yjs edits → snapshot → restart → fallback**
- [ ] **Step 4: Exercise export flush and HWPX reparse assertions**
- [ ] **Step 5: Exercise participant counting and viewer authorization**
- [ ] **Step 6: Run all focused and repository-wide CI gates**
- [ ] **Step 7: Update the Draft PR and implementation status without merging or deploying**
