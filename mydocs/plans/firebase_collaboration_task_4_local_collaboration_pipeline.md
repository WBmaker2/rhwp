# Firebase Collaboration Task 4 Implementation Plan

> **Execution rule:** TDD로 각 하위 작업을 RED → GREEN → REFACTOR 순서로 구현한다. 커밋·푸시·배포는 별도 요청 없이는 수행하지 않는다.

**Goal:** Firebase와 Yjs를 붙이기 전에, 현재 문서에서 협업 컨텍스트를 만들고 검증된 문단·표 셀 텍스트 update를 Rust/WASM 문서에 적용한 뒤 BroadcastChannel로 다른 탭에 전달할 수 있는 로컬 협업 파이프라인을 완성한다.

**Architecture:** Rust는 위치와 StableId를 함께 검증한 뒤 문서를 변경하는 최종 무결성 경계다. TypeScript는 manifest parser와 node registry를 이용해 update를 검증하고 올바른 WASM 메서드로 라우팅한다. Transport는 브라우저 메시지 전달만 담당하며 문서 변경 로직을 알지 않는다.

## Scope

- Task 4-1: `CollaborationContext`
- Task 4-2: update 계약과 validator
- Task 4-3: Rust paragraph apply API
- Task 4-4: Rust cell apply API
- Task 4-5: WASM wrapper와 TypeScript 선언
- Task 4-6: TypeScript `CollaborationDocumentAdapter`
- Task 4-7: `BroadcastChannelCollaborationTransport`

## Non-goals

- Firebase Authentication, Firestore, Storage
- Yjs/CRDT
- 공유 링크와 권한 UI
- 로컬 편집 이벤트 수집
- 원격 커서와 presence
- 다중 문단 표 셀의 구조 재작성

---

## Task 4-1: CollaborationContext

**Files**

- Create: `rhwp-studio/src/collaboration/collaboration-context.ts`
- Test: `rhwp-studio/tests/collaboration-context.test.ts`

**Contract**

```ts
createCollaborationContext(document, sourceFingerprint)
```

- `document.getCollaborationManifest()`를 호출한다.
- manifest를 parser로 검증한다.
- `CollaborationNodeRegistry`를 생성한다.
- manifest, registry, fingerprint를 불변 컨텍스트로 반환한다.

---

## Task 4-2: Update Contract and Validator

**Files**

- Create: `rhwp-studio/src/collaboration/update.ts`
- Test: `rhwp-studio/tests/collaboration-update.test.ts`

**MVP update contract**

```ts
interface CollaborationTextUpdate {
  version: 1;
  updateId: string;
  documentFingerprint: string;
  nodeId: string;
  nodeKind: 'paragraph' | 'cell';
  text: string;
  clientId: string;
  sequence: number;
}
```

**Validation**

- version은 1만 허용한다.
- updateId, nodeId, clientId는 빈 문자열을 거부한다.
- fingerprint는 context와 일치해야 한다.
- nodeId는 registry에 존재해야 한다.
- nodeKind는 registry location kind와 일치해야 한다.
- sequence는 0 이상의 안전한 정수여야 한다.
- text는 문자열이며 UTF-8 기준 최대 1 MiB로 제한한다.

---

## Task 4-3: Rust Paragraph Apply API

**Files**

- Create: `src/collaboration/apply.rs`
- Modify: `src/collaboration/error.rs`
- Modify: `src/collaboration/mod.rs`
- Test: `tests/collaboration_apply.rs`

**API**

```rust
apply_collaboration_paragraph_text(
    document,
    source_fingerprint,
    section_index,
    paragraph_index,
    stable_id,
    text,
) -> Result<CollaborationApplyReport, CollaborationError>
```

**Safety rules**

- fingerprint 형식을 검증한다.
- section/paragraph 범위를 검증한다.
- 전달 위치로 StableId를 재계산해 입력 StableId와 일치해야 한다.
- 일치한 경우에만 문단 text를 교체한다.
- char_count와 char_offsets를 새 텍스트 기준으로 갱신하고 캐시성 line segment를 비운다.

---

## Task 4-4: Rust Cell Apply API

**API**

```rust
apply_collaboration_cell_text(
    document,
    source_fingerprint,
    section_index,
    host_paragraph_index,
    control_index,
    cell_index,
    stable_id,
    text,
) -> Result<CollaborationApplyReport, CollaborationError>
```

