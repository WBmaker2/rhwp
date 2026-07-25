# rhwp Firebase Collaboration MVP v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Firebase- and Cloud Run-backed collaboration path to `rhwp` that imports one HWP document into a stable-ID collaboration model, supports bounded collaborative edits for at most 10 unique users, persists recoverable Yjs snapshots, and exports HWPX without silently dropping unsupported objects.

**Architecture:** Keep `rhwp`'s existing Rust `Document` IR as the import/export authority. Add a collaboration adapter layer in Rust for stable IDs, import, patch application, and HWPX reconstruction. Add a Node.js Hocuspocus service for Yjs transport and Firebase-backed auth/persistence. Add a document API service for upload completion, parse lease, and export orchestration.

**Tech Stack:** Rust, `blake3`, Node.js 22+, TypeScript, Hocuspocus, Yjs, Firebase Auth/Admin SDK, Firestore, Cloud Storage, Cloud Run, GitHub Actions.

---

## Implementation Status

- [x] Task 1: Stable Collaboration IDs and Schema Version
- [x] Task 2: Import HWP IR Into the Collaboration Model
- [x] Task 3: Apply Collaboration Patches Back to the Document IR
  - [x] Body paragraph text
  - [x] Table-cell text
  - [x] Basic resolved image insertion
  - [x] HWPX serialize/reparse roundtrip regression test
- [x] Task 4: Authenticated 10-User Collaboration Server
- [x] Task 5: Snapshot Persistence and Server Recovery
- [x] Task 6: Upload Completion, Parse Lease, and Export API
- [x] Task 7: Firestore and Storage Security Rules
- [ ] Task 8: Presence and Remote Cursor UI
- [ ] Task 9: Firebase Hosting, Cloud Run, and Emulator Deployment
- [ ] Task 10: End-to-End Recovery and Export Verification

The completed Task 5 layer uses injected object-storage and metadata-store interfaces. Concrete production Firebase Storage/Firestore wiring remains part of the deployment/API integration work and is not deployed by this plan update.

---

### Task 1: Stable Collaboration IDs and Schema Version

**Files:**
- Create: `src/collaboration/mod.rs`
- Create: `src/collaboration/stable_id.rs`
- Create: `src/collaboration/model.rs`
- Modify: `src/lib.rs`
- Create: `tests/collaboration_model.rs`

**Interfaces:**
- Produces: `StableId::for_node(source_fingerprint, node_kind, structural_path)`
- Produces: `COLLABORATION_SCHEMA_VERSION`
- Produces: serializable collaboration manifest types

- [x] **Step 1: Write failing deterministic-ID tests**
- [x] **Step 2: Run the focused test and observe failure**
- [x] **Step 3: Implement stable ID generation**
- [x] **Step 4: Define the manifest root and schema version**
- [x] **Step 5: Run focused tests**
- [x] **Step 6: Commit**

---

### Task 2: Import HWP IR Into the Collaboration Model

**Files:**
- Create: `src/collaboration/import.rs`
- Modify: `src/collaboration/mod.rs`
- Modify: `tests/collaboration_model.rs`

**Interfaces:**
- Produces: `build_collaboration_manifest(document, source_fingerprint)`
- Consumes: `Document`, sections, paragraphs, controls, tables, cells

- [x] **Step 1: Write failing import tests**
- [x] **Step 2: Run the focused test and observe failure**
- [x] **Step 3: Implement deterministic import traversal**
- [x] **Step 4: Run focused tests**
- [x] **Step 5: Commit**
- [x] **Step 6: Add nested table-cell readonly classification and HWPX roundtrip preservation regression**

---

### Task 3: Apply Collaboration Patches Back to the Document IR

**Files:**
- Create: `src/collaboration/apply.rs`
- Modify: `src/collaboration/mod.rs`
- Modify: `tests/collaboration_model.rs`

**Interfaces:**
- Produces: `apply_collaboration_patch(document, manifest, patch)`
- Consumes: stable paragraph IDs, cell IDs, inserted-image metadata and resolved bytes

- [x] **Step 1: Write failing patch-application tests**
- [x] **Step 2: Run focused tests and observe failure**
- [x] **Step 3: Implement body-text and cell-text patch application**
- [x] **Step 4: Reject readonly and unknown targets**
- [x] **Step 5: Add failing basic-image insertion test**
- [x] **Step 6: Implement validated image insertion and BinData registration**
- [x] **Step 7: Add HWPX serialize/reparse roundtrip test**
- [x] **Step 8: Run full Rust CI**

---

### Task 4: Authenticated 10-User Collaboration Server

**Files:**
- Create: `services/collaboration-server/package.json`
- Create: `services/collaboration-server/tsconfig.json`
- Create: `services/collaboration-server/src/participants.ts`
- Create: `services/collaboration-server/src/auth.ts`
- Create: `services/collaboration-server/src/server.ts`
- Create: `services/collaboration-server/tests/participants.test.ts`
- Create: `services/collaboration-server/tests/auth.test.ts`
- Create: `services/collaboration-server/tests/server.test.ts`

