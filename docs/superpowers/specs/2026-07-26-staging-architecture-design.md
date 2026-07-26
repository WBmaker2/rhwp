# rhwp Collaboration Staging Architecture Design

- 상태: staging 배포 전 설계 기준안
- 작성일: 2026-07-26
- 대상 저장소: `WBmaker2/rhwp`
- 작업 브랜치: `feat/firebase-collaboration-mvp-v1`
- 대상 PR: Draft PR `#1`
- 적용 시점: 사용자의 명시적 승인 이후
- 이 문서 작성으로 생성되는 클라우드 리소스: 없음

## 1. 목적

이 문서는 이미 구현된 rhwp Firebase 실시간 공동 편집 MVP를 실제 staging 환경에 배치하기 전에 필요한 리소스, 데이터 흐름, 보안 경계, IAM 원칙, 런타임 설정, 비용 안전장치와 검증 기준을 확정한다.

이번 단계는 설계와 운영 절차만 문서화한다. 다음 작업은 이 설계를 machine-readable manifest로 옮기고, 실제 리소스를 변경하지 않는 read-only preflight validator를 구현하는 것이다. Firebase 또는 Google Cloud 리소스 생성, IAM 변경, Secret 생성, Cloud Run 배포, Firebase 배포는 별도의 명시적 승인 없이는 수행하지 않는다.

## 2. 설계 원칙

1. **staging과 production을 프로젝트 수준에서 분리한다.** staging 명령에는 승인된 staging project ID를 명시하며 기본 CLI project에 의존하지 않는다.
2. **리전은 `asia-northeast3`을 기본값으로 사용한다.** Cloud Run, Cloud Tasks, Cloud Firestore와 Cloud Storage가 모두 지원하는 서울 리전이다. 실제 생성 전에 비용, 데이터 위치와 조직 정책을 다시 확인한다.
3. **서비스 계정 키 파일을 만들지 않는다.** Cloud Run service identity, Cloud Tasks OIDC와 사용자 또는 CI의 단기 인증을 사용한다.
4. **런타임 권한은 최소 권한으로 분리한다.** Collaboration server, Document API, Document worker와 Cloud Tasks caller는 서로 다른 서비스 계정을 사용한다.
5. **이미지는 digest로 고정한다.** Cloud Run template의 `${IMAGE}@sha256:${DIGEST}` 계약을 유지하고 mutable tag만으로 배포하지 않는다.
6. **비밀 값은 Secret Manager에서만 주입한다.** 저장소, workflow input, shell history와 로그에 secret 원문을 기록하지 않는다.
7. **Cloud Tasks worker는 비공개로 유지한다.** browser 또는 일반 사용자가 worker endpoint를 직접 호출할 수 없어야 한다.
8. **비용 알림은 안전장치이지 지출 상한이 아니다.** 예산 알림은 사용을 자동으로 중단하지 않으므로 운영자가 별도로 조치해야 한다.
9. **배포는 단계별 검증 후 진행한다.** 한 단계가 실패하면 다음 단계로 자동 진행하지 않는다.
10. **현재 구현과 향후 보강을 구분한다.** 코드가 실제로 보장하지 않는 보안 속성을 문서에서 완료된 것으로 주장하지 않는다.

## 3. 범위

### 3.1 포함

- staging Firebase/GCP 프로젝트 구조
- Firebase Authentication, Firestore, Cloud Storage, Hosting 구성 경계
- Artifact Registry와 Cloud Run 서비스 3개
- Cloud Tasks queue 2개
- 전용 service account 4개
- Secret Manager secret 1개
- IAM 책임 매트릭스
- 런타임, scaling, timeout과 ingress 계약
- 로그, 모니터링, 비용 알림 원칙
- 배포 전·후 acceptance criteria
- 다음 machine-readable manifest의 필수 인터페이스

### 3.2 제외

- 실제 staging project 생성 또는 선택
- billing account 연결
- Firebase 초기화
- API 활성화
- service account, IAM binding, Secret, queue 또는 budget 생성
- container build 또는 push
- Cloud Run, Firebase Hosting, Rules 또는 Index 배포
- machine-readable manifest 파일 생성
- read-only preflight validator 구현
- staging acceptance test 실행
- PR Draft 해제 또는 merge

