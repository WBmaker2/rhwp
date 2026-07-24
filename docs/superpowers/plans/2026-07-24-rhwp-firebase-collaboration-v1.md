# rhwp Firebase Collaboration V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version rhwp collaboration system that uploads 100–200MB HWP files, parses each source once on the server, supports up to 10 authenticated Google users editing body and table-cell text with presence and image insertion, and exports the result as HWPX.

**Architecture:** Add a collaboration model and adapter around the existing rhwp document IR rather than treating HWP bytes as live state. Firebase supplies authentication, metadata, ACL, and object storage; Cloud Run hosts a document API and Hocuspocus/Yjs WebSocket server; `rhwp-studio` connects the existing editor to Yjs through a focused adapter.

**Tech Stack:** Rust 2021, existing rhwp Document IR and HWPX serializer, TypeScript 7, Vite 8, Node.js 18+, Yjs, Hocuspocus, Firebase Authentication, Firestore, Cloud Storage, Firebase Admin SDK, Cloud Run, Node test runner, existing rhwp Rust and browser E2E tests.

## Global Constraints

- Base every task on `WBmaker2/rhwp:feat/firebase-collaboration-mvp-v1`, created from upstream `devel` commit `204c56528c537295dcfbfc126d47d82c3cb25334`.
- Support source HWP files from 100MB through 200MB using resumable upload; do not place source bytes in Firestore or Yjs.
- Parse a source document once per source generation and guard parsing with an atomic lease.
- Authenticate every REST and WebSocket request with a verified Firebase ID token and server-side ACL lookup.
- Count unique users, not browser connections, and reject the 11th unique user.
- Make body text, table-cell text, and newly inserted basic images editable; keep complex objects and table structure read-only.
- Store image bytes only in Cloud Storage and synchronize references through Yjs.
- Export HWPX only; HWP export is out of scope.
- Never commit Firebase service-account JSON, access tokens, signed URLs, or production secrets.
- Do not deploy Firebase or Cloud Run resources without explicit user approval.
- Follow TDD: failing test, observed failure, minimum implementation, passing test, commit.

---

## Planned File Map

### Rust collaboration model

- Create `src/collaboration/mod.rs`: public module boundary.
- Create `src/collaboration/model.rs`: serializable collaboration manifest and stable IDs.
- Create `src/collaboration/stable_id.rs`: deterministic ID generation.
- Create `src/collaboration/import.rs`: Document IR to collaboration manifest conversion.
- Create `src/collaboration/apply.rs`: collaboration snapshot changes back into Document IR.
- Create `tests/collaboration_model.rs`: Rust contract tests for IDs, import, read-only flags, and apply behavior.

The root repository is a single Rust crate, so the first version adds a focused module under `src/` instead of creating a workspace crate that would require a broad repository restructuring.

### Collaboration server

- Create `services/collaboration-server/package.json`: isolated service scripts and dependencies.
- Create `services/collaboration-server/tsconfig.json`: strict TypeScript configuration.
- Create `services/collaboration-server/src/auth.ts`: Firebase token and membership verification.
- Create `services/collaboration-server/src/participants.ts`: unique-user connection accounting.
- Create `services/collaboration-server/src/persistence.ts`: Yjs snapshot load/save interface.
- Create `services/collaboration-server/src/server.ts`: Hocuspocus server composition.
- Create `services/collaboration-server/tests/*.test.ts`: auth, limits, persistence, and reconnection tests.

### Document API

- Create `services/document-api/package.json` and `tsconfig.json`.
- Create `services/document-api/src/parse-lease.ts`: atomic parse lease.
- Create `services/document-api/src/storage-paths.ts`: canonical object paths.
- Create `services/document-api/src/routes/complete-upload.ts`: upload completion and parse request.
- Create `services/document-api/src/routes/export-hwpx.ts`: snapshot freeze and export orchestration.
- Create `services/document-api/src/index.ts`: HTTP service composition.
- Create `services/document-api/tests/*.test.ts`: lease, validation, authorization, and idempotency tests.

### rhwp-studio collaboration client

