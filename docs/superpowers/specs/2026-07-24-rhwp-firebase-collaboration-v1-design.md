# rhwp Firebase 실시간 공동 편집 1차 버전 설계

- 상태: 승인됨
- 승인일: 2026-07-24
- 기준 저장소: `WBmaker2/rhwp`
- 기준 브랜치: `devel`
- 작업 브랜치: `feat/firebase-collaboration-mvp-v1`
- upstream 기준 커밋: `204c56528c537295dcfbfc126d47d82c3cb25334`

## 1. 목표

rhwp를 기반으로 대용량 HWP 문서를 업로드하고, Google 로그인 사용자 최대 10명이 본문과 표 셀 텍스트를 실시간으로 공동 편집하며, 이미지를 삽입하고 접속자 및 원격 커서를 확인한 뒤 HWPX로 내보낼 수 있는 1차 버전을 구현한다.

1차 버전의 핵심은 HWP 파일 자체를 실시간 상태로 사용하지 않고, 서버에서 한 번 파싱한 문서 IR을 안정적인 식별자를 가진 협업 모델로 변환한 뒤 Yjs를 통해 동기화하는 것이다.

## 2. 범위

### 2.1 포함 기능

- 100~200MB HWP resumable upload
- 서버에서 문서 한 번 파싱
- Firebase Google 로그인
- 문서 소유자·편집자·열람자 권한
- 고유 사용자 최대 10명 접속
- 본문 텍스트 실시간 공동 편집
- 표 셀 내부 텍스트 실시간 공동 편집
- PNG·JPEG·WebP 이미지 삽입
- 접속자 목록과 원격 커서 표시
- Yjs 상태 스냅샷 저장 및 서버 재시작 복구
- 공동 편집 결과 HWPX 내보내기
- 복잡한 개체의 읽기 전용 보존

### 2.2 제외 기능

- HWP 형식 재내보내기
- 표 행·열 추가·삭제
- 셀 병합·나누기
- 이미지 고급 배치 및 텍스트 감싸기 편집
- 차트·수식·도형·OLE·글상자 공동 편집
- 댓글·제안 모드
- 상세 버전 이력 UI
- 완전한 오프라인 편집
- 모바일 최적화
- 10명 초과 확장
- 한컴오피스와 픽셀 단위 완전 동일성 보장

## 3. 선택한 접근 방식

협업 앱과 rhwp 협업 어댑터를 분리한다.

- `rhwp-studio`: 문서 편집 UI와 렌더링
- `RhwpYjsAdapter`: rhwp 편집 명령과 Yjs 변경 간 변환
- Firebase Authentication: Google 로그인
- Firestore: 문서 메타데이터, ACL, 공유 링크, 작업 상태
- Cloud Storage: 원본 HWP, 추출 자산, 사용자 삽입 이미지, Yjs 스냅샷, HWPX 결과
- Cloud Run document API: 업로드 완료 처리, HWP 파싱, 협업 모델 초기화, HWPX 내보내기
- Cloud Run collaboration server: Hocuspocus WebSocket, Firebase ID token 검증, 최대 인원 제한, Yjs 영속화

이 구조는 기존 rhwp 문서 엔진의 책임을 유지하면서 협업 기능을 명시적인 경계로 추가하고, Firebase 서비스와 편집기 코어의 결합을 최소화한다.

## 4. 전체 아키텍처

```text
사용자 브라우저
├─ Firebase Google 로그인
├─ rhwp-studio 편집기
├─ Yjs 협업 문서
├─ Awareness 접속자·커서
└─ Cloud Storage 직접 업로드
             │
             ▼
Firebase
├─ Authentication
├─ Firestore
│  ├─ 문서 메타데이터
│  ├─ 사용자 권한
│  ├─ 공유 링크
│  └─ 파싱·내보내기 상태
└─ Cloud Storage
   ├─ 원본 HWP
   ├─ 파싱 결과 및 추출 자산
   ├─ 사용자 삽입 이미지
   ├─ Yjs 스냅샷
   └─ 생성된 HWPX
             │
             ▼
Cloud Run
├─ Document API
│  ├─ 업로드 완료 처리
│  ├─ HWP 1회 파싱
│  ├─ 협업 모델 초기화
│  └─ HWPX 내보내기
└─ Collaboration Server
   ├─ Firebase 토큰 검증
   ├─ ACL 및 최대 10명 검사
   ├─ Yjs WebSocket 동기화
   ├─ Awareness 전달
   └─ 스냅샷 영속화
```