**Safety rules**

- 대상 control은 반드시 table이어야 한다.
- 위치 기반 StableId를 재계산해 검증한다.
- MVP에서는 문단이 정확히 1개인 셀만 수정한다.
- 빈 paragraph list 또는 다중 paragraph 셀은 `UnsupportedCellParagraphStructure`로 거부한다.
- table/cell dirty flag를 설정한다.

---

## Task 4-5: WASM Wrapper

**Files**

- Modify: `src/wasm_api.rs`
- Modify: `src/wasm_api/tests.rs`
- Modify: `typescript/rhwp.d.ts`

**Methods**

```ts
applyCollaborationParagraphText(...): string
applyCollaborationCellText(...): string
```

반환 JSON은 다음 보고서를 직렬화한다.

```json
{
  "updated": true,
  "kind": "paragraph",
  "node_id": "..."
}
```

문서 변경 후 pagination/render cache가 오래된 상태로 남지 않도록 기존 `DocumentCore`의 invalidation 경로를 재사용하거나 최소한 재페이지네이션을 실행한다.

---

## Task 4-6: CollaborationDocumentAdapter

**Files**

- Create: `rhwp-studio/src/collaboration/document-adapter.ts`
- Test: `rhwp-studio/tests/collaboration-document-adapter.test.ts`

**Responsibilities**

- update validator 호출
- registry에서 location 조회
- paragraph/cell별 WASM API 라우팅
- 중복 updateId 무시
- 원격 적용 중 재발행 방지를 위한 `isApplyingRemoteUpdate` 상태 제공
- WASM 반환 JSON 검증

---

## Task 4-7: BroadcastChannel Transport

**Files**

- Create: `rhwp-studio/src/collaboration/transport.ts`
- Create: `rhwp-studio/src/collaboration/broadcast-channel-transport.ts`
- Test: `rhwp-studio/tests/collaboration-transport.test.ts`

**Contract**

```ts
interface CollaborationTransport {
  connect(sessionId: string): void;
  send(update: CollaborationTextUpdate): void;
  subscribe(handler): () => void;
  disconnect(): void;
}
```

**Rules**

- channel name은 `rhwp-collaboration:<sessionId>` 형식이다.
- 자기 clientId의 메시지는 무시한다.
- 같은 updateId는 한 번만 전달한다.
- subscriber 오류는 다른 subscriber와 transport를 중단시키지 않는다.
- disconnect 시 channel을 닫고 상태를 초기화한다.
- 테스트에서는 실제 브라우저 대신 주입 가능한 `BroadcastChannelLike` factory를 사용한다.

---

## Verification

### Rust

```bash
cargo test --test collaboration_apply -- --nocapture
cargo test --test collaboration_model -- --nocapture
cargo test wasm_api::tests::collaboration_apply -- --nocapture
cargo check
cargo fmt --check
```

### TypeScript

```bash
node --test \
  rhwp-studio/tests/collaboration-context.test.ts \
  rhwp-studio/tests/collaboration-update.test.ts \
  rhwp-studio/tests/collaboration-document-adapter.test.ts \
  rhwp-studio/tests/collaboration-transport.test.ts \
  rhwp-studio/tests/collaboration-manifest.test.ts
```

`rhwp-studio/node_modules`가 존재하면 추가로 실행한다.

```bash
npm --prefix rhwp-studio run build
```

### Scope

```bash
git diff --check
git status --short
git diff --stat
```

## Completion Criteria

- [ ] 실행 계획 문서가 기록되어 있다.
- [ ] CollaborationContext가 manifest와 registry를 생성한다.
- [ ] update validator가 version/fingerprint/node/kind/size/sequence를 검증한다.
- [ ] Rust paragraph apply가 위치와 StableId를 검증하고 텍스트를 변경한다.
- [ ] Rust cell apply가 단일 문단 셀만 안전하게 변경한다.
- [ ] WASM wrapper와 TypeScript 선언이 추가된다.
- [ ] DocumentAdapter가 중복 update와 재발행 루프를 방지한다.
- [ ] BroadcastChannel transport가 자기 메시지·중복 메시지를 걸러낸다.
- [ ] focused Rust/TypeScript 테스트가 통과한다.
- [ ] Firebase/Yjs/UI 코드가 변경되지 않는다.
