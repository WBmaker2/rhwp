# Staging Architecture and Deployment Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최신 Draft PR 상태를 정리하고, 현재 구현된 Firebase·Cloud Run·Cloud Tasks 계약을 기준으로 staging architecture 설계 문서와 비실행 deployment runbook을 작성한다.

**Architecture:** 저장소의 기존 staging 템플릿과 production-facing 어댑터를 source of truth로 사용한다. 설계 문서는 리소스·데이터 흐름·IAM·Secret·비용·운영 경계를 정의하고, runbook은 명시적 승인 이후에만 수행할 수 있는 배포 절차와 중단·rollback 조건을 제공한다. 이번 구현 단위에서는 machine-readable manifest, read-only preflight validator, 실제 클라우드 리소스 생성·변경을 수행하지 않는다.

**Tech Stack:** Firebase Authentication, Firestore, Cloud Storage, Firebase Hosting, Google Cloud Run, Cloud Tasks, Secret Manager, Artifact Registry, Cloud Logging/Monitoring, GitHub Actions, Markdown

## Global Constraints

- 저장소: `WBmaker2/rhwp`
- 작업 브랜치: `feat/firebase-collaboration-mvp-v1`
- 대상 PR: Draft PR `#1`, base `devel`
- PR을 merge하거나 Draft 상태를 해제하지 않는다.
- Firebase/GCP 프로젝트, API, IAM, Secret Manager, Cloud Tasks, Cloud Run, Firebase Hosting·Rules 리소스를 생성·변경·배포하지 않는다.
- 현재 기본 리전 계약 `asia-northeast3`을 유지하되, 실제 적용 전 사용자 승인 항목으로 표시한다.
- 기존 서비스 이름 `rhwp-collaboration-staging`, `rhwp-document-api-staging`, `rhwp-document-worker-staging`과 queue 이름 `rhwp-parse-staging`, `rhwp-export-staging`을 문서 기준값으로 사용한다.
- 파일 업로드 계약 `0 < 파일 크기 ≤ 200 MiB`와 사용자 이미지 최대 `20 MiB`를 유지한다.
- secret 값, 서비스 계정 키, Firebase Admin credential을 저장소에 기록하지 않는다.
- 문서의 명령은 예시·runbook 절차이며 이번 작업에서 실행하지 않는다.

---

### Task 1: Baseline 확인과 Draft PR 설명 최신화

**Files:**
- Modify: Draft PR `WBmaker2/rhwp#1` body
- Reference: `docs/superpowers/plans/2026-07-26-npm-ci-reproducibility.md`

**Interfaces:**
- Consumes: 최신 branch head SHA와 해당 SHA의 GitHub Actions 결론
- Produces: 현재 구현 상태와 다음 staging 문서화 범위를 정확히 설명하는 PR body

- [x] **Step 1: 최신 PR 상태를 확인한다**

확인 결과:

```text
state = open
draft = true
merged = false
mergeable = true
head = feat/firebase-collaboration-mvp-v1
base = devel
```

- [x] **Step 2: 문서 작업 직전 기준 head의 전체 workflow 결과를 확인한다**

기준 head `f9f1e8e09efcf8cb0fad955ce66eca02728a3f2d`에서 다음 항목을 포함한 모든 workflow가 성공했다.

```text
CI
CodeQL
Collaboration recovery E2E
Collaboration Emulator E2E
Document worker
Collaboration browser visual
Render Diff
Staging configuration
```

- [x] **Step 3: PR body의 오래된 head와 실행 중 문구를 교체한다**

PR body에 기준 head, 전체 workflow 성공, npm `ci` 전환 완료, 이번 staging 문서화 범위와 cloud mutation 금지를 기록했다.

- [x] **Step 4: PR 상태를 다시 확인한다**

확인 결과:

```text
draft = true
merged = false
```

---

### Task 2: Staging architecture 설계 문서 작성

