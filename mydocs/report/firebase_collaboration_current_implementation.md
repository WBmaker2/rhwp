# Firebase 공동 편집 현재 구현 현황

- 작성일: 2026-07-26
- 기준 브랜치: `feat/firebase-collaboration-mvp-v1`
- 기준 커밋: `a4abbdb8`
- 문서 성격: 현재 코드 스냅샷 보고서
- 범위: Firebase 공동 편집 기능과 이를 지지하는 rhwp 구조

## 1. 요약

현재 rhwp에는 Firebase 공동 편집 서비스가 완성되어 있지 않다. 구현된 범위는 **원본 rhwp `Document`를 협업용 중간 manifest로 변환하기 위한 Rust 도메인 계층**이다.

현재까지 구현된 핵심은 다음과 같다.

- 협업 노드의 결정적 ID 생성
- 협업 manifest schema version 1 정의
- section, paragraph, table, row, cell, readonly object 모델 정의
- 기존 rhwp `Document`에서 문단 텍스트와 표 셀 텍스트 추출
- 표 구조와 비텍스트 control의 읽기 전용 표시
- 동일 입력에 대한 ID와 manifest 결정성 테스트
- 협업 모듈을 crate 외부에서 사용할 수 있도록 공개

현재 구현되지 않은 핵심은 다음과 같다.

- Firebase 프로젝트 및 SDK 연동
- Firebase Authentication
- Firestore 또는 Realtime Database 저장소
- 공유 링크 생성과 권한 관리
- 실시간 update 송수신
- CRDT 또는 OT 기반 충돌 해결
- 접속자, cursor, selection 표시
- Studio 공유 버튼과 협업 UI
- 협업 manifest 변경을 원본 `Document`에 되돌리는 exporter
- 공동 편집 결과의 HWP/HWPX 저장

즉, 현재 상태는 **협업 기능의 1단계 데이터 모델과 import 기반**이며, 사용자에게 노출되는 공유·동시 편집 기능은 아직 없다.

## 2. 프로젝트 개요

rhwp는 Rust로 HWP, HWPX, HWP3 문서를 읽고 편집·렌더링하며 WebAssembly를 통해 브라우저에서도 동작하는 문서 엔진이다.

### 핵심 기술 스택

| 영역 | 기술 |
| --- | --- |
| 문서 엔진 | Rust 2021 |
| 브라우저 런타임 | WebAssembly, `wasm-bindgen`, `web-sys` |
| 직렬화 | `serde`, `serde_json` |
| 결정적 해시 | `blake3` |
| HWP/HWPX parsing | `cfb`, `flate2`, `zip`, `quick-xml` 등 |
| 웹 에디터 | TypeScript, Vite |
| 렌더링 | Canvas2D, CanvasKit, SVG, native Skia 경로 |
| 테스트 | Rust integration tests, Node test, Studio E2E |

루트 crate 버전은 `0.7.19`이며 `cdylib`와 `rlib`를 함께 생성한다.

## 3. 저장소 구성

현재 저장소는 Rust 문서 엔진과 여러 클라이언트를 함께 포함한다.

| 경로 | 역할 |
| --- | --- |
| `src/` | Rust parser, model, renderer, serializer, WASM API |
| `src/collaboration/` | 새로 추가된 협업 manifest 도메인 계층 |
| `tests/` | Rust integration tests |
| `rhwp-studio/` | Vite 기반 웹 편집기 |
| `rhwp-shared/` | 브라우저 클라이언트 공통 코드·security 자산 |
| `rhwp-chrome/` | Chrome/Edge 확장 |
| `rhwp-firefox/` | Firefox 확장 |
| `rhwp-vscode/` | VS Code custom editor |
| `npm/editor/` | npm 에디터 패키지 관련 코드 |
| `mydocs/plans/` | 구현 계획서 |
| `mydocs/report/` | 최종 및 현황 보고서 |
| `mydocs/tech/` | 기술 조사·설계 자료 |
| `mydocs/manual/` | 개발·문서·검증 절차 |

협업 기능은 현재 `src/collaboration/`과 `tests/collaboration_model.rs`에 집중되어 있으며 프런트엔드 디렉터리에는 Firebase collaboration 구현이 확인되지 않는다.

## 4. 현재 브랜치와 변경 이력

현재 브랜치:

```text
feat/firebase-collaboration-mvp-v1
```

분석 시점의 HEAD:

```text
a4abbdb8 style: format collaboration importer
```

협업 관련 최근 커밋 흐름은 다음과 같다.

