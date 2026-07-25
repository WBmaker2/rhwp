# Firebase 공동 편집 구현 계획

- 작성일: 2026-07-26
- 기준 브랜치: `feat/firebase-collaboration-mvp-v1`
- 기준 커밋: `a4abbdb8`
- 대상: rhwp 기반 문서 공유 링크 및 동시 편집 MVP
- 범위: 구현 계획 문서. 이 문서 작성 과정에서는 코드와 설정을 변경하지 않는다.

## 1. 목표

rhwp에서 HWP/HWPX/HWP3 문서를 연 사용자가 **공유 링크를 생성**하고, 링크를 받은 사용자가 브라우저에서 같은 문서에 접속하여 **문단 텍스트와 표 셀 텍스트를 실시간으로 공동 편집**할 수 있는 1차 버전을 구현한다.

1차 버전은 구글 문서 전체 기능을 복제하지 않는다. 현재 rhwp 문서 모델과 저장 포맷의 제약을 고려해 다음 범위로 제한한다.

- 문단 텍스트 공동 편집
- 표 셀 내부 텍스트 공동 편집
- 공유 링크 생성과 링크 기반 입장
- 문서 소유자와 편집 참여자 권한 구분
- 접속자 및 동기화 상태 표시
- 원본 문서 구조와 지원하지 않는 객체의 읽기 전용 보존
- 협업 세션의 명시적 내보내기 또는 저장

## 2. 현재 출발점

현재 브랜치에는 협업 기능의 Rust 도메인 기반이 일부 구현되어 있다.

- `src/collaboration/stable_id.rs`
  - 원본 fingerprint, 노드 종류, 노드 경로를 BLAKE3로 해시하여 결정적 `StableId` 생성
- `src/collaboration/model.rs`
  - schema version 1의 `CollaborationManifest`와 section, paragraph, table, row, cell, readonly object 모델 정의
- `src/collaboration/import.rs`
  - rhwp `Document`를 협업 manifest로 변환
  - 문단 텍스트와 style reference 추출
  - 표 구조와 셀 텍스트 추출
  - 표 구조를 읽기 전용으로 표시
  - 수식, 그림, 머리말, 꼬리말 등 비텍스트 control을 읽기 전용 객체로 기록
- `tests/collaboration_model.rs`
  - 결정적 ID, 경로별 ID 차이, manifest import 결과와 반복 실행 결정성 검증
- `src/lib.rs`
  - `collaboration` 모듈 공개

아직 구현되지 않은 핵심 영역은 다음과 같다.

- Firebase SDK와 Firebase 프로젝트 설정
- 인증과 사용자 프로필
- Firestore 문서 스키마와 Security Rules
- 공유 링크 생성·해제·만료
- 실시간 구독과 로컬 편집 연결
- 충돌 해결 알고리즘
- presence, cursor, selection
- Studio의 공유 UI
- 서버 저장본에서 rhwp `Document`로 역적용하는 exporter
- HWP/HWPX 파일 재저장 및 버전 복구

## 3. MVP 범위와 명시적 비범위

### 3.1 MVP에 포함

- 이메일 또는 Google 로그인
- 문서 소유자가 공유 세션 생성
- 추측하기 어려운 share ID 기반 URL
- 소유자, 편집자, 뷰어 역할
- 문단과 표 셀의 텍스트 변경 실시간 전파
- 동일 텍스트 노드 내 동시 입력 충돌 처리
- 비지원 객체와 표 구조의 읽기 전용 유지
- 연결, 저장, 재연결 상태 표시
- 원본 fingerprint와 collaboration schema version 검증
- 기본 감사 정보: 생성자, 생성 시각, 최종 수정 시각

### 3.2 MVP에서 제외

- 표 행·열의 동시 삽입과 삭제
- 도형, 그림, 수식, 차트의 공동 편집
- 문자·문단 서식 전체의 동시 편집
- 익명 사용자의 무제한 편집
- 공개 검색 가능한 문서
- 오프라인 장기 편집 후 복잡한 병합
- 댓글, 제안 모드, 변경 내용 추적
- 다중 브랜치 문서 버전 관리
- 원본 HWP 바이너리를 클라이언트가 직접 덮어쓰기

## 4. 권장 아키텍처

### 4.1 책임 경계

```text
원본 HWP/HWPX/HWP3
        ↓ rhwp parser
Rust Document IR
        ↓ build_collaboration_manifest
CollaborationManifest v1
        ↓ WASM/TypeScript bridge
협업 클라이언트 상태
        ↕ CRDT update
Firestore 세션 저장소
        ↕ snapshot/export
Rust Document 반영 및 파일 저장
```