## 4. 전체 topology

```text
사용자 브라우저
├─ Firebase Hosting: rhwp-studio 정적 자산
├─ Firebase Authentication: Google 로그인
├─ Firestore: 문서 metadata, membership, share link, worker state
├─ Cloud Storage: source HWP, manifest, image, snapshot, export HWPX
├─ HTTPS → rhwp-document-api-staging
└─ WSS   → rhwp-collaboration-staging
                  │
                  ├─ Firebase Admin Auth 검증
                  ├─ Firestore membership ACL
                  ├─ Storage snapshot read/write/delete
                  └─ internal flush endpoint

rhwp-document-api-staging
├─ Firebase Admin Auth 검증
├─ Firestore membership, parse lease, share link
├─ Storage source metadata 조회
├─ Cloud Tasks parse queue enqueue
├─ Cloud Tasks export queue enqueue
└─ HTTPS → collaboration internal flush

Cloud Tasks
├─ rhwp-parse-staging
└─ rhwp-export-staging
         │
         └─ OIDC → 비공개 rhwp-document-worker-staging

rhwp-document-worker-staging
├─ native rhwp-collaboration-worker 실행
├─ Firestore parse/export task state
└─ Storage source download, manifest/export upload
```

## 5. 주요 요청 흐름

### 5.1 로그인과 문서 접근

1. 브라우저가 Firebase Google sign-in을 수행한다.
2. 브라우저는 Firebase ID token을 Document API와 Collaboration server에 전달한다.
3. 각 서비스가 Firebase Admin SDK로 token을 검증한다.
4. 서비스가 Firestore의 `documents/{documentId}/members/{uid}` 역할을 확인한다.
5. `owner`, `editor`, `viewer`에 맞는 작업만 허용한다.

Firebase Web API key, project ID, auth domain, app ID와 Storage bucket 식별자는 공개 web configuration이다. 서비스 계정 credential이나 내부 token이 아니며, 실제 권한은 Authentication, Security Rules와 서버 ACL이 결정한다.

### 5.2 원본 업로드와 parse

1. owner가 canonical Storage path에 HWP를 직접 업로드한다.
2. Storage Rules가 MIME type과 `0 < 파일 크기 ≤ 200 MiB`를 검증한다.
3. 브라우저가 Document API의 upload-complete route를 호출한다.
4. Document API가 Storage metadata와 source generation을 확인한다.
5. Firestore transaction으로 동일 generation의 중복 enqueue를 차단한다.
6. Document API가 `rhwp-parse-staging` queue에 OIDC HTTP task를 생성한다.
7. Cloud Tasks가 비공개 Document worker `/run/parse` endpoint를 호출한다.
8. worker가 source를 내려받아 native worker로 parse하고 manifest를 Storage에 저장한다.
9. worker가 Firestore document state를 `ready`로 갱신한다.

### 5.3 실시간 공동 편집

1. 브라우저가 WSS로 Collaboration server에 연결한다.
2. 서버가 Firebase ID token과 document ACL을 검증한다.
3. Hocuspocus/Yjs가 본문과 표 셀 변경을 동기화한다.
4. snapshot은 Storage에 저장하고 Firestore에 pointer와 metadata를 기록한다.
5. snapshot은 Firebase Storage Rules에서 client 직접 read/write를 차단한다.
6. Cloud Run WebSocket 요청에는 service request timeout이 적용되므로 `3600`초 뒤 연결 종료에 대비해 client reconnect와 state convergence를 검증한다.

### 5.4 HWPX export

1. owner 또는 editor가 Document API export route를 호출한다.
2. Document API가 Collaboration server의 internal flush endpoint를 호출해 최신 snapshot을 고정한다.
3. Document API가 `rhwp-export-staging` queue에 OIDC task를 생성한다.
4. worker가 source, collaboration manifest와 snapshot을 읽는다.
5. native worker가 변경 내용을 적용해 HWPX를 만든다.
6. 결과를 Storage에 업로드하고 Firestore export metadata를 `ready`로 갱신한다.