- Create `rhwp-studio/src/collaboration/types.ts`: shared client contracts.
- Create `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`: login and token refresh.
- Create `rhwp-studio/src/collaboration/CollaborationController.ts`: lifecycle and connection state.
- Create `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`: local/remote operation bridge.
- Create `rhwp-studio/src/collaboration/PresenceController.ts`: awareness and cursor conversion.
- Create `rhwp-studio/src/collaboration/AssetUploader.ts`: validated resumable image upload.
- Create `rhwp-studio/tests/collaboration-*.test.ts`: adapter and controller unit tests.
- Create `rhwp-studio/e2e/collaboration-flow.test.mjs`: multi-session browser contract.

### Firebase policy

- Create `firebase/firebase.json`.
- Create `firebase/firestore.rules`.
- Create `firebase/storage.rules`.
- Create `firebase/firestore.indexes.json`.
- Create `firebase/tests/rules.test.mjs`.

---

### Task 1: Deterministic Collaboration Model

**Files:**
- Create: `src/collaboration/mod.rs`
- Create: `src/collaboration/model.rs`
- Create: `src/collaboration/stable_id.rs`
- Modify: `src/lib.rs`
- Test: `tests/collaboration_model.rs`

**Interfaces:**
- Produces: `StableId::for_node(source_fingerprint: &str, kind: NodeKind, path: &[u32]) -> StableId`
- Produces: `CollaborationManifest { schema_version, source_fingerprint, sections, readonly_objects }`
- Produces: `NodeKind::{Section, Paragraph, Table, Row, Cell, Image, ReadonlyObject}`

- [ ] **Step 1: Write the failing stable-ID tests**

```rust
use rhwp::collaboration::{NodeKind, StableId};

#[test]
fn stable_id_is_deterministic_for_same_source_and_path() {
    let first = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);
    let second = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);
    assert_eq!(first, second);
}

#[test]
fn stable_id_changes_when_node_path_changes() {
    let first = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 1]);
    let second = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 2]);
    assert_ne!(first, second);
}
```

- [ ] **Step 2: Run the tests and observe the missing module failure**

Run: `cargo test --test collaboration_model stable_id -- --nocapture`

Expected: FAIL because `rhwp::collaboration` does not exist.

- [ ] **Step 3: Add the module and minimal deterministic ID implementation**

```rust
// src/collaboration/stable_id.rs
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum NodeKind {
    Section,
    Paragraph,
    Table,
    Row,
    Cell,
    Image,
    ReadonlyObject,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct StableId(pub String);

impl StableId {
    pub fn for_node(source_fingerprint: &str, kind: NodeKind, path: &[u32]) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(source_fingerprint.as_bytes());
        hasher.update(format!("::{kind:?}::").as_bytes());
        for part in path {
            hasher.update(&part.to_le_bytes());
        }
        Self(hasher.finalize().to_hex().to_string())
    }
}
```

Expose the module from `src/collaboration/mod.rs` and `src/lib.rs`.

- [ ] **Step 4: Add manifest types with explicit editable/read-only boundaries**

```rust
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CollaborationManifest {
    pub schema_version: u32,
    pub source_fingerprint: String,
    pub sections: Vec<SectionManifest>,
    pub readonly_objects: Vec<ReadonlyObjectManifest>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ParagraphManifest {
    pub id: StableId,
    pub text: String,
    pub style_ref: Option<u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CellManifest {
    pub id: StableId,
    pub text: String,
    pub structure_readonly: bool,
}
```

- [ ] **Step 5: Run focused and full Rust tests**

Run: `cargo test --test collaboration_model -- --nocapture`

Expected: PASS.

Run: `cargo test`