핵심 원칙은 **Firebase 데이터를 원본 HWP 구조의 직접 직렬화 포맷으로 사용하지 않는 것**이다. Firestore에는 협업 세션과 텍스트 변경 상태를 저장하고, rhwp의 `Document`는 import/export 경계에서 관리한다.

### 4.2 충돌 해결

Firestore의 단순 last-write-wins만으로 텍스트를 동기화하면 같은 문단을 동시에 수정할 때 입력이 손실될 수 있다. 텍스트 노드 단위 CRDT를 사용한다.

권장안:

- 클라이언트 CRDT: Yjs
- 텍스트 단위: `StableId`별 `Y.Text`
- Firestore: 세션 metadata, snapshot, update chunk 저장
- presence: Firestore 영속 저장과 분리하고 가능하면 Realtime Database 또는 짧은 TTL 문서 사용

대안:

- 1차 데모에 한해 node-level 낙관적 revision과 transaction을 사용할 수 있으나, 동일 문단 동시 입력을 안전하게 처리하지 못하므로 정식 MVP 완료 기준으로 삼지 않는다.

### 4.3 Firestore 권장 데이터 모델

```text
collaborationSessions/{sessionId}
  ownerUid
  sourceFingerprint
  schemaVersion
  title
  status
  createdAt
  updatedAt
  accessMode
  currentSnapshotVersion

collaborationSessions/{sessionId}/members/{uid}
  role
  displayName
  joinedAt
  lastSeenAt

collaborationSessions/{sessionId}/updates/{updateId}
  clientId
  sequence
  payload
  createdAt

collaborationSessions/{sessionId}/snapshots/{version}
  manifest
  crdtState
  createdAt
  createdBy

shareLinks/{shareId}
  sessionId
  role
  expiresAt
  revokedAt
  createdBy
```

원본 파일 자체는 Firestore 문서에 넣지 않는다. 필요하면 Firebase Storage에 암호화된 원본 blob과 export 결과를 저장하고 Firestore에는 경로와 해시만 기록한다.

## 5. 단계별 구현 계획

## Phase 0. 계약과 안전 경계 확정

### 산출물

- collaboration schema v1 명세
- 지원·비지원 편집 범위 표
- Firestore data model과 Security Rules 초안
- 개인정보·보존 기간·삭제 정책

### 작업

1. `CollaborationManifest` JSON 예제를 fixture로 고정한다.
2. schema version 불일치 시 읽기 전용 또는 명시적 오류로 처리하는 정책을 정한다.
3. `StableId`가 원본 generation 안에서만 유효하다는 점을 명시한다.
4. 원본이 다시 업로드되어 fingerprint가 바뀌면 새 협업 세션으로 처리한다.
5. 공유 링크가 인증을 우회하지 않도록 Security Rules를 설계한다.

### 검증 기준

- 동일 문서와 fingerprint에서 manifest JSON이 결정적이다.
- 빈 fingerprint가 거부된다.
- 비지원 control은 누락되지 않고 readonly object로 기록된다.
- 공유 링크만 알아도 권한이 없는 문서를 직접 읽을 수 없다.

## Phase 1. Rust 협업 manifest 완성

### 대상 파일

- `src/collaboration/model.rs`
- `src/collaboration/import.rs`
- `src/collaboration/stable_id.rs`
- `tests/collaboration_model.rs`

### 작업

1. manifest JSON round-trip 테스트를 추가한다.
2. 빈 문서, 다중 section, 다중 문단, 병합 셀, 빈 셀 fixture를 추가한다.
3. readonly object 종류와 경로 안정성을 검증한다.
4. source fingerprint 생성 책임을 API 경계에서 명확히 한다.
5. manifest 크기와 import 성능 기준선을 측정한다.

### 검증 기준

- `cargo test --test collaboration_model` 통과
- 동일 입력의 serialized manifest byte가 반복 실행에서 동일
- 대형 문서에서도 manifest import가 정해진 메모리·시간 한도 안에 완료

## Phase 2. WASM/TypeScript 브리지

### 예상 대상

- `src/wasm_api/`
- `rhwp-studio/src/`
- `npm/editor/`

### 작업

1. 현재 열린 문서에서 collaboration manifest JSON을 반환하는 WASM API를 노출한다.
2. fingerprint 계산 API 또는 호출 계약을 추가한다.
3. TypeScript 타입을 Rust schema와 동기화한다.
4. schema version과 source fingerprint를 클라이언트에서 검증한다.
5. text node ID와 Studio 편집 위치 사이의 mapping 계층을 만든다.