## 6. 리소스 inventory와 naming contract

| 범주 | 기준 이름 또는 값 | 상태 |
|---|---|---|
| GCP/Firebase project | `${FIREBASE_STAGING_PROJECT_ID}` | 승인 입력 |
| 기본 region | `asia-northeast3` | 권장 기준, 생성 전 승인 |
| Firebase Web App | project 내부 staging web app | 생성 전 승인 |
| Firestore | `(default)`, regional `asia-northeast3` | 생성 전 승인 |
| Cloud Storage bucket | `${FIREBASE_STAGING_PROJECT_ID}.appspot.com` 또는 Firebase가 반환한 실제 기본 bucket 이름 | 생성 후 실제 값 고정 |
| Firebase Hosting site | staging project 기본 site | 생성 전 승인 |
| Artifact Registry repository | `rhwp-staging` | 권장 기준 |
| Collaboration service | `rhwp-collaboration-staging` | 기존 template 계약 |
| Document API service | `rhwp-document-api-staging` | 기존 template 계약 |
| Document worker service | `rhwp-document-worker-staging` | 기존 template 계약 |
| Parse queue | `rhwp-parse-staging` | 기존 environment 계약 |
| Export queue | `rhwp-export-staging` | 기존 environment 계약 |
| Collaboration service account | `rhwp-collaboration-staging@${PROJECT_ID}.iam.gserviceaccount.com` | 권장 기준 |
| Document API service account | `rhwp-document-api-staging@${PROJECT_ID}.iam.gserviceaccount.com` | 권장 기준 |
| Document worker service account | `rhwp-document-worker-staging@${PROJECT_ID}.iam.gserviceaccount.com` | 권장 기준 |
| Cloud Tasks caller account | `rhwp-tasks-staging@${PROJECT_ID}.iam.gserviceaccount.com` | 기존 environment 계약 |
| Internal token secret | `rhwp-collaboration-internal-token-staging` | 기존 template 계약 |
| Monthly budget amount | `${STAGING_MONTHLY_BUDGET_KRW}` | 필수 승인 입력, 원화 |
| Budget thresholds | `50%`, `80%`, `100%` actual spend | 권장 초기값 |
| Notification channel | `${STAGING_BUDGET_NOTIFICATION_CHANNEL}` | 필수 승인 입력 |
| Data retention | `${STAGING_DATA_RETENTION_DAYS}` | 필수 승인 입력 |

Firebase가 새 프로젝트에서 반환하는 Storage bucket 이름이 `.appspot.com` 형식과 다를 수 있으므로, 생성 후 실제 bucket 이름을 manifest에 기록하고 추측하지 않는다.

## 7. Cloud Run runtime contract

| 서비스 | ingress | 공개 호출 | concurrency | timeout | CPU | memory | minScale | maxScale |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Collaboration | `all` | browser WSS와 health route 때문에 필요 | 80 | 3600s | 1 | 1Gi | 0 | 10 |
| Document API | `all` | browser HTTPS 때문에 필요 | 80 | 300s | 1 | 512Mi | 0 | 20 |
| Document worker | `internal` | 금지 | 1 | 900s | 2 | 2Gi | 0 | 10 |

### 7.1 WebSocket 제한

Cloud Run WebSocket stream은 HTTP request로 처리되며 service timeout을 넘으면 연결이 닫힌다. 현재 `3600`초는 Cloud Run service 최대 timeout과 일치한다. 이는 무제한 연결을 뜻하지 않는다. Studio client는 연결 종료 후 다시 인증하고 sync하여 state convergence를 회복해야 한다.

열린 WebSocket이 있는 instance는 active로 간주될 수 있으므로 staging 사용자가 없어도 연결이 유지되는 동안 비용이 발생할 수 있다. acceptance test 후 불필요한 브라우저 세션을 종료한다.

## 8. Cloud Tasks 초기 staging profile

다음 값은 비용과 동시 메모리 사용을 제한하기 위한 권장 초기값이다. 실제 queue 생성 전 승인 패킷에 포함한다.