| 커밋 | 내용 |
| --- | --- |
| `de7607c4` | Firebase 공동 편집 구현 계획 문서 추가 |
| `581cbc65` | Firebase 공동 편집 1차 버전 설계 문서 추가 |
| `fa9928e2` | 결정적 collaboration ID 계약 테스트 |
| `0abeab78` | 결정적 collaboration ID 구현 |
| `f856a599` | collaboration manifest 타입 추가 |
| `57c0b9c6` | collaboration 타입 공개 |
| `1f5cdc37` | crate에서 collaboration 모듈 공개 |
| `73cb13b7` | document import 계약 실패 테스트 추가 |
| `9bb4e60b` | `Document` collaboration manifest importer 구현 |
| `87f4b086` | importer API 공개 |
| `a4abbdb8` | importer formatting 정리 |

이 이력은 TDD 형태로 ID 계약과 import 계약을 먼저 정의한 뒤 구현을 추가한 흐름을 보여준다.

## 5. 구현된 코드

## 5.1 모듈 공개

### `src/lib.rs`

`collaboration` 모듈을 public module로 노출한다.

```rust
pub mod collaboration;
```

이를 통해 integration test와 외부 crate 사용자가 협업 타입과 importer를 사용할 수 있다.

### `src/collaboration/mod.rs`

하위 모듈을 구성하고 public API를 재노출한다.

- `import`
- `model`
- `stable_id`

공개 API:

- `build_collaboration_manifest`
- `CollaborationError`
- manifest 구조체들
- `COLLABORATION_SCHEMA_VERSION`
- `NodeKind`
- `StableId`

## 5.2 결정적 Stable ID

### `src/collaboration/stable_id.rs`

협업 노드를 식별하는 `StableId`가 구현되어 있다.

```rust
pub struct StableId(pub String);
```

ID 입력 요소:

- 고정 namespace: `rhwp-collaboration-id-v1`
- `source_fingerprint`
- `NodeKind`
- 문서 안의 node path

해시 알고리즘:

- BLAKE3
- 결과는 hex 문자열

지원 node 종류:

- Section
- Paragraph
- Table
- Row
- Cell
- Image
- ReadonlyObject

### 보장되는 성질

- 같은 source fingerprint, node kind, path는 같은 ID를 생성한다.
- path가 다르면 다른 ID를 생성한다.
- ID는 프로세스 메모리 주소나 임의 UUID에 의존하지 않는다.

### 현재 제약

- ID는 원본 source fingerprint와 구조 경로에 의존한다.
- 문단 또는 control 순서가 바뀌면 이후 path가 달라져 ID도 달라질 수 있다.
- `Image` variant는 정의되어 있으나 importer에서 별도 image manifest를 생성하지 않는다.
- 해시 충돌 처리나 ID alias/migration 계층은 없다.

## 5.3 Collaboration manifest model

### `src/collaboration/model.rs`

현재 schema version:

```rust
pub const COLLABORATION_SCHEMA_VERSION: u32 = 1;
```

### `CollaborationManifest`

포함 필드:

- `schema_version`
- `source_fingerprint`
- `sections`
- `readonly_objects`

`empty()` 생성자는 schema version과 fingerprint를 설정하고 비어 있는 collection을 만든다.

### Section

`SectionManifest`는 다음을 포함한다.

- section `id`
- `paragraphs`
- `tables`

### Paragraph

`ParagraphManifest`:

- `id`
- `text`
- `style_ref`

현재 문단에서는 전체 문자열과 단일 style ID reference만 보관한다.

### Table

`TableManifest`:

- `id`
- `rows`
- `cells`
- `structure_readonly`

표는 텍스트 편집 대상 후보지만 구조는 읽기 전용으로 명시된다.

### Row

`RowManifest`:

- row `id`
- 해당 row에 포함된 `cell_ids`

### Cell

`CellManifest`:

- `id`
- `text`
- `style_ref`
- `structure_readonly`

셀의 여러 문단 텍스트는 줄바꿈 문자로 합쳐 하나의 문자열로 저장된다.

### Readonly object

`ReadonlyObjectManifest`:

- `id`
- 문자열 `kind`

현재 비텍스트 control은 상세 payload 없이 종류와 stable ID만 기록된다.

## 5.4 Document importer

### `src/collaboration/import.rs`

주요 API:

```rust
pub fn build_collaboration_manifest(
    document: &Document,
    source_fingerprint: &str,
) -> Result<CollaborationManifest, CollaborationError>
```

### 오류 처리

현재 오류 variant는 하나다.

```rust
CollaborationError::EmptySourceFingerprint
```

빈 fingerprint는 importer에서 거부한다.

### import 흐름