**Files:**
- Create: `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- Reference: `firebase/staging.env.example`
- Reference: `deploy/cloudrun/*.service.yaml`
- Reference: `scripts/validate_staging_config.py`
- Reference: `services/*/src/*firebase-adapters.ts`

**Interfaces:**
- Consumes: 현재 환경 변수, Cloud Run service template, Firebase adapter의 실제 데이터 접근 범위
- Produces: 다음 단계의 machine-readable manifest와 read-only preflight validator가 구현할 수 있는 명시적 staging 계약

- [ ] **Step 1: 설계 문서의 상태와 범위를 정의한다**

문서 머리말에 다음을 명시한다.

```text
상태: staging 배포 전 설계 기준안
적용: 명시적 승인 이후
이번 문서 작성으로 생성되는 클라우드 리소스: 없음
```

- [ ] **Step 2: 전체 staging topology와 요청 흐름을 작성한다**

다음 구성 요소와 연결을 포함한다.

```text
Browser
  -> Firebase Hosting
  -> Firebase Authentication
  -> Firestore / Cloud Storage
  -> Document API (HTTPS)
  -> Collaboration server (WSS)
Document API
  -> Cloud Tasks parse/export queues
  -> Collaboration internal flush endpoint
Cloud Tasks
  -> Document worker private endpoints with OIDC
Document worker
  -> Firestore state
  -> Cloud Storage source/manifest/snapshot/export objects
```

- [ ] **Step 3: 리소스 inventory와 naming contract를 정의한다**

최소 항목:

```text
Firebase/GCP staging project placeholder
asia-northeast3 region
Firebase Web App
Firestore database
Storage bucket
Firebase Hosting site
Artifact Registry repository
3 Cloud Run services
2 Cloud Tasks queues
4 dedicated service accounts
1 Secret Manager secret
budget and notification channels
```

- [ ] **Step 4: 데이터·신뢰 경계를 정의한다**

다음 경계를 설명한다.

```text
- 공개 Firebase Web config와 secret의 구분
- Firebase ID token과 document ACL 검증
- public HTTPS/WSS endpoint와 internal worker endpoint 구분
- Cloud Tasks OIDC identity
- collaboration flush의 Cloud Run identity + internal token 이중 경계
- client가 snapshot을 직접 읽거나 쓰지 못하는 규칙
```

- [ ] **Step 5: IAM matrix를 작성한다**

행:

```text
release/deployer identity
collaboration service account
document API service account
document worker service account
Cloud Tasks caller service account
```

열:

```text
Firestore
Cloud Storage
Cloud Tasks enqueue
Cloud Run invoke
Secret access
Artifact Registry image pull
Firebase deploy
```

각 셀은 `required`, `not required`, `approval-time decision` 중 하나와 이유를 기록한다. 광범위한 Owner/Editor 권한을 금지하고, 실제 role binding은 다음 manifest/preflight 단계에서 확정하도록 한다.

- [ ] **Step 6: runtime, scaling, timeout 계약을 기록한다**

현재 템플릿 값을 그대로 기록한다.

```text
collaboration: concurrency 80, timeout 3600s, 1 CPU, 1Gi, min 0, max 10
document API: concurrency 80, timeout 300s, 1 CPU, 512Mi, min 0, max 20
document worker: concurrency 1, timeout 900s, 2 CPU, 2Gi, min 0, max 10
```

- [ ] **Step 7: 비용·관측·운영 안전장치를 정의한다**

포함 항목:

```text
- minScale 0 유지
- budget threshold와 알림 채널은 승인 필수 입력
- Cloud Logging의 secret/token redaction 원칙
- queue backlog, task retry, 5xx, latency, instance count 관측
- staging 데이터 보존 기간과 수동 정리 책임
```

금액은 확정 비용으로 단정하지 않고 실제 프로젝트·트래픽·리전 기준 계산이 필요한 승인 항목으로 남긴다.

- [ ] **Step 8: 실패 모드와 acceptance criteria를 정의한다**

최소 실패 모드:

```text
Auth domain 누락
CORS/WSS 연결 실패
IAM denied
Secret version 미연결
queue region mismatch
worker timeout/retry
snapshot flush 실패
Cloud Run restart/reconnect
budget alert 누락
production project ID 오입력
```

acceptance criteria는 배포 전·배포 후로 구분한다.

- [ ] **Step 9: 다음 단계 인터페이스를 정의한다**

다음 구현 단위가 생성할 machine-readable manifest의 필수 필드를 목록으로 정의하되 파일은 생성하지 않는다.

---

### Task 3: Staging deployment runbook 작성

**Files:**
- Create: `docs/runbooks/staging-deployment.md`
- Reference: `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- Reference: `deploy/cloudrun/README.md`

**Interfaces:**
- Consumes: 승인된 staging architecture 계약
- Produces: 승인 전에는 실행할 수 없고, 승인 후 단계별로 중단·검증·rollback 가능한 배포 절차

- [ ] **Step 1: Runbook 안전 문구와 실행 게이트를 작성한다**

문서 상단에 다음을 명시한다.

```text
DO NOT RUN WITHOUT EXPLICIT APPROVAL
production project 사용 금지
각 단계의 project ID와 active account를 재확인
실패한 단계 이후 자동 진행 금지
```

- [ ] **Step 2: 승인 패킷과 필수 입력 표를 작성한다**

필수 입력:

```text
project ID
billing account
region
authorized domains
service account names
secret names
queue retry/rate settings
budget amount and thresholds
notification channel
container image digests
data retention period
```

- [ ] **Step 3: 배포 전 read-only 확인 절차를 작성한다**

현재 단계에서는 실행하지 않는 명령 예시를 포함한다.

```text
gcloud config get-value project
gcloud auth list
gcloud projects describe
gcloud services list --enabled
gcloud run services list
gcloud tasks queues list
gcloud secrets list
firebase projects:list
```

- [ ] **Step 4: 리소스 준비 순서를 작성한다**

순서:

```text
project/billing
APIs
Firebase app/Auth/Firestore/Storage/Hosting
Artifact Registry
service accounts
IAM
Secret Manager
Cloud Tasks queues
container images
Cloud Run worker
Cloud Run collaboration server
Cloud Run document API
Firebase Rules/Indexes/Hosting
```

각 단계에 `precondition`, `action`, `verification`, `stop condition`, `rollback`을 작성한다.

- [ ] **Step 5: Cloud Run과 Cloud Tasks 배포 검증 절차를 작성한다**

포함 검증:

```text
healthz
worker unauthenticated invocation denied
Cloud Tasks OIDC invocation accepted
collaboration WSS upgrade
Document API Firebase ID token verification
internal flush unauthorized/authorized boundary
```

- [ ] **Step 6: Firebase 배포 검증 절차를 작성한다**

포함 검증:

```text
Google sign-in
authorized domain
Firestore Rules
Storage Rules
0-byte and >200 MiB rejection
200 MiB boundary acceptance
viewer/editor/owner ACL
snapshot client access denial
```

- [ ] **Step 7: staging acceptance test와 rollback 절차를 작성한다**

acceptance flow:

```text
login
upload
parse
share link
editor/viewer collaboration
viewer mutation rejection
restart/reconnect
snapshot recovery
export
HWPX re-import
logging and budget signal review
```

rollback 우선순위:

```text
traffic stop
previous Cloud Run revision
queue pause
Firebase Hosting rollback
Rules rollback
secret version disable
staging data cleanup only after approval
```

- [ ] **Step 8: 배포 완료 기록 양식을 작성한다**

기록 항목:

```text
approval reference
deployer
project ID
region
image digests
service revisions
Rules release
queue configuration
acceptance evidence
known issues
rollback point
```

---

### Task 4: 문서 정합성 검증과 PR 최종 갱신

**Files:**
- Modify: `docs/superpowers/plans/2026-07-26-staging-architecture-runbook.md`
- Read: `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- Read: `docs/runbooks/staging-deployment.md`
- Modify: Draft PR `WBmaker2/rhwp#1` body

**Interfaces:**
- Consumes: 완료된 설계와 runbook
- Produces: 모순·placeholder·범위 이탈이 없는 문서와 최신 PR 상태

- [ ] **Step 1: placeholder와 범위 이탈을 검사한다**

금지 항목:

```text
TBD
TODO
실제 secret 값
service account key JSON
실제 production project ID
배포 완료 주장
cloud resource 생성 주장
```

`${...}`는 기존 템플릿 변수명이나 명시적 예시일 때만 허용한다.

- [ ] **Step 2: 기존 템플릿과 수치를 대조한다**

대조 대상:

```text
region
service names
queue names
concurrency
timeout
CPU/memory
Secret Manager reference
worker ingress
```

- [ ] **Step 3: 기존 staging validator 결과를 확인한다**

Run:

```bash
python3 scripts/validate_staging_config.py
```

Expected:

```text
staging configuration templates are valid; no deployment was performed
```

GitHub 연결 환경에서 직접 실행할 수 없으면 최신 `Staging configuration` workflow 성공 결과를 증거로 기록한다.

- [ ] **Step 4: 문서 변경 head의 GitHub Actions 결과를 확인한다**

최소 확인:

```text
Staging configuration = success
CI = success
CodeQL = success
```

- [ ] **Step 5: 계획 체크박스와 최종 검증 결과를 갱신한다**

기록 항목:

```text
final head SHA
workflow run IDs
created files
cloud mutations = none
```

- [ ] **Step 6: PR body를 최종 갱신한다**

추가 내용:

```text
- staging architecture design 문서 경로
- staging deployment runbook 경로
- 이번 단계에서 cloud mutation 없음
- 다음 단계: machine-readable manifest + read-only preflight validator
- 실제 staging 배포는 명시적 승인 후에만 가능
```

- [ ] **Step 7: PR 상태를 최종 확인한다**

Expected:

```text
open = true
draft = true
merged = false
```