| 설정 | parse queue | export queue | 근거 |
|---|---:|---:|---|
| max concurrent dispatches | 1 | 1 | 200 MiB 문서 처리와 worker concurrency 1 |
| max dispatches per second | 1 | 1 | burst 억제 |
| max attempts | 5 | 5 | transient failure 재시도 |
| min backoff | 10s | 10s | 즉시 반복 실패 방지 |
| max backoff | 300s | 300s | bounded recovery |
| max doublings | 5 | 5 | 점진적 backoff |
| dispatch deadline | 900s | 900s | worker timeout과 정합 |

Cloud Tasks OIDC service account는 queue와 같은 project에 속해야 하며, worker service에 `roles/run.invoker`가 필요하다. task를 생성하는 Document API identity에는 queue의 `roles/cloudtasks.enqueuer`와 OIDC service account를 사용할 수 있는 `iam.serviceAccounts.actAs` 권한이 필요하다.

## 9. 데이터와 신뢰 경계

### 9.1 Browser 경계

- Firebase Hosting, Document API와 Collaboration server는 인터넷에서 도달 가능하다.
- 공개 도달 가능과 무인증 application access는 같은 의미가 아니다.
- Document API와 Collaboration WebSocket은 Firebase ID token과 Firestore ACL을 application layer에서 검증한다.
- Firestore와 Storage client access는 Firebase Security Rules를 추가로 적용한다.

### 9.2 Worker 경계

- Document worker는 `internal` ingress를 유지한다.
- `allUsers`에 Cloud Run Invoker를 부여하지 않는다.
- Cloud Tasks caller service account만 worker에 `roles/run.invoker`를 가진다.
- task 요청은 HTTPS와 OIDC ID token을 사용한다.
- `ALLOW_EMULATOR_TASKS=false`를 유지한다.

### 9.3 Collaboration internal flush 경계와 현재 제한

현재 Document API client는 Collaboration service audience로 identity token을 발급해 `Authorization: Bearer ...` header를 보내고, 별도로 `x-rhwp-internal-token`을 보낸다. 그러나 Collaboration server의 현재 internal handler가 직접 검증하는 값은 `x-rhwp-internal-token`뿐이다.

또한 같은 Collaboration Cloud Run service가 browser WSS를 받아야 하므로 service 전체를 private IAM invocation으로 전환하면 browser가 연결할 수 없다. Cloud Run의 service-level public/private IAM 설정만으로 동일 service의 특정 path만 별도 private 처리할 수 있다고 가정하지 않는다.

따라서 현재 staging에서 실질적으로 강제되는 internal flush application 인증은 다음과 같다.

```text
HTTPS + Secret Manager에서 주입된 high-entropy internal token
```

Document API가 identity token도 보내지만 현재 public Collaboration service에서 이 token이 두 번째 강제 경계라고 주장하지 않는다.

**staging 승인 시 선택지는 다음 두 가지다.**

1. **MVP staging 한정 승인:** 현재 single service 구조를 유지하고 internal token을 실질 경계로 사용한다. token을 로그에 남기지 않고 secret-level IAM을 적용하며 staging 외 사용을 금지한다.
2. **강화 후 배포:** internal flush를 별도의 private Cloud Run service 또는 별도 private endpoint로 분리해 Cloud Run IAM과 internal token을 모두 강제한다.

본 설계의 기본 권고는 staging에서 1번을 명시적으로 승인하되, production 전에는 2번을 별도 설계·구현하는 것이다.

## 10. Secret contract

현재 필요한 application secret은 하나다.

| Secret | 사용 서비스 | 환경 변수 | 접근 범위 |
|---|---|---|---|
| `rhwp-collaboration-internal-token-staging` | Collaboration, Document API | `INTERNAL_API_TOKEN`, `COLLABORATION_INTERNAL_TOKEN` | 해당 secret에만 `roles/secretmanager.secretAccessor` |

원칙:

- 최소 32 random bytes를 base64url 또는 동등한 high-entropy 문자열로 저장한다.
- secret 원문을 repository, `.env.example`, GitHub Actions input, PR, log 또는 배포 기록에 넣지 않는다.
- Cloud Run YAML은 `secretKeyRef`만 포함한다.
- rotation 시 새 version을 만들고 두 서비스가 같은 version을 사용하도록 순차 배포한다.
- 이전 version disable은 새 revision 검증 이후 수행한다.

Firebase Web API key는 이 Secret inventory에 포함하지 않는다. 공개 client configuration이지만 Firebase Security Rules와 API restriction은 별도로 검토한다.

## 11. IAM responsibility matrix

표기:

- **필수:** 현재 코드의 실제 동작에 필요
- **불필요:** 해당 identity에 부여하지 않음
- **승인 결정:** 실제 배포 identity와 조직 정책을 확인한 뒤 결정

| Identity | Firestore | Storage | Tasks enqueue | Run invoke | OIDC account 사용 | Secret access | Artifact pull | Firebase deploy |
|---|---|---|---|---|---|---|---|---|
| release/deployer | 승인 결정 | 승인 결정 | 승인 결정 | 승인 결정 | 승인 결정 | 승인 결정 | 승인 결정 | 승인 결정 |
| Collaboration SA | `roles/datastore.user` 필수 | staging bucket `roles/storage.objectAdmin` 필수 | 불필요 | 불필요 | 불필요 | 해당 secret `roles/secretmanager.secretAccessor` 필수 | 불필요 | 불필요 |
| Document API SA | `roles/datastore.user` 필수 | staging bucket `roles/storage.objectViewer` 필수 | 두 queue `roles/cloudtasks.enqueuer` 필수 | 현재 public Collaboration 호출에는 IAM 강제 없음; private split 시 필수 | Tasks caller SA에 `roles/iam.serviceAccountUser` 필수 | 해당 secret `roles/secretmanager.secretAccessor` 필수 | 불필요 | 불필요 |
| Document worker SA | `roles/datastore.user` 필수 | staging bucket `roles/storage.objectAdmin` 필수 | 불필요 | 불필요 | 불필요 | 불필요 | 불필요 | 불필요 |
| Cloud Tasks caller SA | 불필요 | 불필요 | 불필요 | worker service `roles/run.invoker` 필수 | 자기 identity로 OIDC token 발급 | 불필요 | 불필요 | 불필요 |
| Cloud Run service agent | 불필요 | 불필요 | 불필요 | platform managed | platform managed | platform managed | repository `roles/artifactregistry.reader` 필요 여부 확인 | 불필요 |

### 11.1 Release identity 원칙

release/deployer에 `roles/owner` 또는 `roles/editor`를 편의상 부여하지 않는다. 실제 manifest 단계에서 필요한 resource admin 역할을 작업별로 나누고, service account에 대한 `roles/iam.serviceAccountUser`를 대상 account별로 제한한다. CI를 사용한다면 장기 service account key 대신 Workload Identity Federation을 우선한다.

### 11.2 Storage 역할 근거

- Collaboration server는 snapshot create, read와 delete를 수행하므로 bucket-level Object Admin이 필요하다.
- Document API는 source object metadata만 조회하므로 Object Viewer로 제한한다.
- Document worker는 source download와 manifest/export upload를 수행하므로 Object Admin이 필요하다.
- bucket 자체 설정 변경 권한인 Storage Admin은 runtime identity에 부여하지 않는다.

## 12. Firebase configuration contract

### 12.1 Authentication

- Google provider를 staging project에서만 활성화한다.
- Firebase Hosting 기본 domain과 승인된 custom domain만 authorized domain에 넣는다.
- custom domain을 사용하면 Firebase `authDomain`과 OAuth redirect URI의 `/__/auth/handler` 경로를 함께 검증한다.
- production domain을 staging allowlist에 자동 추가하지 않는다.

### 12.2 Firestore

- default database를 `asia-northeast3`에 생성하는 것을 기본안으로 한다.
- 위치는 생성 후 쉽게 변경할 수 없으므로 project ID와 region을 approval packet에서 다시 확인한다.
- server SDK는 IAM으로 접근하고 browser SDK는 Firestore Rules를 적용한다.
- document, membership, share link, snapshot pointer와 worker state의 server-managed field를 client가 수정하지 못해야 한다.

