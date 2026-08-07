# Firebase Collaboration Tasks 1–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 협업 manifest의 JSON·검증 계약을 고정하고, 현재 `HwpDocument`를 검증된 `CollaborationManifest` JSON으로 반환하는 WASM API를 제공한다.

**Architecture:** 기존 `Document → CollaborationManifest` importer는 유지하되, 오류와 검증 책임을 `error.rs`와 `validation.rs`로 분리한다. WASM API는 importer와 동일한 검증 경로를 사용하고 JSON 문자열만 반환하며, TypeScript·CRDT·Firebase 연결은 이번 범위에 포함하지 않는다.

**Tech Stack:** Rust 2021, serde/serde_json, wasm-bindgen, 기존 rhwp `DocumentCore`와 `HwpDocument`, Rust integration/unit tests.

## Global Constraints

- 기준 브랜치는 `feat/firebase-collaboration-mvp-v1`이다.
- 기존 사용자가 작성한 문서와 변경을 되돌리지 않는다.
- Firebase SDK, TypeScript 협업 계층, CRDT, 공유 UI는 수정하지 않는다.
- 원본 `Document`와 협업 manifest의 단방향 변환 범위만 다룬다.
- 생산 코드보다 실패하는 테스트를 먼저 작성하고 RED → GREEN → REFACTOR 순서를 지킨다.
- 전체 테스트 전에 focused collaboration/WASM 테스트를 실행한다.
- 커밋과 PR 생성은 사용자의 별도 요청 없이는 수행하지 않는다.

---

### Task 1: CollaborationManifest 직렬화·검증 계약 보강

**Files:**
- Create: `src/collaboration/error.rs`
- Create: `src/collaboration/validation.rs`
- Modify: `src/collaboration/mod.rs`
- Modify: `src/collaboration/import.rs`
- Modify: `tests/collaboration_model.rs`

**Interfaces:**
- Produces: `validate_source_fingerprint(value: &str) -> Result<(), CollaborationError>`
- Produces: `validate_collaboration_manifest(manifest: &CollaborationManifest) -> Result<(), CollaborationError>`
- Produces: `CollaborationError::{EmptySourceFingerprint, InvalidSourceFingerprint, UnsupportedSchemaVersion}`
- Preserves: `build_collaboration_manifest(document, source_fingerprint)` public signature.

- [x] **Step 1: JSON round-trip 및 결정성 실패 테스트 작성**

  - 다중 section, 다중 paragraph, 다중 table을 포함하는 작은 in-memory fixture를 만든다.
  - `serde_json::to_string` 후 `from_str` 결과가 원본 manifest와 같음을 검증한다.
  - 같은 document와 fingerprint를 두 번 import한 JSON 문자열이 byte-for-byte 동일함을 검증한다.

- [x] **Step 2: edge case 및 검증 함수 실패 테스트 작성**

  - 빈 문단과 빈 셀 텍스트가 빈 문자열로 보존되는지 검증한다.
  - 대표 readonly control이 기대한 kind 문자열로 기록되는지 검증한다.
  - 빈 fingerprint, 앞뒤 공백, 구분자 없음, 빈 algorithm/digest, 제어 문자를 거부하는 테스트를 작성한다.
  - 현재 schema version은 허용하고 다른 schema version은 `UnsupportedSchemaVersion`으로 거부하는 테스트를 작성한다.

- [x] **Step 3: RED 확인**

  Run: `cargo test --test collaboration_model collaboration_manifest_json -- --nocapture`

  Run: `cargo test --test collaboration_model validates_ -- --nocapture`

  Expected: 새 검증 API와 오류 variant가 없어 컴파일 또는 assertion 실패.

- [x] **Step 4: 최소 오류·검증 구현**

  - `CollaborationError`를 `error.rs`로 이동한다.
  - fingerprint는 `algorithm:digest` 형식, 최대 256 bytes, 공백·제어 문자 금지로 검증한다.
  - algorithm은 소문자 ASCII 영숫자와 `-`, digest는 ASCII 영숫자와 `-_.`만 허용한다.
  - manifest의 `schema_version`과 `source_fingerprint`를 검증한다.
  - importer는 공통 fingerprint 검증 함수를 호출한다.