## 5. 저장소 변경 구조

```text
rhwp/
├─ rhwp-studio/
│  └─ src/
│     └─ collaboration/
│        ├─ CollaborationController.ts
│        ├─ RhwpYjsAdapter.ts
│        ├─ PresenceController.ts
│        ├─ FirebaseAuthProvider.ts
│        ├─ AssetUploader.ts
│        └─ types.ts
├─ crates/
│  └─ rhwp-collaboration/
│     ├─ src/
│     │  ├─ model.rs
│     │  ├─ import.rs
│     │  ├─ export.rs
│     │  ├─ stable_id.rs
│     │  └─ operations.rs
│     └─ tests/
├─ services/
│  ├─ document-api/
│  └─ collaboration-server/
└─ firebase/
   ├─ firestore.rules
   ├─ storage.rules
   ├─ firestore.indexes.json
   └─ firebase.json
```

구현 중 실제 저장소 구조와 책임 경계를 다시 확인해 파일 위치를 조정할 수 있으나, 협업 어댑터·서버·Firebase 설정의 모듈 경계는 유지한다.

## 6. 문서 처리 흐름

```text
원본 HWP
  → Cloud Storage 업로드
  → 서버에서 1회 파싱
  → rhwp Document IR 생성
  → 안정적 ID 부여
  → Yjs 협업 모델 초기화
  → 실시간 공동 편집
  → 최신 스냅샷 고정
  → Document IR에 변경 반영
  → HWPX serializer 실행
  → Cloud Storage에 결과 저장
```

브라우저가 100~200MB 원본 파일을 사용자마다 반복 파싱하지 않는다. 원본은 서버 처리의 기준 자료이고, 실시간 편집 상태는 별도 협업 모델과 스냅샷으로 관리한다.

## 7. 안정적 식별자

인덱스 기반 위치인 `sectionIndex / paragraphIndex / charOffset`만으로는 동시 편집 중 대상이 쉽게 바뀐다. 협업 대상에 다음 ID를 부여한다.

- `sectionId`
- `blockId`
- `paragraphId`
- `textRunId`
- `tableId`
- `rowId`
- `cellId`
- `imageId`
- `readonlyObjectId`

인덱스는 표시와 탐색을 위한 파생 값으로만 사용한다. ID는 최초 파싱 시 결정적으로 생성하고, 같은 원본과 같은 파서 버전에서 재현 가능해야 한다.

## 8. Yjs 모델

대용량 문서 전체를 단일 문자열이나 단일 거대 객체에 저장하지 않는다. 섹션과 블록 단위로 구조를 나누고 텍스트 편집 대상만 `Y.Text`로 관리한다.

```text
Y.Doc
├─ metadata: Y.Map
├─ sections: Y.Array<sectionId>
├─ section:{sectionId}: Y.Map
│  ├─ blocks: Y.Array<blockId>
│  └─ readonlyObjects: Y.Array<objectId>
├─ paragraph:{paragraphId}: Y.Map
│  ├─ text: Y.Text
│  ├─ styleRef
│  └─ revision
├─ table:{tableId}: Y.Map
│  ├─ rowIds: Y.Array
│  └─ properties
├─ cell:{cellId}: Y.Map
│  ├─ text: Y.Text
│  ├─ styleRef
│  └─ readonlyStructure: true
└─ image:{imageId}: Y.Map
   ├─ assetPath
   ├─ width
   ├─ height
   ├─ anchorParagraphId
   └─ placement
```

문서가 큰 경우 섹션별 subdocument 또는 논리적 분할을 적용해 초기 로드와 메모리 사용량을 제한한다. 단일 `Y.Doc` 사용 여부는 성능 검증 결과에 따라 결정하되, 외부 API는 섹션 단위 로딩을 허용하도록 설계한다.

## 9. 편집 동기화

### 9.1 로컬 변경