- [x] **Step 1: Create the service package**
- [x] **Step 2: Write failing unique-user tests**
- [x] **Step 3: Run tests and observe failure**
- [x] **Step 4: Implement the participant registry and token/ACL verifier**
- [x] **Step 5: Compose Hocuspocus hooks**
- [x] **Step 6: Run tests and build**
- [x] **Step 7: Commit**

---

### Task 5: Snapshot Persistence and Server Recovery

**Files:**
- Create: `services/collaboration-server/src/persistence.ts`
- Modify: `services/collaboration-server/src/server.ts`
- Create: `services/collaboration-server/tests/persistence.test.ts`
- Create: `services/collaboration-server/tests/persistence-hooks.test.ts`

**Interfaces:**
- Produces: `SnapshotStore.load(documentId: string): Promise<Uint8Array | null>`
- Produces: `SnapshotStore.save(documentId: string, update: Uint8Array, reason: SnapshotReason): Promise<SnapshotRecord>`
- Produces: `YjsSnapshotPersistence`
- Produces: `SnapshotReason = 'debounce' | 'size-threshold' | 'last-user' | 'export' | 'shutdown'`

- [x] **Step 1: Write failing load/save/fallback tests with an in-memory object store**
- [x] **Step 2: Run tests and observe failure**
- [x] **Step 3: Implement canonical paths and checksum validation**
- [x] **Step 4: Retain the 10 newest snapshots and remove expired objects after metadata publication**
- [x] **Step 5: Wire document load and debounced store hooks**
- [x] **Step 6: Force-save after the last unique user, before export, and during shutdown**
- [x] **Step 7: Run tests and TypeScript build**

Canonical snapshot path:

```text
documents/{documentId}/collaboration/snapshots/{timestamp}-{checksum}.bin
```

The object is written before the metadata pointer is published. Loads verify SHA-256 and fall back through previously recorded snapshots when the latest object is absent or corrupt.

---

### Task 6: Upload Completion, Parse Lease, and Export API

**Files:**
- Create: `services/document-api/package.json`
- Create: `services/document-api/tsconfig.json`
- Create: `services/document-api/src/storage-paths.ts`
- Create: `services/document-api/src/parse-lease.ts`
- Create: `services/document-api/src/routes/complete-upload.ts`
- Create: `services/document-api/src/routes/export-hwpx.ts`

**Interfaces:**
- Produces: upload-completion route
- Produces: Firestore parse lease
- Produces: HWPX export orchestration
- Consumes: collaboration `flushForExport(documentId)` and Rust document conversion path

- [x] **Step 1: Define failing storage-path and lease tests**
- [x] **Step 2: Implement canonical source/asset/export paths**
- [x] **Step 3: Implement single-owner parse lease acquisition and expiry**
- [x] **Step 4: Implement upload-completion orchestration**
- [x] **Step 5: Implement export orchestration with mandatory collaboration flush**
- [x] **Step 6: Run tests and build**

The Task 6 layer uses injected token verification, membership, object metadata, atomic lease storage, parse job, collaboration flush, and export job interfaces. Concrete Firebase adapters, a Cloud Run HTTP listener, and deployment configuration remain in Tasks 7–9 and are not deployed by this change.

---

### Task 7: Firestore and Storage Security Rules

**Files:**
- Create: `firebase/firebase.json`
- Create: `firebase/firestore.rules`
- Create: `firebase/storage.rules`
- Create: `firebase/firestore.indexes.json`
- Create: `firebase/tests/rules.test.mjs`
- Create: `.github/workflows/firebase-rules.yml`

- [x] Define failing Firestore and Storage authorization contracts.
- [x] Restrict document reads to members and client metadata updates to owner-controlled title fields.
- [x] Restrict membership and share-link management to the document owner.
- [x] Deny client writes to parse, snapshot, derived, and export state.
- [x] Validate owner-only 100–200 MiB HWP source uploads.
- [x] Validate owner/editor user images by role, size, type, uploader metadata, and create-only semantics.
- [x] Run Firestore and Storage Emulator tests with locked dependencies.

The rules suite uses the demo project and Local Emulator Suite only. No Firebase project or production rules were deployed.

---

### Task 8: Presence and Remote Cursor UI

- [ ] Add awareness payloads containing `uid`, display name, photo URL, stable target ID, and relative cursor position.
- [ ] Render online users and remote cursors without persisting awareness state.

---

### Task 9: Firebase Hosting, Cloud Run, and Emulator Deployment

- [ ] Add Firebase and Cloud Run configuration.
- [ ] Verify local emulator flow.
- [ ] Do not deploy without explicit approval.

---

### Task 10: End-to-End Recovery and Export Verification

- [ ] Verify upload → parse → collaborate → snapshot → restart → recover → export HWPX.
- [ ] Verify unsupported objects remain present after export.
- [ ] Verify the 11th unique user is rejected while multiple tabs for one UID count once.