### 검증 기준

- Studio에서 업로드한 문서를 manifest JSON으로 추출 가능
- Rust fixture와 TypeScript parser 결과 일치
- 지원하지 않는 객체가 편집 가능 상태로 잘못 노출되지 않음

## Phase 3. Firebase 기반 세션과 권한

### 예상 대상

- `rhwp-studio/src/collaboration/`
- Firebase 설정 파일
- `rhwp-shared/security/`

### 작업

1. Firebase SDK를 별도 collaboration adapter 뒤에 둔다.
2. emulator 기반 Auth, Firestore, Storage 환경을 구성한다.
3. session repository와 share-link repository 인터페이스를 정의한다.
4. 소유자, 편집자, 뷰어 권한을 Security Rules와 애플리케이션 양쪽에서 검증한다.
5. 링크 폐기와 만료를 지원한다.

### 검증 기준

- 소유자만 공유 링크 생성·폐기 가능
- 뷰어는 update 작성 불가
- 편집자는 허용된 session에만 update 작성 가능
- 링크 폐기 직후 신규 접속 차단
- emulator rules test 통과

## Phase 4. CRDT 동기화

### 작업

1. `StableId`별 CRDT text map을 생성한다.
2. 로컬 입력을 CRDT transaction으로 변환한다.
3. 원격 update를 Studio 문서 모델에 적용한다.
4. update batching, snapshot, compaction을 구현한다.
5. 재접속 시 snapshot 이후 update만 재생한다.
6. 중복 update와 순서 역전을 멱등 처리한다.

### 검증 기준

- 두 브라우저에서 같은 문단에 동시에 입력해도 텍스트 손실 없음
- 문단 A와 문단 B의 동시 편집이 독립적으로 수렴
- 네트워크 단절 후 재접속 시 동일 상태로 수렴
- update를 두 번 받아도 결과가 중복되지 않음

## Phase 5. 공유 UI와 사용자 피드백

### 예상 UI

- 상단 `공유` 버튼
- 공유 dialog: 역할, 링크 복사, 만료, 폐기
- 접속자 avatar 또는 이름
- `연결 중`, `저장 중`, `저장됨`, `오프라인`, `충돌 복구 필요` 상태
- 비지원 객체의 읽기 전용 안내

### 작업

1. 소유자 공유 흐름을 구현한다.
2. 링크 진입 시 인증과 권한 확인 화면을 구현한다.
3. presence와 접속자 목록을 표시한다.
4. 원격 cursor·selection은 텍스트 mapping이 안정된 뒤 추가한다.
5. 저장 실패와 권한 변경을 사용자에게 명확하게 표시한다.

### 검증 기준

- 공유 링크 생성부터 두 번째 사용자 편집까지 끊김 없는 흐름
- 권한 오류가 무응답이나 데이터 손실로 보이지 않음
- 모바일·데스크톱 기본 반응형 확인
- 키보드만으로 공유 dialog 조작 가능

## Phase 6. Document 역적용과 내보내기

현재 구현은 `Document → CollaborationManifest` 단방향이다. 실제 파일 저장을 위해 반대 방향의 명시적 적용 계층이 필요하다.

### 작업

1. manifest의 editable text를 원본 `Document` node에 적용하는 exporter를 설계한다.
2. source fingerprint와 stable ID mapping을 검증한다.
3. 문단 텍스트 및 표 셀 텍스트만 변경하고 readonly 구조는 보존한다.
4. reflow와 pagination을 재실행한다.
5. HWP/HWPX 저장 결과를 재파싱하여 의미 보존을 검증한다.
6. export 전 snapshot을 생성하고 실패 시 원상 복구한다.

### 검증 기준

- 공동 편집된 문단·셀 텍스트가 다운로드한 문서에 반영
- 비지원 객체와 표 구조가 손상되지 않음
- 저장 파일을 rhwp가 다시 열 수 있음
- export 실패 시 기존 session과 원본 파일 유지

## Phase 7. 운영 안정화

### 작업

1. update 수, snapshot 크기, 재접속 시간, 오류율을 계측한다.
2. rate limit과 payload size limit을 둔다.
3. 오래된 presence와 update chunk 정리 정책을 적용한다.
4. session 삭제와 사용자 데이터 삭제 흐름을 구현한다.
5. emulator E2E와 실제 staging 환경 검증을 분리한다.
6. Firebase 비용 상한과 경보를 설정한다.

### 검증 기준