```text
사용자 입력
→ rhwp 편집 명령
→ RhwpYjsAdapter
→ Y.Text 또는 Y.Map 변경
→ WebSocket 전송
```

### 9.2 원격 변경

```text
Yjs 원격 변경
→ RhwpYjsAdapter
→ rhwp 원격 편집 명령
→ 영향 문단·셀만 재조판
→ 화면 갱신
```

원격 변경을 적용할 때 transaction origin을 사용해 같은 변경이 다시 Yjs에 기록되는 순환 업데이트를 차단한다.

### 9.3 Undo/Redo

기존 로컬 편집 히스토리를 그대로 공유 히스토리로 사용하지 않는다. 협업 세션에서는 사용자별 `Y.UndoManager`를 적용하고, 원격 사용자의 변경은 자신의 Undo 대상에 포함하지 않는다. 기존 rhwp Undo 동작과 충돌하는 영역은 협업 모드에서 명시적으로 분리한다.

## 10. 본문 및 표 편집

### 10.1 본문

- 문단 텍스트를 `Y.Text`로 관리한다.
- 변경은 안정적 `paragraphId`를 기준으로 적용한다.
- 원격 변경 시 문서 전체가 아니라 영향 문단과 연관 레이아웃만 갱신한다.
- 스타일 공동 편집은 1차 범위에서 제한하며, 기존 스타일 참조를 보존한다.

### 10.2 표

- 각 셀 텍스트를 독립된 `Y.Text`로 관리한다.
- 같은 셀의 동시 입력은 Yjs가 병합한다.
- 서로 다른 셀 편집은 독립적으로 처리한다.
- 행·열·셀 병합 구조는 읽기 전용이다.
- 구조 변경 명령은 UI와 명령 계층에서 모두 차단한다.

## 11. 이미지 삽입

이미지 바이너리나 Base64를 Yjs 문서에 저장하지 않는다.

```text
이미지 선택
→ 클라이언트 검증
→ Cloud Storage 직접 업로드
→ assetPath 및 메타데이터 생성
→ Yjs에 이미지 참조 추가
→ 다른 사용자 지연 로딩
```

- 지원 형식: PNG, JPEG, WebP
- 파일당 최대 크기: 20MB
- 저장 경로: `documents/{documentId}/assets/user/{imageId}/{filename}`
- 이미지 업로드가 성공한 뒤에만 Yjs 이미지 노드를 생성한다.
- 1차 버전은 기본 크기와 문단 앵커만 편집한다.

## 12. 인증 및 권한

Firebase Google 로그인을 사용한다.

1. 브라우저가 Firebase ID token을 발급받는다.
2. REST API와 WebSocket 연결 시 토큰을 전달한다.
3. Cloud Run이 Firebase Admin SDK로 토큰을 검증한다.
4. Firestore 문서 멤버십과 역할을 확인한다.
5. 권한이 확인된 요청만 실행한다.

역할:

- `owner`: 문서 관리, 멤버 관리, 편집, 내보내기
- `editor`: 편집, 이미지 삽입, 내보내기
- `viewer`: 열람과 접속자 확인만 가능

클라이언트가 전달한 `userId`, `role`, `documentId`를 신뢰하지 않고 서버에서 검증한다.

## 13. 최대 10명 제한

- 고유 사용자 수를 기준으로 계산한다.
- 같은 사용자가 여러 탭을 열어도 한 명으로 센다.
- WebSocket 연결 승인 단계에서 검사한다.
- 11번째 고유 사용자는 편집 세션 연결을 거절한다.
- 기존 접속자의 연결 종료와 heartbeat 만료를 반영한다.

## 14. 접속자와 원격 커서

Yjs Awareness로 다음 상태를 공유한다.

- `userId`
- `displayName`
- `photoURL`
- `colorIndex`
- `activeParagraphId` 또는 `cellId`
- `anchorOffset`
- `headOffset`
- `lastActiveAt`

사용자 색상은 10개 팔레트에서 `userId` 해시로 결정한다. Awareness는 영속 문서 데이터가 아니므로 스냅샷에 저장하지 않는다.

## 15. 업로드 및 파싱

### 15.1 업로드