### 12.3 Cloud Storage

- staging bucket도 `asia-northeast3`에 배치한다.
- source HWP: owner create only, `0 < size ≤ 200 MiB`.
- user image: owner/editor, PNG/JPEG/WebP, 최대 20 MiB.
- snapshots: client read/write 금지.
- exports: document member read only.
- public bucket 또는 object ACL을 사용하지 않는다.

### 12.4 Hosting

- build output은 `rhwp-studio/dist`를 사용한다.
- Firebase web configuration에는 staging project 값만 주입한다.
- `VITE_COLLABORATION_URL`은 `wss://`, `VITE_DOCUMENT_API_URL`은 `https://`여야 한다.
- Hosting deploy 전에 asset build와 config provenance를 기록한다.

## 13. 환경 변수 contract

### Browser build

```text
VITE_FIREBASE_API_KEY
VITE_FIREBASE_AUTH_DOMAIN
VITE_FIREBASE_PROJECT_ID
VITE_FIREBASE_STORAGE_BUCKET
VITE_FIREBASE_APP_ID
VITE_COLLABORATION_URL
VITE_DOCUMENT_API_URL
```

### Collaboration service

```text
PORT
FIREBASE_STORAGE_BUCKET
INTERNAL_API_TOKEN <- Secret Manager
```

### Document API

```text
PORT
GCP_PROJECT_ID
GCP_LOCATION=asia-northeast3
FIREBASE_STORAGE_BUCKET
PARSE_QUEUE=rhwp-parse-staging
PARSE_WORKER_URL=https://.../run/parse
EXPORT_QUEUE=rhwp-export-staging
EXPORT_WORKER_URL=https://.../run/export
TASKS_SERVICE_ACCOUNT_EMAIL
COLLABORATION_FLUSH_URL
COLLABORATION_INTERNAL_TOKEN <- Secret Manager
DIRECT_WORKER_DISPATCH=false
```

### Document worker

```text
PORT
FIREBASE_STORAGE_BUCKET
RHWP_COLLABORATION_WORKER_BIN=/usr/local/bin/rhwp-collaboration-worker
ALLOW_EMULATOR_TASKS=false
```

## 14. Observability contract

### 14.1 로그

각 service log는 최소 다음 공통 필드를 구조화한다.

```text
service
revision
requestId 또는 taskName
documentId의 비가역 hash 또는 안전한 identifier
operation
status
latencyMs
errorClass
```

금지 로그:

```text
Firebase ID token
Authorization header
x-rhwp-internal-token
Secret Manager payload
원본 HWP 내용
사용자 개인정보가 포함된 document title
```

### 14.2 모니터링 대상

- Cloud Run 4xx, 5xx, request latency와 instance count
- Collaboration active connection과 reconnect 실패
- Cloud Tasks queue depth, oldest task age, retry count와 dead task
- worker parse/export duration와 timeout
- Firestore permission denied
- Storage permission denied와 object size validation failure
- snapshot flush failure와 fallback recovery
- budget actual/forecast threshold notification

### 14.3 Alert 초기 권고

- 5xx가 5분 동안 연속 발생
- queue oldest task age가 15분 초과
- task attempt가 3회 이상
- worker timeout 발생
- snapshot flush가 연속 2회 실패
- monthly budget actual spend가 50%, 80%, 100% 도달

실제 notification channel과 on-call 책임자는 approval packet에서 확정한다.

## 15. 비용 안전장치

- 세 Cloud Run service 모두 `minScale=0`을 유지한다.
- Document worker concurrency는 1로 유지한다.
- queue concurrency를 초기 1로 제한한다.
- test 종료 후 열린 browser/WebSocket 세션을 종료한다.
- staging data retention 기간을 정하고 source, snapshot와 export 정리 책임자를 지정한다.
- Artifact Registry image retention policy는 최근 검증된 digest와 rollback 대상만 보존하도록 별도 승인한다.
- 월간 예산은 원화 `${STAGING_MONTHLY_BUDGET_KRW}`로 승인받고 actual spend 50%, 80%, 100% 알림을 설정한다.