- 문서별 저장 용량과 읽기·쓰기 횟수 추적 가능
- 악의적 대량 update가 제한됨
- 계정 또는 session 삭제 후 관련 데이터 제거 확인
- staging에서 최소 3명 동시 편집 soak test 통과

## 6. 우선순위

| 우선순위 | 항목 | 이유 |
| --- | --- | --- |
| P0 | schema, stable ID, import/export 계약 | 이후 모든 데이터의 호환성과 무결성 기반 |
| P0 | 인증, 권한, Security Rules | 공유 링크가 문서 유출 경로가 되지 않도록 선행 필요 |
| P0 | 텍스트 CRDT 수렴 | 공동 편집의 핵심 품질 |
| P1 | Studio 공유 UI와 상태 표시 | 실제 사용 흐름 완성 |
| P1 | snapshot, compaction, 재접속 | 장시간 세션 안정성 |
| P1 | 파일 export | 사용자 결과물 회수 |
| P2 | presence와 원격 cursor | 협업 인지성 개선 |
| P2 | 댓글, 제안 모드, 변경 추적 | MVP 이후 확장 |

## 7. 테스트 전략

### Rust unit/integration

- stable ID 결정성 및 충돌 위험 계약
- manifest import와 JSON round-trip
- editable/readonly 경계
- document 역적용과 재직렬화

### TypeScript unit

- Rust schema parser
- local edit ↔ CRDT transaction 변환
- duplicate/out-of-order update 처리
- 권한별 UI 상태

### Firebase emulator

- Auth와 Firestore Security Rules
- share-link 만료·폐기
- owner/editor/viewer 접근 행렬
- session 삭제 cascade

### E2E

- 브라우저 두 개의 동시 입력
- 같은 문단, 다른 문단, 표 셀 동시 편집
- 네트워크 단절과 재접속
- 권한 변경 중 편집
- 공동 편집 결과 export와 재열기

### 회귀

- 기존 HWP/HWPX/HWP3 parsing, rendering, saving 테스트를 유지한다.
- collaboration feature가 비활성화된 기본 Studio 경로는 Firebase를 요구하지 않아야 한다.

## 8. 주요 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| stable ID가 문서 구조 변경 후 달라짐 | 원격 상태 mapping 실패 | 한 source generation 안에서만 ID 유효, export 시 명시적 mapping 검증 |
| Firestore last-write-wins 사용 | 동시 입력 손실 | 텍스트 CRDT 채택 |
| update 문서 무한 증가 | 비용·재접속 지연 | snapshot과 compaction, TTL 정리 |
| Security Rules 누락 | 문서 유출·권한 상승 | emulator rules test와 deny-by-default |
| 원격 update와 Studio undo 충돌 | 예측 불가능한 undo | local transaction만 local undo stack에 포함하는 정책 |
| 지원하지 않는 객체 손상 | 원본 문서 훼손 | readonly manifest와 export allowlist |
| reflow/pagination 차이 | 저장 후 레이아웃 변화 | export 후 재조판 및 시각 회귀 검증 |
| Firebase 종속성 확산 | 테스트·배포 복잡도 증가 | repository/adapter 경계와 emulator 우선 테스트 |

## 9. 완료 정의

MVP는 다음 조건을 모두 만족할 때 완료로 본다.

- 소유자가 문서를 열고 공유 링크를 생성할 수 있다.
- 권한 있는 두 사용자가 같은 문서의 문단과 표 셀 텍스트를 동시에 편집할 수 있다.
- 같은 텍스트 노드의 동시 입력이 데이터 손실 없이 수렴한다.
- 비지원 객체와 표 구조는 읽기 전용으로 유지된다.
- 연결 단절 후 재접속해 동일 상태로 복구된다.
- 공동 편집 결과를 HWP 또는 HWPX로 저장하고 다시 열 수 있다.
- Security Rules 테스트와 핵심 E2E가 통과한다.
- collaboration 기능을 사용하지 않는 기존 rhwp 흐름에 회귀가 없다.

## 10. 권장 실행 순서

1. Phase 0 계약 확정
2. Phase 1 Rust manifest 보강
3. Phase 2 WASM/TypeScript 브리지
4. Phase 3 Firebase 인증·세션·권한
5. Phase 4 CRDT 동기화
6. Phase 5 공유 UI
7. Phase 6 파일 역적용·내보내기
8. Phase 7 운영 안정화

각 Phase는 독립적으로 테스트 가능한 산출물을 만들고, 다음 Phase로 넘어가기 전에 해당 검증 기준을 충족해야 한다.