브라우저가 Cloud Storage resumable upload를 사용한다.

원본 경로:

`documents/{documentId}/source/original.hwp`

UI는 업로드 비율, 전송량, 재개, 재시도, 취소를 제공한다.

### 15.2 문서 상태

- `uploading`
- `uploaded`
- `parsing`
- `ready`
- `failed`
- `exporting`

같은 문서에 대한 파싱 요청이 중복되어도 한 작업만 실행되도록 Firestore 트랜잭션 또는 원자적 작업 잠금을 사용한다.

### 15.3 파싱 산출물

- `documents/{documentId}/derived/manifest.json`
- `documents/{documentId}/derived/sections/*`
- `documents/{documentId}/assets/imported/*`
- `documents/{documentId}/collaboration/snapshots/*`

파싱 작업은 제한된 컨테이너에서 실행하며 파일 헤더, 압축 해제 크기, 이미지 수, 섹션 수, 실행 시간과 메모리 상한을 검증한다.

## 16. HWPX 내보내기

1. 최신 Yjs 변경을 서버에 flush한다.
2. 일관된 스냅샷을 고정한다.
3. 최초 파싱된 Document IR을 불러온다.
4. 본문과 표 셀 텍스트를 반영한다.
5. 사용자 삽입 이미지를 반영한다.
6. 읽기 전용 개체는 최초 상태를 유지한다.
7. rhwp HWPX serializer를 실행한다.
8. 결과를 Storage에 저장한다.
9. 권한 확인 후 다운로드 경로를 반환한다.

결과 경로:

`documents/{documentId}/exports/{exportId}.hwpx`

내보낸 HWPX는 rhwp로 다시 파싱해 본문, 표 셀, 이미지 참조와 읽기 전용 개체 보존 여부를 검증한다.

## 17. Firestore 데이터 모델

```text
documents/{documentId}
  ownerId
  title
  sourceFilename
  sourceSize
  sourceStoragePath
  status
  parserVersion
  createdAt
  updatedAt
  latestSnapshotPath
  latestExportPath
  maxParticipants: 10

documents/{documentId}/members/{userId}
  role
  invitedBy
  createdAt

documents/{documentId}/exports/{exportId}
  status
  storagePath
  requestedBy
  createdAt
  completedAt

shareLinks/{shareId}
  documentId
  role
  enabled
  expiresAt
  createdBy
```

1차 버전의 기본 공유 정책은 Google 로그인 사용자에게만 권한을 부여하는 것이다. 링크 자체는 권한을 완성하지 않으며, 로그인과 서버 ACL 검증을 통과해야 한다.

## 18. 스냅샷과 복구

Yjs 변경을 입력마다 Storage에 저장하지 않는다.

스냅샷 조건:

- 변경 후 debounce 시간이 지나면 저장
- 누적 업데이트 크기가 임계값을 넘으면 저장
- 마지막 사용자가 나갈 때 저장
- HWPX 내보내기 직전 저장
- 서버 종료 신호 처리 시 가능한 범위에서 저장

경로:

`documents/{documentId}/collaboration/snapshots/{timestamp}.bin`

복구 순서:

1. 최신 완전 스냅샷 로드
2. 후속 업데이트가 있으면 적용
3. 검증 실패 시 직전 정상 스냅샷으로 fallback
4. 복구 결과를 새 스냅샷으로 저장

## 19. 복잡한 개체 읽기 전용 정책

다음 개체는 1차 버전에서 표시와 내보내기 보존만 지원한다.

- 차트
- 수식
- 도형
- 글상자
- OLE 개체
- 머리말·꼬리말
- 각주·미주
- 복잡한 이미지 배치
- 표 구조

UI에서는 읽기 전용 배지와 설명을 표시한다. 편집 명령 계층에서도 해당 개체에 대한 변경을 거절해 우회 변경을 방지한다.

## 20. 오류 처리