Expected: all existing and new Rust tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib.rs src/collaboration tests/collaboration_model.rs
git commit -m "feat: add deterministic collaboration model"
```

---

### Task 2: Document IR Import and Read-Only Classification

**Files:**
- Create: `src/collaboration/import.rs`
- Modify: `src/collaboration/mod.rs`
- Modify: `src/collaboration/model.rs`
- Test: `tests/collaboration_model.rs`

**Interfaces:**
- Consumes: `StableId`, `CollaborationManifest`, existing rhwp Document IR.
- Produces: `build_collaboration_manifest(document: &Document, source_fingerprint: &str) -> Result<CollaborationManifest, CollaborationError>`
- Produces: `EditableBlock::{Paragraph, TableCell, InsertedImage}` and `ReadonlyObjectKind`.

- [ ] **Step 1: Add a failing import contract test using the smallest existing document fixture**

```rust
#[test]
fn import_marks_paragraph_and_cell_text_editable_but_table_structure_readonly() {
    let document = load_fixture_document("tests/fixtures/formatting_table.hwpx");
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();

    assert!(manifest.sections.iter().any(|section| !section.paragraphs.is_empty()));
    assert!(manifest.sections.iter().flat_map(|s| &s.tables)
        .flat_map(|t| &t.cells)
        .all(|cell| cell.structure_readonly));
}
```

Use an already tracked small table fixture. Do not add a large binary fixture.

- [ ] **Step 2: Run the focused test**

Run: `cargo test --test collaboration_model import_marks -- --nocapture`

Expected: FAIL because `build_collaboration_manifest` is undefined.

- [ ] **Step 3: Implement a visitor that maps supported nodes and records unsupported controls**

The visitor must:

```rust
match node {
    DocumentNode::Paragraph(paragraph) => import_paragraph(paragraph, path),
    DocumentNode::Table(table) => import_table_with_readonly_structure(table, path),
    DocumentNode::Image(image) => import_existing_image_as_readonly_asset(image, path),
    other => record_readonly_object(other, path),
}
```

Use the actual Document IR enum and fields found in the repository; preserve this behavior even where the concrete names differ.

- [ ] **Step 4: Add tests for deterministic re-import and unsupported-object preservation**

```rust
assert_eq!(
    build_collaboration_manifest(&document, fingerprint).unwrap(),
    build_collaboration_manifest(&document, fingerprint).unwrap()
);
assert!(!manifest.readonly_objects.is_empty());
```

- [ ] **Step 5: Run Rust tests**

Run: `cargo test --test collaboration_model -- --nocapture`

Expected: PASS.

Run: `cargo test`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/collaboration tests/collaboration_model.rs
git commit -m "feat: import document IR into collaboration manifest"
```

---

### Task 3: Apply Collaborative Text and Image Changes Back to Document IR

**Files:**
- Create: `src/collaboration/apply.rs`
- Modify: `src/collaboration/mod.rs`
- Modify: `src/collaboration/model.rs`
- Test: `tests/collaboration_model.rs`

**Interfaces:**
- Consumes: stable IDs from Task 1 and manifest mapping from Task 2.
- Produces: `CollaborationPatch { paragraphs, cells, inserted_images }`
- Produces: `apply_collaboration_patch(document: &mut Document, manifest: &CollaborationManifest, patch: &CollaborationPatch) -> Result<ApplyReport, CollaborationError>`

- [ ] **Step 1: Write failing tests for paragraph, cell, image, and read-only rejection**

```rust
#[test]
fn apply_updates_only_supported_targets() {
    let mut document = load_fixture_document("tests/fixtures/formatting_table.hwpx");
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();
    let patch = CollaborationPatch::from_test_values(
        manifest.first_paragraph_id(), "공동 편집 본문",
        manifest.first_cell_id(), "공동 편집 셀"
    );

    let report = apply_collaboration_patch(&mut document, &manifest, &patch).unwrap();
    assert_eq!(report.updated_paragraphs, 1);
    assert_eq!(report.updated_cells, 1);
}

#[test]
fn apply_rejects_unknown_or_readonly_object_ids() {
    // Assert CollaborationError::ReadonlyTarget or UnknownTarget.
}
```

- [ ] **Step 2: Run focused tests**

Run: `cargo test --test collaboration_model apply_ -- --nocapture`

Expected: FAIL because patch and apply APIs do not exist.

- [ ] **Step 3: Implement minimum patch application with a stable-ID lookup table**

Build the lookup during import or reconstruct it deterministically. Never search by mutable paragraph index alone.

```rust
pub struct ApplyReport {
    pub updated_paragraphs: usize,
    pub updated_cells: usize,
    pub inserted_images: usize,
}
```

Reject attempts to mutate table structure or `readonlyObjectId` targets.

- [ ] **Step 4: Add HWPX round-trip test**

Serialize the patched document using the existing HWPX writer, parse the output again, and assert that edited paragraph and cell text survive.

- [ ] **Step 5: Run tests**

Run: `cargo test --test collaboration_model -- --nocapture`

Expected: PASS.