1. 빈 `CollaborationManifest`를 생성한다.
2. `Document.sections`를 순회한다.
3. section path로 section stable ID를 만든다.
4. section의 paragraph를 순회한다.
5. paragraph 전체 text와 style ID를 `ParagraphManifest`에 저장한다.
6. paragraph의 control을 순회한다.
7. table control은 `TableManifest`로 변환한다.
8. 그 외 control은 `ReadonlyObjectManifest`로 기록한다.

### 문단 변환

- `Paragraph.text`를 그대로 복사한다.
- `Paragraph.style_id`를 `u32`로 변환해 `style_ref`에 저장한다.
- char-shape run, line segment, paragraph shape 상세 정보는 manifest에 포함하지 않는다.

### 표 변환

- 원본 `row_count`만큼 row manifest를 생성한다.
- cell의 `row` 값으로 해당 row에 셀을 배치한다.
- cell ID path에는 control path와 cell의 원본 vector index를 사용한다.
- 셀 안 여러 paragraph의 text를 `\n`으로 연결한다.
- 첫 문단의 style ID만 cell `style_ref`로 사용한다.
- table과 cell 모두 `structure_readonly: true`다.

### 읽기 전용 control 분류

다음 control 종류를 문자열로 분류한다.

- section definition
- column definition
- shape
- picture
- header
- footer
- footnote
- endnote
- auto/new number
- page number position
- bookmark
- hyperlink
- ruby
- character overlap
- page hide
- hidden comment
- equation
- field
- form
- unknown

Table은 별도 분기로 처리되므로 정상 importer 흐름에서 readonly control kind `table`은 사용되지 않는다.

## 6. 구현된 테스트

### `tests/collaboration_model.rs`

현재 확인되는 테스트 계약은 다음과 같다.

### Stable ID

- 같은 source와 path에서 ID가 동일함
- path가 달라지면 ID가 달라짐

### Document manifest import

fixture `Document`에 section, paragraph, table, equation 등을 구성해 다음을 검증한다.

- source fingerprint 보존
- schema version 보존
- section과 paragraph 개수
- 문단 text와 style reference
- table, row, cell 구성
- 셀 text 결합
- table과 cell 구조 읽기 전용
- equation이 readonly object로 분류됨

### 결정성

동일한 `Document`와 fingerprint로 importer를 두 번 실행한 결과가 동일함을 검증한다.

### 테스트 공백

현재 보고서 작성 시점에 다음 계약 테스트는 확인되지 않는다.

- manifest JSON serialization round-trip
- 빈 fingerprint 오류
- 빈 문서와 다중 section
- 병합 셀과 span 정보
- image 전용 manifest
- 대형 문서 성능
- schema migration
- importer 결과를 `Document`로 되돌리는 round-trip
- WASM API 경계
- Firebase emulator 또는 클라이언트 E2E

## 7. 현재 데이터 흐름

구현된 실제 흐름:

```text
HWP/HWPX/HWP3 parser
        ↓
rhwp::model::Document
        ↓ build_collaboration_manifest(document, fingerprint)
CollaborationManifest v1
```

아직 연결되지 않은 예정 흐름:

```text
CollaborationManifest
        ↓ WASM/TypeScript
실시간 협업 client state
        ↕ Firebase/CRDT
원격 사용자
        ↓ export
rhwp::model::Document
        ↓ serializer
HWP/HWPX 결과 파일
```

현재는 위 예정 흐름의 첫 번째 변환까지만 구현되어 있다.

## 8. 아직 구현되지 않은 사용자 기능

### 공유

- Studio에 공유 버튼 없음
- share ID와 URL 생성 없음
- 링크 복사 dialog 없음
- 링크 만료와 폐기 없음

### 인증과 권한

- Firebase Auth 없음
- owner/editor/viewer 역할 없음
- Security Rules 없음
- 익명 또는 Google 로그인 정책 없음

### 실시간 동기화

- Firestore listener 없음
- local edit update 전송 없음
- remote update 적용 없음
- CRDT/OT 없음
- 중복·순서 역전·재접속 처리 없음

### presence

- 접속 사용자 목록 없음
- 원격 cursor와 selection 없음
- typing 상태 없음

### 저장과 내보내기

- collaboration manifest를 `Document`에 적용하는 함수 없음
- 공동 편집 상태를 HWP/HWPX로 저장하는 경로 없음
- snapshot 또는 version 복구 없음

## 9. 기술적 제약과 부채

## 9.1 단방향 변환

현재 importer는 `Document → CollaborationManifest`만 지원한다. 실제 공동 편집 결과를 파일로 저장하려면 stable ID를 원본 node와 다시 연결하는 exporter가 필요하다.

## 9.2 스타일 표현이 매우 제한적