Google Cloud budget은 지출을 자동으로 차단하지 않는다. 자동 billing disable은 서비스 중단과 resource 손실 위험이 있으므로 이번 staging 설계 범위에 포함하지 않는다.

## 16. 주요 실패 모드와 대응

| 실패 모드 | 탐지 | 즉시 대응 | 배포 중단 조건 |
|---|---|---|---|
| production project ID 선택 | read-only project 확인 | 모든 mutation 중단 | 항상 중단 |
| region 불일치 | resource describe | 생성 전 값 수정 | 항상 중단 |
| Auth authorized domain 누락 | login redirect 실패 | domain/authDomain 수정 | login 성공 전 중단 |
| Document API CORS 또는 URL 오류 | browser network error | Hosting env와 service URL 검증 | upload 전 중단 |
| WSS upgrade 실패 | provider connect timeout | public invocation, URL, server log 점검 | collaboration test 중단 |
| IAM denied | Cloud Audit/Run log | 해당 identity의 최소 role만 보완 | broad role 부여 금지 |
| Secret version 미연결 | revision startup failure | secret binding/version 확인 | healthz 성공 전 중단 |
| queue region mismatch | CreateTask NOT_FOUND | project/location/queue 비교 | task test 중단 |
| OIDC audience 또는 invoker 오류 | worker 401/403 | default run.app URL과 IAM 확인 | parse/export 중단 |
| worker timeout | task retry/504 | 문서 크기, CPU/memory, timeout 검토 | 반복 enqueue 금지 |
| snapshot flush 실패 | export 409/5xx | collaboration state와 token 확인 | export 중단 |
| Cloud Run restart 후 수렴 실패 | browser E2E | rollback 또는 reconnect 수정 | acceptance 실패 |
| budget alert 미구성 | billing budget 조회 | 배포 승인 취소 | traffic 전 중단 |
| secret 노출 의심 | log/repository scan | secret rotate, revision 교체 | 즉시 중단 |

## 17. Acceptance criteria

### 17.1 배포 전

- staging project ID, billing account, region과 active deployer가 승인 기록과 일치한다.
- production project ID와 domain이 입력에 포함되지 않는다.
- image 3개가 SHA-256 digest로 고정되어 있다.
- 4개 service account와 IAM binding 계획이 최소 권한 matrix와 일치한다.
- internal token secret이 repository 밖에서 준비되고 두 service에 같은 승인 version으로 연결될 계획이다.
- worker는 private이며 Tasks caller만 invoker이다.
- budget amount, thresholds와 notification channel이 존재한다.
- queue retry, rate와 concurrency가 승인됐다.
- 기존 static staging validator가 성공한다.
- machine-readable manifest와 read-only preflight가 성공한 뒤에만 mutation 승인 단계로 넘어간다.

### 17.2 배포 후

- Hosting에서 staging app이 열리고 Google sign-in이 성공한다.
- Document API와 Collaboration service `/healthz`가 성공한다.
- worker의 unauthenticated 직접 호출은 거부된다.
- Cloud Tasks OIDC 호출은 worker에서 수락된다.
- 0 byte와 200 MiB 초과 source upload가 거부된다.
- 200 MiB source가 규칙과 API 경계에서 허용된다.
- owner/editor/viewer ACL이 예상대로 적용된다.
- 두 browser context에서 Yjs state와 remote cursor가 수렴한다.
- viewer keyboard, delete, paste와 편집 명령이 차단된다.
- Collaboration revision restart 뒤 reconnect와 snapshot recovery가 성공한다.
- export 후 HWPX를 다시 parse해 본문, 표 셀과 지원 대상 이미지가 보존된다.
- 로그에 token 또는 secret이 나타나지 않는다.
- budget과 notification channel이 조회 가능하다.

## 18. 다음 machine-readable manifest interface