Run: `cargo test`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/collaboration tests/collaboration_model.rs
git commit -m "feat: apply collaboration patches to document IR"
```

---

### Task 4: Authenticated Hocuspocus Server and 10-User Limit

**Files:**
- Create: `services/collaboration-server/package.json`
- Create: `services/collaboration-server/tsconfig.json`
- Create: `services/collaboration-server/src/auth.ts`
- Create: `services/collaboration-server/src/participants.ts`
- Create: `services/collaboration-server/src/server.ts`
- Create: `services/collaboration-server/tests/auth.test.ts`
- Create: `services/collaboration-server/tests/participants.test.ts`

**Interfaces:**
- Produces: `verifyConnection(input: ConnectionAuthInput): Promise<AuthorizedConnection>`
- Produces: `ParticipantRegistry.tryJoin(documentId: string, userId: string, connectionId: string): JoinResult`
- Produces: `ParticipantRegistry.leave(documentId: string, userId: string, connectionId: string): void`

- [ ] **Step 1: Create package scripts and strict compiler settings**

```json
{
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "node --test --import tsx tests/*.test.ts"
  },
  "dependencies": {
    "@hocuspocus/server": "^3.0.0",
    "firebase-admin": "^13.0.0",
    "yjs": "^13.6.0"
  },
  "devDependencies": {
    "tsx": "^4.0.0",
    "typescript": "^7.0.2"
  }
}
```

Resolve exact compatible versions during lockfile installation; do not downgrade the repository TypeScript floor.

- [ ] **Step 2: Write failing unique-user tests**

```ts
assert.equal(registry.tryJoin('doc-1', 'user-1', 'tab-a').accepted, true)
assert.equal(registry.tryJoin('doc-1', 'user-1', 'tab-b').uniqueUsers, 1)
for (let index = 2; index <= 10; index++) {
  assert.equal(registry.tryJoin('doc-1', `user-${index}`, `tab-${index}`).accepted, true)
}
assert.deepEqual(registry.tryJoin('doc-1', 'user-11', 'tab-11'), {
  accepted: false,
  reason: 'participant-limit',
  uniqueUsers: 10,
})
```

- [ ] **Step 3: Run tests and observe failure**

Run: `cd services/collaboration-server && npm test`

Expected: FAIL because implementation modules do not exist.

- [ ] **Step 4: Implement the participant registry and token/ACL verifier**

```ts
export interface AuthorizedConnection {
  documentId: string
  userId: string
  role: 'owner' | 'editor' | 'viewer'
  displayName: string
  photoURL: string | null
}
```

`verifyConnection` must verify the Firebase token, load `documents/{documentId}/members/{uid}`, and reject missing membership. Keep Firebase Admin and Firestore behind injected interfaces so tests do not call production services.

- [ ] **Step 5: Compose Hocuspocus hooks**

- `onAuthenticate`: verify token and ACL, then call `tryJoin`.
- `onDisconnect`: call `leave`.
- `beforeHandleMessage`: reject document updates from `viewer` while allowing awareness traffic.

- [ ] **Step 6: Run tests and build**

Run: `cd services/collaboration-server && npm test && npm run build`

Expected: PASS and zero TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add services/collaboration-server package-lock.json
git commit -m "feat: add authenticated collaboration server"
```

---

### Task 5: Snapshot Persistence and Server Recovery

**Files:**
- Create: `services/collaboration-server/src/persistence.ts`
- Modify: `services/collaboration-server/src/server.ts`
- Create: `services/collaboration-server/tests/persistence.test.ts`

**Interfaces:**
- Produces: `SnapshotStore.load(documentId: string): Promise<Uint8Array | null>`
- Produces: `SnapshotStore.save(documentId: string, update: Uint8Array, reason: SnapshotReason): Promise<SnapshotRecord>`
- Produces: `SnapshotReason = 'debounce' | 'size-threshold' | 'last-user' | 'export' | 'shutdown'`

- [ ] **Step 1: Write failing load/save/fallback tests with an in-memory object store**

```ts
const store = new SnapshotStore(fakeObjects, fakeDocuments)
await store.save('doc-1', updateA, 'debounce')
assert.deepEqual(await store.load('doc-1'), updateA)

fakeObjects.corruptLatest()
assert.deepEqual(await store.load('doc-1'), updateBeforeA)
```

- [ ] **Step 2: Run tests**

Run: `cd services/collaboration-server && npm test -- tests/persistence.test.ts`

Expected: FAIL because `SnapshotStore` is undefined.

- [ ] **Step 3: Implement canonical paths and checksum validation**