문단과 셀은 단일 `style_ref`만 보관한다. 한 문단 안에 여러 character style run이 있는 경우 공동 편집 모델에서 정확한 범위를 표현하지 못한다.

## 9.3 표 구조 정보 부족

manifest는 row와 cell 목록을 가지지만 다음 상세 구조가 없다.

- row span
- column span
- 열 폭과 행 높이
- cell address
- 병합 관계
- nested table 관계

MVP에서 구조를 읽기 전용으로 유지한다면 당장 편집에 필요하지 않지만, 안정적인 export와 UI mapping에는 추가 metadata가 필요할 수 있다.

## 9.4 Readonly object payload 미보존

readonly object는 ID와 kind만 있다. 원본 `Document`가 메모리에 유지된다는 전제가 깨지면 manifest만으로 해당 객체를 복원할 수 없다.

## 9.5 Stable ID의 구조 경로 의존성

ID가 vector index 기반 path에 의존하므로 구조 편집이 허용되면 ID가 연쇄적으로 달라질 수 있다. 현재 표 구조를 읽기 전용으로 둔 결정은 이 위험과 일치한다.

## 9.6 Firebase adapter 경계 없음

현재 Firebase dependency가 없다는 점은 오히려 장점이지만, 이후 SDK를 Studio 전역에 직접 사용하면 테스트와 교체 가능성이 악화될 수 있다. repository/adapter 계층이 필요하다.

## 9.7 Undo/Redo 정책 미정

기존 Studio의 local command history와 원격 CRDT transaction을 어떻게 분리할지 아직 코드 계약이 없다. 원격 변경까지 local undo 대상으로 넣으면 다른 사용자의 입력을 되돌리는 문제가 발생할 수 있다.

## 9.8 Reflow와 pagination 연결

텍스트 변경을 원본 `Document`에 반영할 때 rhwp의 reflow와 pagination이 다시 실행되어야 한다. 공동 편집 상태 수렴과 화면 layout 수렴은 서로 다른 문제이므로 별도 검증이 필요하다.

## 10. 현실적인 완성도 판단

| 영역 | 상태 | 판단 |
| --- | --- | --- |
| 협업 도메인 타입 | 구현 | 기본 schema v1 존재 |
| 결정적 node ID | 구현 | MVP 기반으로 사용 가능 |
| Document import | 구현 | 문단·표 셀 텍스트 중심 |
| Rust 계약 테스트 | 부분 구현 | 핵심 happy path와 결정성 검증 |
| WASM 노출 | 미구현 | Studio가 manifest를 아직 사용하지 못함 |
| Firebase backend | 미구현 | 설정·SDK·rules 모두 없음 |
| 인증·권한 | 미구현 | 공유 보안 기능 없음 |
| 실시간 편집 | 미구현 | update protocol 없음 |
| 충돌 해결 | 미구현 | 동시 입력 수렴 불가 |
| 공유 UI | 미구현 | 사용자 진입점 없음 |
| Document export | 미구현 | 결과 파일 저장 불가 |
| 운영·비용·관측 | 미구현 | production 준비 전 단계 |

종합하면 전체 Firebase 공동 편집 MVP의 완성도는 **도메인 기반 착수 단계**다. 핵심 데이터 모델의 방향은 잡혔지만, 사용자 관점의 공동 편집 기능은 아직 시작되지 않았다.

## 11. 다음 작업 권장 순서

1. collaboration manifest JSON 계약과 fixture를 고정한다.
2. WASM API로 manifest를 Studio에 노출한다.
3. TypeScript 타입과 stable ID ↔ 편집 위치 mapping을 구현한다.
4. Firebase emulator에서 세션, 멤버, 공유 링크, Security Rules를 구현한다.
5. 텍스트 CRDT를 연결해 두 클라이언트 수렴 테스트를 통과시킨다.
6. Studio 공유 UI와 연결 상태 표시를 추가한다.
7. manifest 변경을 원본 `Document`에 반영하는 exporter를 구현한다.
8. 공동 편집 결과를 저장하고 재열기까지 검증한다.

세부 단계와 완료 기준은 `mydocs/plans/firebase_collaboration_implementation_plan.md`에 기록한다.

## 12. 분석 근거 파일

- `Cargo.toml`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `mydocs/README.md`
- `mydocs/manual/codex/docs_and_git_workflow.md`
- `src/lib.rs`
- `src/collaboration/mod.rs`
- `src/collaboration/model.rs`
- `src/collaboration/stable_id.rs`
- `src/collaboration/import.rs`
- `tests/collaboration_model.rs`
- `rhwp-studio/package.json`
- `rhwp-shared/package.json`
- `rhwp-chrome/package.json`
- `rhwp-firefox/package.json`
- `rhwp-vscode/package.json`
