---
kind: plan
status: active
canonical: mydocs/manual/codex/docs_and_git_workflow.md
last_verified: 2026-07-26
---

# Firebase Collaboration Task 3 구현 계획

## 목표

협업 manifest가 각 편집 가능 텍스트 노드의 원본 문서 위치를 직접 제공하도록 확장하고, rhwp-studio에서 manifest JSON을 검증한 뒤 `StableId`로 문단·표 셀 위치를 조회하는 TypeScript node registry를 구현한다.

## 범위

### Rust

- `ParagraphManifest`에 `ParagraphLocation`을 추가한다.
- `CellManifest`에 `CellLocation`을 추가한다.
- importer가 section, paragraph, control, cell, row, column 위치를 채운다.
- 위치 필드는 기존 schema version 1에 additive 필드로 추가한다.
- manifest 위치 정보와 JSON round-trip 회귀 테스트를 추가한다.

### TypeScript

- `rhwp-studio/src/collaboration/types.ts`: schema v1 타입 정의
- `errors.ts`: 파싱·계약 오류
- `manifest-parser.ts`: JSON, schema, fingerprint, 중복 ID, 위치 필드 검증
- `node-registry.ts`: `StableId → paragraph/cell location` 조회
- `rhwp-studio/tests/collaboration-manifest.test.ts`: parser와 registry 계약 테스트

## 설계 결정

### schema version 1 유지

이번 변경은 기존 필드를 삭제하거나 의미를 바꾸지 않고 위치 정보를 추가하는 additive 확장이다. 아직 Firebase 영속 데이터나 외부 공개 협업 소비자가 없으므로 `COLLABORATION_SCHEMA_VERSION = 1`을 유지한다. 이후 위치 필드의 의미 변경 또는 필수 구조 변경이 발생하면 version 2로 올린다.

### 위치 정보는 manifest가 소유

TypeScript에서 Rust의 BLAKE3 ID와 traversal 규칙을 복제하지 않는다. Rust importer가 다음 위치를 manifest에 기록한다.

- 문단: `section_index`, `paragraph_index`
- 표 셀: `section_index`, `host_paragraph_index`, `control_index`, `cell_index`, `row_index`, `column_index`

### node registry 경계

registry에는 편집 가능한 문단과 셀만 등록한다. section, table, row, readonly object는 조회 대상에서 제외한다. 중복 ID는 silent overwrite하지 않고 parser 단계에서 거부한다.

## TDD 실행 순서

1. Rust 위치 정보 테스트를 작성하고 실패를 확인한다.
2. Rust 모델과 importer를 최소 수정해 통과시킨다.
3. TypeScript parser·registry 테스트를 작성하고 실패를 확인한다.
4. TypeScript 모듈을 최소 구현해 통과시킨다.
5. focused Rust/TypeScript 테스트, `cargo check`, `npm run build`를 실행한다.
6. Git diff에서 Task 3 관련 파일 외 변경이 없는지 확인한다.

## 완료 기준

- 모든 paragraph와 cell manifest에 정확한 source location이 있다.
- 기존 schema version 1과 JSON 직렬화 계약이 유지된다.
- parser가 잘못된 JSON, unsupported schema, fingerprint mismatch, duplicate StableId, 잘못된 위치를 거부한다.
- registry가 paragraph/cell StableId를 정확한 위치로 조회한다.
- readonly object는 registry에 포함되지 않는다.
- Firebase, CRDT, 공유 UI는 변경하지 않는다.
- 커밋과 push는 수행하지 않는다.