| 상황 | 처리 |
|---|---|
| 업로드 중 연결 단절 | resumable upload 재개 |
| 파싱 실패 | 원본 보존, 오류 코드 기록, 재시도 허용 |
| WebSocket 단절 | 지수 백오프 재접속 및 Yjs 재동기화 |
| 11번째 사용자 접속 | 세션 연결 거절 및 안내 |
| 권한 제거 | 다음 API 요청 및 재연결 시 차단 |
| 이미지 업로드 실패 | Yjs 이미지 노드 생성하지 않음 |
| 내보내기 실패 | 원본과 최신 스냅샷 보존 |
| 복잡한 개체 편집 시도 | 명령 거절 및 읽기 전용 안내 |
| 서버 재시작 | 최신 정상 스냅샷에서 복구 |

## 21. 보안 원칙

- Firebase 클라이언트 설정 외의 비밀값을 저장소에 커밋하지 않는다.
- 서비스 계정 키 JSON을 저장소에 넣지 않는다.
- Cloud Run 서비스 계정에 최소 권한을 부여한다.
- Storage 파일을 공개 버킷으로 제공하지 않는다.
- API와 WebSocket 모두 Firebase token과 ACL을 검증한다.
- 파일 확장자가 아니라 실제 형식과 헤더를 확인한다.
- 압축 폭탄과 비정상 문서에 대한 리소스 제한을 적용한다.
- 문서와 자산 경로는 사용자 입력 문자열로 직접 조합하지 않는다.
- 로그에 token, 원문 내용, 서명 URL을 남기지 않는다.

## 22. 테스트 전략

### 22.1 단위 테스트

- 안정적 ID 생성의 결정성
- Document IR → 협업 모델 변환
- 협업 모델 → Document IR 반영
- 본문 삽입·삭제·동시 변경
- 표 셀 삽입·삭제·동시 변경
- 읽기 전용 명령 차단
- 이미지 메타데이터 검증
- owner/editor/viewer 권한 판정
- 고유 사용자 10명 제한
- transaction origin 순환 방지

### 22.2 통합 테스트

- 두 클라이언트 본문 동시 편집
- 같은 셀 동시 편집
- 서로 다른 셀 동시 편집
- 이미지 삽입 후 다른 클라이언트 표시
- WebSocket 재접속 및 상태 수렴
- 스냅샷 저장과 서버 재시작 복구
- viewer 쓰기 차단
- 11번째 사용자 차단
- 편집 결과 HWPX 내보내기와 재파싱

### 22.3 E2E 테스트

1. 테스트 인증으로 세 브라우저 세션 접속
2. HWP 업로드
3. 서버 파싱 완료 확인
4. 세 사용자가 서로 다른 문단 편집
5. 두 사용자가 같은 표 셀 편집
6. 이미지 삽입
7. 접속자와 원격 커서 표시
8. 네트워크 단절과 재접속
9. HWPX 내보내기
10. 결과 HWPX 재파싱 및 보존 검증

실제 100~200MB 파일은 일반 CI에 직접 포함하지 않는다. 생성형 대용량 fixture와 별도 수동 검증 프로필을 병행한다.

## 23. 완료 기준

다음 조건을 모두 만족해야 1차 버전을 완료로 판정한다.

- 100~200MB HWP resumable upload 성공
- 동일 문서의 서버 파싱이 한 번만 수행됨
- Google 로그인 및 서버 ACL 검증
- 고유 사용자 최대 10명 제한
- 본문 텍스트 실시간 수렴
- 표 셀 텍스트 실시간 수렴
- PNG/JPEG/WebP 이미지 삽입 및 동기화
- 접속자 목록과 원격 커서 표시
- 서버 재시작 후 최신 정상 상태 복구
- 공동 편집 결과 HWPX 내보내기
- 복잡한 개체의 읽기 전용 보존
- 내보낸 HWPX의 재파싱 검증 통과
- 기존 rhwp 빌드와 핵심 편집 테스트 회귀 없음

## 24. 구현 원칙

- 기능 구현은 TDD로 진행한다.
- 협업 코어를 먼저 검증하고 UI를 연결한다.
- 각 단계는 작은 커밋으로 분리한다.
- Firebase 실제 배포와 외부 리소스 변경은 사용자 승인 없이 수행하지 않는다.
- 원본 upstream으로 PR을 열지 않고 우선 `WBmaker2/rhwp` 포크에서 완성한다.
- 검증되지 않은 상태를 완료로 보고하지 않는다.