Use:

```text
documents/{documentId}/collaboration/snapshots/{timestamp}-{checksum}.bin
```

Write the object first, then atomically update `latestSnapshotPath` in Firestore. Verify checksum on load and fall back to the prior recorded snapshot when validation fails.

- [ ] **Step 4: Wire persistence hooks**

Load on document creation, debounce writes after changes, force save when the last unique user leaves, and expose `flushForExport(documentId)`.

- [ ] **Step 5: Run tests and build**

Run: `cd services/collaboration-server && npm test && npm run build`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/collaboration-server
git commit -m "feat: persist and recover Yjs snapshots"
```

---

### Task 6: Upload Completion, Parse Lease, and Export API

**Files:**
- Create: `services/document-api/package.json`
- Create: `services/document-api/tsconfig.json`
- Create: `services/document-api/src/storage-paths.ts`
- Create: `services/document-api/src/parse-lease.ts`
- Create: `services/document-api/src/routes/complete-upload.ts`
- Create: `services/document-api/src/routes/export-hwpx.ts`
- Create: `services/document-api/src/index.ts`
- Create: `services/document-api/tests/parse-lease.test.ts`
- Create: `services/document-api/tests/routes.test.ts`

**Interfaces:**
- Produces: `acquireParseLease(documentId: string, sourceGeneration: string, now: Date): Promise<LeaseResult>`
- Produces: `POST /v1/documents/:documentId/complete-upload`
- Produces: `POST /v1/documents/:documentId/exports`
- Consumes: collaboration server `flushForExport` endpoint or internal authenticated service call.

- [ ] **Step 1: Write failing idempotency and authorization tests**

```ts
const first = await lease.acquire('doc-1', 'generation-7', now)
const second = await lease.acquire('doc-1', 'generation-7', now)
assert.equal(first.acquired, true)
assert.equal(second.acquired, false)
assert.equal(second.reason, 'already-processing')
```

Route tests must assert:

- missing Firebase token returns 401;
- non-member returns 403;
- source outside 100–200MB returns 422 for the large-file V1 route;
- wrong content header returns 415;
- duplicate completion does not start a second parse;
- viewer cannot request export.

- [ ] **Step 2: Run tests**

Run: `cd services/document-api && npm test`

Expected: FAIL because service modules do not exist.

- [ ] **Step 3: Implement canonical paths and parse lease**

```ts
export const sourcePath = (documentId: string) =>
  `documents/${assertId(documentId)}/source/original.hwp`

export const exportPath = (documentId: string, exportId: string) =>
  `documents/${assertId(documentId)}/exports/${assertId(exportId)}.hwpx`
```

The Firestore transaction must compare `sourceGeneration`, status, lease owner, and lease expiry before setting `status: 'parsing'`.

- [ ] **Step 4: Implement upload completion orchestration**

Validate Storage object metadata and actual HWP signature, acquire the lease, invoke the native rhwp parser once, write derived manifest/sections/assets, initialize the Yjs snapshot, then set `status: 'ready'`. On failure set a sanitized error code while preserving the source.

- [ ] **Step 5: Implement export orchestration**

Authorize owner/editor, request a collaboration flush, load source IR and latest snapshot, call the Rust collaboration apply API and HWPX serializer, reparse the generated HWPX for validation, upload it, then update the export record.

- [ ] **Step 6: Run tests and build**

Run: `cd services/document-api && npm test && npm run build`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/document-api
git commit -m "feat: add document parse and HWPX export API"
```

---

### Task 7: rhwp-studio Yjs Adapter, Presence, and Image Upload

**Files:**
- Modify: `rhwp-studio/package.json`
- Create: `rhwp-studio/src/collaboration/types.ts`
- Create: `rhwp-studio/src/collaboration/FirebaseAuthProvider.ts`
- Create: `rhwp-studio/src/collaboration/CollaborationController.ts`
- Create: `rhwp-studio/src/collaboration/RhwpYjsAdapter.ts`
- Create: `rhwp-studio/src/collaboration/PresenceController.ts`
- Create: `rhwp-studio/src/collaboration/AssetUploader.ts`
- Create: `rhwp-studio/tests/collaboration-adapter.test.ts`
- Create: `rhwp-studio/tests/collaboration-controller.test.ts`