다음 구현 단위는 아래 필드를 가진 manifest를 생성한다. 이 문서는 schema 요구사항만 정의하며 파일은 만들지 않는다.

```text
schemaVersion
environment
project.id
project.number
project.billingAccount
project.region
project.forbiddenProjectIds[]

firebase.webAppId
firebase.apiKeyReference
firebase.authDomain
firebase.authorizedDomains[]
firebase.firestoreLocation
firebase.storageBucket
firebase.storageLocation
firebase.hostingSite

artifactRegistry.repository
artifactRegistry.location

cloudRun.collaboration.name
cloudRun.collaboration.image
cloudRun.collaboration.digest
cloudRun.collaboration.serviceAccount
cloudRun.collaboration.ingress
cloudRun.collaboration.runtime

cloudRun.documentApi.name
cloudRun.documentApi.image
cloudRun.documentApi.digest
cloudRun.documentApi.serviceAccount
cloudRun.documentApi.ingress
cloudRun.documentApi.runtime

cloudRun.documentWorker.name
cloudRun.documentWorker.image
cloudRun.documentWorker.digest
cloudRun.documentWorker.serviceAccount
cloudRun.documentWorker.ingress
cloudRun.documentWorker.runtime

tasks.callerServiceAccount
tasks.parse.name
tasks.parse.location
tasks.parse.targetUrl
tasks.parse.retry
tasks.parse.rateLimits
tasks.export.name
tasks.export.location
tasks.export.targetUrl
tasks.export.retry
tasks.export.rateLimits

secrets.collaborationInternal.name
secrets.collaborationInternal.version

iam.bindings[]

budget.currency=KRW
budget.amount
budget.thresholds[]
budget.notificationChannels[]

operations.dataRetentionDays
operations.approvalReference
operations.rollbackRevisionIds
```

Read-only preflight validator는 이 manifest와 실제 조회 결과를 비교하되 create, update, delete, deploy 또는 IAM mutation 명령을 실행하지 않아야 한다.

## 19. 승인 시 반드시 보여줄 결정 사항

실제 staging mutation 승인을 요청할 때 다음 내용을 한 번에 제시한다.

1. project ID, project number와 billing account
2. region과 데이터 위치
3. 생성 또는 변경할 모든 리소스 목록
4. service account별 IAM binding 전체
5. secret 이름과 접근 principal, 값은 제외
6. queue retry/rate/concurrency
7. Cloud Run public/private policy
8. internal flush의 single-service staging 제한 수용 여부
9. 월간 예산 원화 금액과 threshold
10. 예상되는 과금 서비스와 삭제/rollback 절차
11. image digest와 배포 revision 계획
12. staging acceptance test 목록

## 20. 공식 참고 문서

- [Cloud Run request timeout](https://cloud.google.com/run/docs/configuring/request-timeout)
- [Cloud Run WebSocket](https://cloud.google.com/run/docs/triggering/websockets)
- [Cloud Run authentication overview](https://cloud.google.com/run/docs/authenticating/overview)
- [Cloud Run IAM roles](https://cloud.google.com/run/docs/reference/iam/roles)
- [Cloud Run locations](https://cloud.google.com/run/docs/locations)
- [Cloud Tasks HTTP target authentication](https://cloud.google.com/tasks/docs/creating-http-target-tasks)
- [Cloud Tasks access control](https://cloud.google.com/tasks/docs/access-control)
- [Cloud Tasks locations](https://cloud.google.com/tasks/docs/locations)
- [Firestore locations](https://firebase.google.com/docs/firestore/locations)
- [Firestore server client IAM](https://cloud.google.com/firestore/docs/security/iam)
- [Cloud Storage locations](https://cloud.google.com/storage/docs/locations)
- [Cloud Storage IAM roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
- [Secret Manager access control](https://cloud.google.com/secret-manager/docs/access-control)
- [Artifact Registry access control](https://cloud.google.com/artifact-registry/docs/access-control)
- [Cloud Billing budgets](https://cloud.google.com/billing/docs/how-to/budgets)
- [Firebase Auth redirect and custom domain guidance](https://firebase.google.com/docs/auth/web/redirect-best-practices)