- [x] **Step 5: GREEN 및 회귀 확인**

  Run: `cargo test --test collaboration_model -- --nocapture`

  Expected: Task 1의 모든 계약 테스트 통과.

---

### Task 2: CollaborationManifest JSON WASM API

**Files:**
- Modify: `src/wasm_api.rs`
- Modify: `src/wasm_api/tests.rs`
- Modify: `typescript/rhwp.d.ts`

**Interfaces:**
- Produces native Rust method: `HwpDocument::get_collaboration_manifest_native(&self, source_fingerprint: &str) -> Result<String, CollaborationError>`
- Produces WASM method: `HwpDocument.getCollaborationManifest(sourceFingerprint: string): string`
- JSON result conforms to `COLLABORATION_SCHEMA_VERSION` and passes `validate_collaboration_manifest`.

- [x] **Step 1: native/WASM 계약 실패 테스트 작성**

  - `HwpDocument::create_empty()`에서 유효 fingerprint로 JSON을 반환하는 테스트를 작성한다.
  - 반환 JSON을 `CollaborationManifest`로 역직렬화해 schema, fingerprint, section/paragraph 존재를 검증한다.
  - 잘못된 fingerprint가 오류를 반환하는 테스트를 작성한다.
  - 동일 문서와 fingerprint의 JSON이 반복 호출에서 동일함을 검증한다.

- [x] **Step 2: RED 확인**

  Run: `cargo test wasm_api::tests::collaboration_manifest -- --nocapture`

  Expected: 새 native API가 없어 컴파일 실패.

- [x] **Step 3: 최소 native/WASM 구현**

  - native helper는 `build_collaboration_manifest` 호출 후 manifest 검증, `serde_json::to_string`을 수행한다.
  - WASM wrapper는 `#[wasm_bindgen(js_name = getCollaborationManifest)]`를 사용하고 오류를 `JsValue` 문자열로 변환한다.
  - API는 문서를 변경하지 않는 `&self` query로 구현한다.

- [x] **Step 4: TypeScript 선언 보강**

  - `typescript/rhwp.d.ts`의 `HwpDocument`에 `getCollaborationManifest(sourceFingerprint: string): string`을 추가한다.
  - 반환값이 JSON 문자열이며 schema version 1의 collaboration manifest임을 주석으로 명시한다.

- [x] **Step 5: GREEN 및 범위 검증**

  Run: `cargo test wasm_api::tests::collaboration_manifest -- --nocapture`

  Run: `cargo test --test collaboration_model -- --nocapture`

  Run: `cargo check`

  Expected: focused tests와 Rust compilation 통과.

---

## Completion Checklist

- [x] 계획 문서가 `mydocs/plans/`에 기록되어 있다.
- [x] CollaborationManifest JSON round-trip과 byte 결정성이 검증된다.
- [x] 다중 section·문단·표, 빈 문단·셀, readonly control 계약이 검증된다.
- [x] schema version과 fingerprint 공통 검증 API가 공개된다.
- [x] `getCollaborationManifest` WASM API가 검증된 JSON을 반환한다.
- [x] TypeScript 선언이 API와 일치한다.
- [x] Firebase, CRDT, Studio UI 코드는 변경되지 않는다.
- [x] Git diff에 계획 문서와 Task 1·2 관련 파일만 포함된다.


## Implementation Result

- 구현일: 2026-07-26
- Task 1: collaboration manifest JSON round-trip, byte 결정성, 다중 section·문단·표, 빈 문단·셀, readonly control, schema version, fingerprint 계약을 구현하고 테스트했다.
- Task 2: `HwpDocument::get_collaboration_manifest_native`와 WASM `getCollaborationManifest` API, TypeScript 선언을 구현했다.
- 검증: `cargo fmt --check`, `cargo test --test collaboration_model -- --nocapture`, `cargo check`가 종료 코드 0으로 통과했다.
- 제외 범위: Firebase, CRDT, Studio 공유 UI, Document 역적용은 변경하지 않았다.
- Git commit과 PR은 생성하지 않았다.