**Interfaces:**
- Produces: `CollaborationController.connect(options: CollaborationOptions): Promise<void>`
- Produces: `RhwpYjsAdapter.bindParagraph(paragraphId: string, text: Y.Text): Unsubscribe`
- Produces: `RhwpYjsAdapter.bindCell(cellId: string, text: Y.Text): Unsubscribe`
- Produces: `AssetUploader.uploadImage(input: ImageUploadInput): Promise<InsertedImageRef>`
- Consumes: existing editor command dispatch and selection APIs.

- [ ] **Step 1: Add exact dependencies and a collaboration test script**

Add `firebase`, `yjs`, and `@hocuspocus/provider` to `rhwp-studio/package.json`. Extend the existing Node test glob only if needed; do not replace current test scripts.

- [ ] **Step 2: Write failing adapter tests with a fake editor port**

```ts
const editor = new FakeEditorPort({ paragraph: '가나다' })
const text = new Y.Text('가나다')
const adapter = new RhwpYjsAdapter(editor)
adapter.bindParagraph('paragraph-1', text)

editor.emitLocalTextChange({ id: 'paragraph-1', from: 1, to: 2, insert: '나나' })
assert.equal(text.toString(), '가나나다')

text.doc!.transact(() => text.insert(0, '원격 '), REMOTE_ORIGIN)
assert.equal(editor.paragraphText('paragraph-1'), '원격 가나나다')
assert.equal(editor.localChangeCount, 1)
```

This verifies local-to-Yjs, remote-to-editor, and loop prevention.

- [ ] **Step 3: Run tests and observe failure**

Run: `cd rhwp-studio && npm test`

Expected: FAIL because collaboration modules do not exist.

- [ ] **Step 4: Define a narrow editor port before touching existing editor internals**

```ts
export interface CollaborationEditorPort {
  onTextChange(listener: (change: LocalTextChange) => void): () => void
  applyRemoteTextChange(change: RemoteTextChange): void
  onSelectionChange(listener: (selection: StableSelection) => void): () => void
  renderRemoteSelection(selection: RemoteSelection): void
  insertRemoteImage(image: InsertedImageRef): void
  setReadonlyTarget(targetId: string, readonly: boolean): void
}
```

Create the smallest adapter from current rhwp-studio APIs to this port. Do not scatter Yjs calls through existing UI modules.

- [ ] **Step 5: Implement adapter and per-user undo**

Use explicit origins:

```ts
export const LOCAL_ORIGIN = Symbol('rhwp-local')
export const REMOTE_ORIGIN = Symbol('rhwp-remote')
```

Use `Y.UndoManager` scoped to local origins. Do not add remote transactions to the current user’s undo stack.

- [ ] **Step 6: Implement presence conversion with stable IDs**

Awareness payload:

```ts
export interface PresenceState {
  userId: string
  displayName: string
  photoURL: string | null
  colorIndex: number
  activeTargetId: string | null
  anchorOffset: number
  headOffset: number
  lastActiveAt: number
}
```

Map editor selections to `activeTargetId + offsets`, never DOM node indices.

- [ ] **Step 7: Implement validated resumable image upload**

Accept PNG/JPEG/WebP up to 20MB, upload to `documents/{documentId}/assets/user/{imageId}/{filename}`, and create the Yjs image reference only after upload success. Reject executable or mismatched MIME/header combinations.

- [ ] **Step 8: Run tests, type-check, and build**

Run: `cd rhwp-studio && npm test && npm run build`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add rhwp-studio package-lock.json
git commit -m "feat: connect rhwp studio to Yjs collaboration"
```

---

### Task 8: Firebase Rules, Multi-Session E2E, and Regression Gate

**Files:**
- Create: `firebase/firebase.json`
- Create: `firebase/firestore.rules`
- Create: `firebase/storage.rules`
- Create: `firebase/firestore.indexes.json`
- Create: `firebase/tests/rules.test.mjs`
- Create: `rhwp-studio/e2e/collaboration-flow.test.mjs`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md` only to document local development and non-deployment status.

**Interfaces:**
- Consumes all previous tasks.
- Produces an end-to-end verified V1 path and CI regression gate.

- [ ] **Step 1: Write failing Firestore and Storage emulator tests**

Tests must prove:

```text
owner: read/write metadata, members, exports
editor: read document, write collaboration-related records, request export
viewer: read only
non-member: no document access
client: cannot write ownerId, status, parserVersion, latestSnapshotPath
client: cannot upload outside its authorized document path
client: cannot upload unsupported image type or source larger than 200MB
```

- [ ] **Step 2: Run emulator tests**

Run: `firebase emulators:exec --only firestore,storage "node --test firebase/tests/rules.test.mjs"`

Expected: FAIL until rules exist.

- [ ] **Step 3: Implement least-privilege rules**

Rules must use authenticated UID and document membership. Server-maintained fields are immutable from clients. Original HWP uploads are allowed only to the canonical source path and must enforce declared size/content type; server still repeats validation because Storage metadata is not sufficient proof of file format.

- [ ] **Step 4: Write the multi-session E2E test**

The test starts local emulators and service processes, launches three isolated browser contexts, and verifies:

1. each test user authenticates;
2. a source HWP uploads through the resumable path;
3. parse status becomes `ready`;
4. three users edit different paragraphs and converge;
5. two users edit the same table cell and converge;
6. one user inserts an image and all clients display it;
7. awareness shows three users and stable-ID cursors;
8. one client disconnects and reconnects without data loss;
9. an export is produced;
10. the generated HWPX is reparsed and contains edited body, cell, and image references;
11. a viewer write is rejected;
12. the 11th unique user receives `participant-limit`.

- [ ] **Step 5: Run E2E locally**

Run: `cd rhwp-studio && node e2e/collaboration-flow.test.mjs --mode=headless`

Expected: PASS with explicit assertions for every stage.

- [ ] **Step 6: Add CI jobs without production deployment**

Add jobs for:

```text
cargo test --test collaboration_model
collaboration-server npm test + build
document-api npm test + build
rhwp-studio npm test + build
Firebase emulator rules test
headless collaboration E2E using generated small fixture
```

Keep the 100–200MB stress profile out of standard CI; expose it as a manual workflow or documented command.

- [ ] **Step 7: Run the complete regression gate**

Run:

```bash
cargo test
(cd services/collaboration-server && npm test && npm run build)
(cd services/document-api && npm test && npm run build)
(cd rhwp-studio && npm test && npm run build)
firebase emulators:exec --only firestore,storage "node --test firebase/tests/rules.test.mjs"
(cd rhwp-studio && node e2e/collaboration-flow.test.mjs --mode=headless)
```

Expected: every command exits 0.

- [ ] **Step 8: Run the manual large-file profile**

Generate or use a non-sensitive 100MB, 150MB, and 200MB HWP fixture outside Git, upload each through the resumable path, and record:

```text
upload resumed after forced disconnect
single parse lease acquired
browser peak memory
server peak memory
parse duration
export success
reparsed HWPX success
```

Do not claim 100–200MB support until this profile passes.

- [ ] **Step 9: Commit**

```bash
git add firebase rhwp-studio/e2e/collaboration-flow.test.mjs .github/workflows/ci.yml README.md
git commit -m "test: add collaboration security and end-to-end gates"
```

---

## Self-Review Results

### Spec coverage

- Large resumable upload and single server parse: Task 6 and Task 8.
- Google authentication and ACL: Task 4, Task 6, Task 7, Task 8.
- Maximum 10 unique users: Task 4 and Task 8.
- Body and table-cell collaboration: Task 1–3 and Task 7–8.
- Image insertion: Task 3, Task 7, Task 8.
- Presence and cursors: Task 7 and Task 8.
- HWPX export and reparse verification: Task 3, Task 6, Task 8.
- Complex-object read-only preservation: Task 2, Task 3, Task 7, Task 8.
- Snapshot persistence and restart recovery: Task 5 and Task 8.
- Security rules and secret hygiene: Task 4, Task 6, Task 8.
- Existing rhwp regression protection: every Rust task plus Task 8 full gate.

### Placeholder scan

The plan contains no TBD/TODO steps. Where existing Document IR concrete enum names must be discovered, the behavioral mapping and required test contract are explicit; implementation must bind those contracts to the repository’s actual types before code is committed.

### Type consistency

Stable IDs flow from Task 1 into import, apply, editor selection, presence, and export. `CollaborationManifest`, `CollaborationPatch`, `AuthorizedConnection`, `ParticipantRegistry`, `SnapshotStore`, and the editor port each have one defined responsibility and consistent names throughout the plan.
