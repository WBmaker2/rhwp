# rhwp Collaboration Staging Deployment Runbook

> **DO NOT RUN WITHOUT EXPLICIT USER APPROVAL.**
>
> 이 문서는 실행 절차를 정의할 뿐이다. 이 문서가 저장소에 존재한다고 해서 Firebase 또는 Google Cloud 리소스 생성·변경·배포가 승인된 것은 아니다.

- 대상 환경: staging only
- 설계 기준: `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- 기본 region: `asia-northeast3`
- production project 사용: 금지
- 실패한 단계 이후 자동 진행: 금지
- service account key JSON 생성: 금지
- 이 runbook 작성 과정에서 수행한 cloud mutation: 없음

## 1. 실행 전 필수 중단 조건

다음 항목 중 하나라도 충족되지 않으면 이 runbook의 mutation 단계로 넘어가지 않는다.

1. 사용자가 project ID, billing account, region, IAM, budget와 생성·변경 리소스 전체를 보고 명시적으로 승인했다.
2. machine-readable staging manifest가 작성되고 version control에 기록됐다.
3. read-only preflight validator가 실제 project 상태를 조회해 성공했다.
4. 승인된 project ID가 production 또는 기존 업무 project가 아니다.
5. container image 3개가 digest로 고정됐다.
6. budget 금액, threshold와 notification channel이 승인됐다.
7. internal flush의 현재 single-service 보안 제한을 staging에서 수용할지 결정됐다.
8. Cloud Tasks dispatch deadline과 worker timeout 불일치가 해결됐다.

### 1.1 배포 전 해결해야 할 현재 구현 불일치

#### Cloud Tasks dispatch deadline

현재 Document API가 만드는 HTTP task payload에는 `dispatchDeadline`이 없다. Cloud Tasks HTTP task의 기본 deadline은 10분이고 Document worker Cloud Run timeout은 15분이다.

배포 승인 전 아래 중 하나를 선택하고 코드·테스트·manifest를 일치시킨다.

- 권고: task payload에 `dispatchDeadline=900s`를 추가하고 관련 단위·Emulator E2E를 통과한다.
- 대안: Document worker timeout을 `600s` 이하로 줄이고 200 MiB 처리 acceptance를 다시 확인한다.

선택하지 않은 상태에서 worker를 staging에 배포하지 않는다.

#### Collaboration internal flush

Document API는 Cloud Run identity token과 internal token을 함께 보내지만 현재 Collaboration application handler는 internal token만 직접 검증한다. Collaboration service는 browser WSS를 받아야 하므로 service 전체를 private로 전환할 수 없다.

배포 승인 전 아래 중 하나를 선택한다.

- MVP staging 한정: public Collaboration service + high-entropy internal token 경계를 수용한다.
- 강화: internal flush를 별도 private service 또는 private endpoint로 분리한 뒤 배포한다.

선택과 승인 근거를 deployment record에 남긴다.

## 2. Approval packet

실행자는 다음 표를 완성해 사용자에게 제시하고 승인을 받는다. 값이 비어 있으면 실행하지 않는다.

| 항목 | 승인 값 |
|---|---|
| approval reference | `${APPROVAL_REFERENCE}` |
| deployer identity | `${DEPLOYER_IDENTITY}` |
| staging project ID | `${PROJECT_ID}` |
| staging project number | `${PROJECT_NUMBER}` |
| forbidden project IDs | `${FORBIDDEN_PROJECT_IDS_CSV}` |
| billing account | `${BILLING_ACCOUNT_ID}` |
| region | `asia-northeast3` |
| Firebase authorized domains | `${AUTHORIZED_DOMAINS_CSV}` |
| Storage bucket | `${STORAGE_BUCKET}` |
| Artifact Registry repository | `rhwp-staging` |
| Collaboration image digest | `${COLLABORATION_IMAGE_DIGEST}` |
| Document API image digest | `${DOCUMENT_API_IMAGE_DIGEST}` |
| Document worker image digest | `${DOCUMENT_WORKER_IMAGE_DIGEST}` |
| Collaboration service account | `${COLLABORATION_SA}` |
| Document API service account | `${DOCUMENT_API_SA}` |
| Document worker service account | `${DOCUMENT_WORKER_SA}` |
| Cloud Tasks caller account | `${TASKS_CALLER_SA}` |
| internal token secret | `rhwp-collaboration-internal-token-staging` |
| parse queue profile | concurrency 1, rate 1/s, attempts 5, backoff 10–300s |
| export queue profile | concurrency 1, rate 1/s, attempts 5, backoff 10–300s |
| task dispatch deadline decision | `${TASK_DISPATCH_DEADLINE_DECISION}` |
| internal flush security decision | `${INTERNAL_FLUSH_SECURITY_DECISION}` |
| monthly budget | `${STAGING_MONTHLY_BUDGET_KRW}` KRW |
| budget thresholds | 50%, 80%, 100% actual spend |
| notification channel | `${STAGING_BUDGET_NOTIFICATION_CHANNEL}` |
| data retention | `${STAGING_DATA_RETENTION_DAYS}` days |
| rollback revisions | `${ROLLBACK_REVISION_IDS}` |

## 3. Shell session guard

아래 예시는 approval packet의 값을 shell variable로 옮기는 형식이다. secret 원문은 variable로 설정하지 않는다.

```bash
set -euo pipefail

export PROJECT_ID='approved-staging-project-id'
export PROJECT_NUMBER='approved-project-number'
export REGION='asia-northeast3'
export BILLING_ACCOUNT_ID='approved-billing-account-id'
export DEPLOYER_ACCOUNT='approved-deployer@example.com'
export STORAGE_BUCKET='actual-firebase-storage-bucket'
export ARTIFACT_REPOSITORY='rhwp-staging'

export COLLABORATION_SERVICE='rhwp-collaboration-staging'
export DOCUMENT_API_SERVICE='rhwp-document-api-staging'
export DOCUMENT_WORKER_SERVICE='rhwp-document-worker-staging'
export PARSE_QUEUE='rhwp-parse-staging'
export EXPORT_QUEUE='rhwp-export-staging'
export INTERNAL_SECRET='rhwp-collaboration-internal-token-staging'

export COLLABORATION_SA="rhwp-collaboration-staging@${PROJECT_ID}.iam.gserviceaccount.com"
export DOCUMENT_API_SA="rhwp-document-api-staging@${PROJECT_ID}.iam.gserviceaccount.com"
export DOCUMENT_WORKER_SA="rhwp-document-worker-staging@${PROJECT_ID}.iam.gserviceaccount.com"
export TASKS_CALLER_SA="rhwp-tasks-staging@${PROJECT_ID}.iam.gserviceaccount.com"
```

실행자가 production project ID 목록을 별도 승인 문서에서 가져와 아래처럼 검사한다.

```bash
case ",${FORBIDDEN_PROJECT_IDS_CSV}," in
  *",${PROJECT_ID},"*)
    echo "Refusing to operate on a forbidden project: ${PROJECT_ID}" >&2
    exit 1
    ;;
esac
```

## 4. Phase 0 — read-only preflight

### Precondition

- 아직 어떠한 mutation 명령도 실행하지 않는다.
- `gcloud`, `firebase`, `docker` 또는 사용하기로 승인한 build tool의 version을 기록한다.
- active account와 project를 변경하지 않은 채 먼저 현재 상태를 확인한다.

### Read-only actions

```bash
gcloud version
firebase --version

gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud config get-value project

gcloud projects describe "${PROJECT_ID}" \
  --format='yaml(projectId,projectNumber,name,lifecycleState)'

gcloud billing projects describe "${PROJECT_ID}" \
  --format='yaml(projectId,billingAccountName,billingEnabled)'

gcloud services list --enabled \
  --project="${PROJECT_ID}" \
  --format='value(config.name)'

gcloud run services list \
  --project="${PROJECT_ID}" \
  --region="${REGION}"

gcloud tasks queues list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"

gcloud secrets list --project="${PROJECT_ID}"
gcloud iam service-accounts list --project="${PROJECT_ID}"
gcloud artifacts repositories list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"

firebase projects:list
```

### Verification

- active account가 `${DEPLOYER_ACCOUNT}`와 일치한다.
- project ID와 project number가 approval packet과 일치한다.
- billing account와 enabled 상태가 승인 값과 일치한다.
- 예상하지 못한 기존 Cloud Run service, queue, secret 또는 service account가 있으면 목록을 사용자에게 제시한다.
- organization policy가 `asia-northeast3` 사용을 허용한다.

### Stop condition

- project 또는 billing account 불일치
- production project 가능성
- active account 불일치
- 기존 동명 리소스가 승인 없이 존재
- read-only 명령 자체에 필요한 조회 권한 부족

### Rollback

read-only 단계이므로 rollback 대상이 없다. 오류를 기록하고 중단한다.

## 5. Phase 1 — project, billing, API

### Precondition

- project 생성 또는 기존 empty staging project 사용 방식이 승인됐다.
- billing 연결이 승인됐다.
- 필요한 deployer IAM이 최소 권한으로 준비됐다.

### Actions

project가 아직 없을 때만 승인된 방식으로 생성한다. 기존 project를 사용하면 생성 명령을 실행하지 않는다.

필요 API 후보:

```text
run.googleapis.com
cloudtasks.googleapis.com
firestore.googleapis.com
storage.googleapis.com
secretmanager.googleapis.com
artifactregistry.googleapis.com
firebase.googleapis.com
firebasehosting.googleapis.com
identitytoolkit.googleapis.com
cloudbuild.googleapis.com  # Cloud Build를 승인한 경우에만
iamcredentials.googleapis.com
```

승인 후 예시:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudtasks.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  firebase.googleapis.com \
  firebasehosting.googleapis.com \
  identitytoolkit.googleapis.com \
  iamcredentials.googleapis.com \
  --project="${PROJECT_ID}"
```

Cloud Build를 사용하지 않으면 `cloudbuild.googleapis.com`을 활성화하지 않는다.

### Verification

```bash
gcloud services list --enabled \
  --project="${PROJECT_ID}" \
  --filter='config.name:(run.googleapis.com cloudtasks.googleapis.com firestore.googleapis.com storage.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com identitytoolkit.googleapis.com iamcredentials.googleapis.com)'
```

### Stop condition

- API 활성화가 다른 project에서 수행됨
- billing 미연결
- organization policy 또는 quota 오류

### Rollback

오사용이 확인되면 즉시 중단한다. API disable은 다른 리소스에 영향을 줄 수 있으므로 자동 실행하지 않고 사용자 승인 후 처리한다.

## 6. Phase 2 — Firebase base resources

### Precondition

- project와 region이 승인됐다.
- Firestore와 Storage 위치가 `asia-northeast3`으로 승인됐다.
- 위치는 생성 후 변경하기 어렵다는 점을 확인했다.

### Actions

기존 GCP project에 Firebase를 추가하는 경우:

```bash
firebase projects:addfirebase "${PROJECT_ID}"
```

Firebase Web App을 생성하고 app ID를 deployment record에 저장한다.

```bash
firebase apps:create web rhwp-staging --project="${PROJECT_ID}"
firebase apps:list --project="${PROJECT_ID}"
```

Firestore default database는 `asia-northeast3`에 Native mode로 생성한다. 실제 CLI version의 dry-run 또는 help를 확인한 뒤 승인된 명령을 실행한다.

```bash
gcloud firestore databases create \
  --database='(default)' \
  --location="${REGION}" \
  --type=firestore-native \
  --project="${PROJECT_ID}"
```

Cloud Storage for Firebase는 Firebase console 또는 승인된 provisioning 방법으로 시작하고, 반환된 실제 bucket 이름을 `${STORAGE_BUCKET}`으로 기록한다. bucket 이름을 `.appspot.com`으로 추측해 생성하지 않는다.

Firebase Authentication에서 Google provider를 활성화하고 승인된 staging domain만 authorized domain에 추가한다.

### Verification

```bash
firebase apps:list --project="${PROJECT_ID}"
gcloud firestore databases describe \
  --database='(default)' \
  --project="${PROJECT_ID}"
gcloud storage buckets describe "gs://${STORAGE_BUCKET}"
```

확인:

- Firestore location `asia-northeast3`
- Storage location `ASIA-NORTHEAST3`
- Google provider enabled
- staging Hosting domain과 승인 custom domain만 authorized

### Stop condition

- Firestore 또는 Storage location 불일치
- production domain 포함
- 예상하지 않은 Firebase App 존재
- public bucket policy 존재

### Rollback

Firestore 또는 Storage location 오류는 단순 수정이 불가능할 수 있다. 잘못 생성한 project에서 진행하지 말고 사용자에게 새 staging project 생성 여부를 승인받는다. 데이터 삭제를 자동 수행하지 않는다.

## 7. Phase 3 — Artifact Registry와 image digest

### Precondition

- build 방식이 local, Cloud Build 또는 별도 CI 중 하나로 승인됐다.
- 각 Dockerfile과 native worker 포함 여부를 검증했다.

### Actions

repository가 없을 때만 생성한다.

```bash
gcloud artifacts repositories create "${ARTIFACT_REPOSITORY}" \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --description='rhwp staging images'
```

세 image를 build하고 push한 후 tag가 아니라 digest를 조회한다. 실제 build 명령은 승인된 build 방식에 따라 실행한다.

```bash
gcloud artifacts docker images list \
  "${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPOSITORY}" \
  --include-tags \
  --format='table(package,version,tags,updateTime)'
```

### Verification

- Collaboration, Document API, Document worker image가 각각 존재한다.
- 배포 입력은 모두 `@sha256:` digest 형식이다.
- Document worker image에 `/usr/local/bin/rhwp-collaboration-worker`가 존재한다.
- image provenance와 source commit SHA를 deployment record에 남긴다.

### Stop condition

- mutable tag만 존재
- source commit 불명
- vulnerability scan 또는 build test 실패
- worker native binary 누락

### Rollback

새 image는 traffic을 받기 전에는 runtime rollback이 필요 없다. 잘못된 digest를 승인 목록에서 제외하며 즉시 삭제하지 않는다.

## 8. Phase 4 — service accounts와 IAM

### Precondition

- architecture IAM matrix가 승인됐다.
- `roles/owner`, `roles/editor`를 runtime identity에 사용하지 않는다.

### Actions

service account가 없을 때만 생성한다.

```bash
for account in \
  rhwp-collaboration-staging \
  rhwp-document-api-staging \
  rhwp-document-worker-staging \
  rhwp-tasks-staging
do
  gcloud iam service-accounts create "${account}" \
    --project="${PROJECT_ID}" \
    --display-name="${account}"
done
```

Firestore runtime access:

```bash
for sa in "${COLLABORATION_SA}" "${DOCUMENT_API_SA}" "${DOCUMENT_WORKER_SA}"
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${sa}" \
    --role='roles/datastore.user'
done
```

Storage bucket-level access:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${STORAGE_BUCKET}" \
  --member="serviceAccount:${COLLABORATION_SA}" \
  --role='roles/storage.objectAdmin'

gcloud storage buckets add-iam-policy-binding "gs://${STORAGE_BUCKET}" \
  --member="serviceAccount:${DOCUMENT_API_SA}" \
  --role='roles/storage.objectViewer'

gcloud storage buckets add-iam-policy-binding "gs://${STORAGE_BUCKET}" \
  --member="serviceAccount:${DOCUMENT_WORKER_SA}" \
  --role='roles/storage.objectAdmin'
```

Document API가 Tasks caller identity를 task OIDC account로 사용할 수 있게 service account resource에 제한한다.

```bash
gcloud iam service-accounts add-iam-policy-binding "${TASKS_CALLER_SA}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${DOCUMENT_API_SA}" \
  --role='roles/iam.serviceAccountUser'
```

Artifact Registry가 cross-project인 경우에만 Cloud Run service agent에 repository-level Reader를 부여한다. same-project 기본 동작을 확인하기 전 불필요하게 추가하지 않는다.

### Verification

```bash
gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten='bindings[].members' \
  --filter="bindings.members:(serviceAccount:${COLLABORATION_SA} serviceAccount:${DOCUMENT_API_SA} serviceAccount:${DOCUMENT_WORKER_SA} serviceAccount:${TASKS_CALLER_SA})" \
  --format='table(bindings.role,bindings.members)'

gcloud storage buckets get-iam-policy "gs://${STORAGE_BUCKET}"

gcloud iam service-accounts get-iam-policy "${TASKS_CALLER_SA}" \
  --project="${PROJECT_ID}"
```

### Stop condition

- runtime identity에 Owner/Editor 부여
- service account key 생성
- project-level Storage Admin 부여
- Tasks caller에 Firestore 또는 Storage 권한 부여
- 예상 외 principal 추가

### Rollback

잘못 추가한 binding만 정확한 member와 role을 지정해 제거한다. 전체 IAM policy를 덮어쓰지 않는다. 제거도 사용자에게 변경 내용을 보여준 뒤 수행한다.

## 9. Phase 5 — Secret Manager

### Precondition

- secret 이름과 access principal이 승인됐다.
- secret 원문을 terminal history, repository 또는 log에 남기지 않는 입력 방법을 준비했다.

### Actions

secret이 없을 때 생성한다.

```bash
gcloud secrets create "${INTERNAL_SECRET}" \
  --replication-policy=automatic \
  --project="${PROJECT_ID}"
```

새 high-entropy token을 안전한 입력 도구로 생성해 stdin으로 version을 추가한다. 아래 명령에서 secret 원문을 command argument로 입력하지 않는다.

```bash
gcloud secrets versions add "${INTERNAL_SECRET}" \
  --data-file=- \
  --project="${PROJECT_ID}"
```

두 workload에 secret-level accessor를 부여한다.

```bash
for sa in "${COLLABORATION_SA}" "${DOCUMENT_API_SA}"
do
  gcloud secrets add-iam-policy-binding "${INTERNAL_SECRET}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${sa}" \
    --role='roles/secretmanager.secretAccessor'
done
```

### Verification

```bash
gcloud secrets describe "${INTERNAL_SECRET}" --project="${PROJECT_ID}"
gcloud secrets versions list "${INTERNAL_SECRET}" --project="${PROJECT_ID}"
gcloud secrets get-iam-policy "${INTERNAL_SECRET}" --project="${PROJECT_ID}"
```

secret value를 출력해 검증하지 않는다. version ID와 enabled 상태만 기록한다.

### Stop condition

- secret 원문이 console output 또는 log에 노출
- project-level secretAccessor 부여
- Document worker 또는 Tasks caller에 secret 접근 부여

### Rollback

노출이 의심되면 해당 version을 disable하고 새 token version을 만든다. 두 service revision 교체가 끝나기 전에 이전 정상 version을 destroy하지 않는다.

## 10. Phase 6 — Cloud Tasks queues

### Precondition

- dispatch deadline 불일치 해결이 코드와 테스트로 확인됐다.
- queue profile이 승인됐다.
- worker default `run.app` URL과 OIDC audience 계획이 정해졌다.

### Actions

queue가 없을 때 생성한다.

```bash
for queue in "${PARSE_QUEUE}" "${EXPORT_QUEUE}"
do
  gcloud tasks queues create "${queue}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=1 \
    --max-attempts=5 \
    --min-backoff=10s \
    --max-backoff=300s \
    --max-doublings=5 \
    --log-sampling-ratio=1.0
done
```

Document API에 queue별 enqueue 권한을 부여한다.

```bash
for queue in "${PARSE_QUEUE}" "${EXPORT_QUEUE}"
do
  gcloud tasks queues add-iam-policy-binding "${queue}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --member="serviceAccount:${DOCUMENT_API_SA}" \
    --role='roles/cloudtasks.enqueuer'
done
```

### Verification

```bash
for queue in "${PARSE_QUEUE}" "${EXPORT_QUEUE}"
do
  gcloud tasks queues describe "${queue}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}"
  gcloud tasks queues get-iam-policy "${queue}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}"
done
```

### Stop condition

- queue region 불일치
- concurrency 또는 rate가 승인값보다 큼
- allUsers 또는 allAuthenticatedUsers binding
- Document API 외 runtime identity에 enqueue 권한 부여

### Rollback

traffic 시작 전 잘못 생성된 queue는 사용자 승인 후 삭제할 수 있다. task가 존재하면 먼저 queue를 pause하고 task 상태를 기록한다. 자동 삭제하지 않는다.

## 11. Phase 7 — template rendering과 dry-run

### Precondition

- manifest와 실제 조회값이 일치한다.
- image digest, service account, bucket, URL과 secret version이 확정됐다.

### Actions

원본 template을 직접 덮어쓰지 않는다. 임시 작업 디렉터리에 render한다.

```bash
mkdir -p .staging-rendered
cp deploy/cloudrun/*.service.yaml .staging-rendered/
```

`${PROJECT_ID}`, `${IMAGE}`, `${DIGEST}`, `${STORAGE_BUCKET}`, service account와 URL placeholder를 승인값으로 치환한다. 치환 스크립트는 secret 원문을 처리하지 않고 Secret Manager reference만 유지해야 한다.

기존 static validator를 실행한다.

```bash
python3 scripts/validate_staging_config.py
```

Cloud Run YAML을 server-side apply 없이 검증한다.

```bash
gcloud run services replace \
  .staging-rendered/document-worker.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --dry-run

gcloud run services replace \
  .staging-rendered/collaboration-server.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --dry-run

gcloud run services replace \
  .staging-rendered/document-api.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --dry-run
```

### Verification

- placeholder가 남지 않았다.
- image가 digest-pinned다.
- worker ingress가 `internal`, concurrency 1, timeout 900 또는 승인된 정합값이다.
- emulator flag가 false다.
- Collaboration과 API의 secret reference가 같은 승인 version이다.

### Stop condition

- dry-run 실패
- unresolved placeholder
- secret literal 포함
- production project/domain 발견
- task deadline/worker timeout 불일치 지속

### Rollback

`.staging-rendered` local 파일만 삭제한다. cloud mutation은 없어야 한다.

## 12. Phase 8 — Document worker deploy

### Precondition

- worker image와 YAML dry-run 성공
- queue와 OIDC caller 준비
- Cloud Tasks dispatch deadline 정합 해결

### Actions

```bash
gcloud run services replace \
  .staging-rendered/document-worker.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}"
```

Tasks caller에 worker service invoker를 부여한다.

```bash
gcloud run services add-iam-policy-binding "${DOCUMENT_WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${TASKS_CALLER_SA}" \
  --role='roles/run.invoker'
```

`allUsers` binding이 없음을 확인한다.

### Verification

```bash
gcloud run services describe "${DOCUMENT_WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}"

gcloud run services get-iam-policy "${DOCUMENT_WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}"
```

- unauthenticated direct POST는 401/403이어야 한다.
- 승인된 identity를 사용한 health 또는 test task만 worker에 도달해야 한다.
- 실제 parse/export task는 Document API 배포 후 acceptance 단계에서 보낸다.

### Stop condition

- worker public invocation 가능
- startup failure
- native binary missing
- Firestore 또는 Storage permission denied

### Rollback

- 새 revision에 traffic을 주지 않거나 이전 revision으로 100% 되돌린다.
- queue를 pause해 새로운 task dispatch를 중단한다.
- service를 즉시 삭제하지 않는다.

## 13. Phase 9 — Collaboration service deploy

### Precondition

- internal flush security decision이 승인됐다.
- secret binding이 준비됐다.
- browser WSS가 application-level Firebase authentication을 사용함을 확인했다.

### Actions

```bash
gcloud run services replace \
  .staging-rendered/collaboration-server.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}"
```

browser WSS와 health route가 도달할 수 있도록 승인된 public invocation policy를 적용한다.

```bash
gcloud run services add-iam-policy-binding "${COLLABORATION_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member='allUsers' \
  --role='roles/run.invoker'
```

이 public binding은 internal route가 공개적으로 허용된다는 뜻이 아니다. internal route는 application token을 검증한다. 현재 single-service staging 제한을 deployment record에 남긴다.

### Verification

```bash
gcloud run services describe "${COLLABORATION_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}"
```

- `/healthz` 200
- invalid 또는 missing Firebase token의 WebSocket 연결 거부
- 유효 token이나 membership 없는 document 연결 거부
- internal flush missing/wrong token 401
- 승인된 internal token 요청 성공
- 3600초 timeout과 client reconnect 확인

### Stop condition

- unauthenticated WebSocket editing 가능
- internal token 없이 flush 가능
- secret log 노출
- snapshot Storage/Firestore permission denied

### Rollback

이전 healthy revision으로 traffic을 되돌린다. security failure이면 public traffic을 0으로 만들거나 service invocation binding을 제거하고 원인을 해결한다.

## 14. Phase 10 — Document API deploy

### Precondition

- worker와 Collaboration URL이 확정됐다.
- queues와 IAM이 준비됐다.
- secret version이 Collaboration과 일치한다.

### Actions

Document API rendered YAML에 다음 실제 URL을 넣는다.

```text
PARSE_WORKER_URL=https://<worker-run-app>/run/parse
EXPORT_WORKER_URL=https://<worker-run-app>/run/export
COLLABORATION_FLUSH_URL=https://<collaboration-run-app>
```

Cloud Tasks target에는 custom domain이 아니라 worker default `run.app` URL을 사용한다.

```bash
gcloud run services replace \
  .staging-rendered/document-api.service.yaml \
  --project="${PROJECT_ID}" \
  --region="${REGION}"
```

browser HTTPS 접근을 위해 public invocation policy를 적용한다. 실제 API authorization은 Firebase ID token과 document ACL이 담당한다.

```bash
gcloud run services add-iam-policy-binding "${DOCUMENT_API_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member='allUsers' \
  --role='roles/run.invoker'
```

### Verification

- `/healthz` 200
- Firebase token 없음 또는 invalid token 요청 거부
- member가 아닌 document 요청 거부
- owner/editor/viewer role matrix 일치
- parse/export task enqueue 성공
- internal flush wrong token failure
- direct worker dispatch false

### Stop condition

- API route가 authentication 없이 데이터 반환
- Cloud Tasks enqueue permission denied
- OIDC account actAs denied
- Collaboration flush unauthorized/timeout

### Rollback

이전 revision으로 traffic을 되돌린다. 잘못 enqueue된 task가 있으면 queue를 pause하고 task를 개별 조사한다.

## 15. Phase 11 — Firebase Rules, Indexes, Hosting

### Precondition

- Cloud Run service URLs가 healthy하다.
- Studio build environment가 staging 값만 포함한다.
- Firebase config와 Rules Emulator test가 성공한다.

### Actions

Studio production build를 생성한다.

```bash
cd rhwp-studio
npm ci
npm test
npm run build
cd ..
```

Firebase deploy target을 명시한다. 전체 deploy보다 단계별 deploy를 사용한다.

```bash
firebase deploy \
  --project="${PROJECT_ID}" \
  --only firestore:rules,firestore:indexes,storage

firebase deploy \
  --project="${PROJECT_ID}" \
  --only hosting
```

### Verification

- Google sign-in 성공
- approved authorized domain만 사용
- Firestore Rules 권한 matrix
- Storage upload boundary
- snapshot client read/write denial
- Hosting asset가 승인된 commit과 일치
- `VITE_COLLABORATION_URL=wss://...`
- `VITE_DOCUMENT_API_URL=https://...`

### Stop condition

- project alias에 의존해 다른 project에 deploy
- Hosting build에 production Firebase config 포함
- Rules test 실패
- snapshot client 접근 가능

### Rollback

- Hosting은 이전 release로 rollback한다.
- Rules와 indexes는 이전 검증 파일을 명시적으로 재배포한다.
- rollback도 project ID를 명시하고 승인 기록에 남긴다.

## 16. Service-level smoke verification

### 16.1 Health

```text
GET Collaboration /healthz -> 200
GET Document API /healthz -> 200
Worker direct unauthenticated POST -> 401/403
```

### 16.2 Cloud Tasks OIDC

1. 승인된 Document API route를 통해 작은 fixture parse task를 생성한다.
2. queue에서 task가 dispatch되는지 확인한다.
3. worker log에서 OIDC 인증된 request가 처리되는지 확인한다.
4. Firestore parse state와 Storage manifest를 확인한다.
5. task body 또는 log에 secret이 없는지 확인한다.

### 16.3 Collaboration

1. owner와 viewer 두 계정을 준비한다.
2. owner가 document를 연다.
3. viewer가 같은 document를 연다.
4. owner 변경이 viewer에게 수렴하는지 확인한다.
5. viewer의 keyboard, delete, paste, toolbar 명령이 거부되는지 확인한다.
6. Collaboration revision을 재시작하고 두 client가 reconnect하는지 확인한다.

### 16.4 Internal flush

- token 없음: 401
- wrong token: 401
- approved token: snapshot path 반환
- staging에서 identity token이 실질적인 두 번째 강제 경계가 아니라는 현재 제한을 기록

## 17. Firebase boundary verification

| 테스트 | 기대 결과 |
|---|---|
| 0 byte source upload | 거부 |
| 1 byte supported HWP | 허용 |
| 정확히 200 MiB supported HWP | 허용 |
| 200 MiB 초과 | 거부 |
| unsupported MIME | 거부 |
| editor image PNG/JPEG/WebP ≤20 MiB | 허용 |
| viewer image upload | 거부 |
| client snapshot read | 거부 |
| client snapshot write | 거부 |
| member export read | 허용 |
| non-member export read | 거부 |

## 18. Staging acceptance flow

아래 흐름을 순서대로 완료한다. 중간 실패 시 다음으로 넘어가지 않는다.

1. Firebase Google login
2. HWP upload
3. upload complete와 Cloud Tasks enqueue
4. worker parse
5. Studio document load
6. editor/viewer share link 생성과 수락
7. 두 browser realtime convergence
8. remote presence와 cursor 표시
9. viewer mutation rejection
10. Collaboration revision restart
11. reconnect와 snapshot recovery
12. export 요청과 internal flush
13. worker HWPX export
14. exported HWPX download
15. HWPX re-import와 본문·표 셀·지원 이미지 검증
16. Cloud Logging secret scan
17. queue retry/backlog 확인
18. budget과 notification channel 확인
19. acceptance evidence 저장

## 19. Rollback priority

### 19.1 즉시 traffic 중단

security 또는 data corruption 위험이 있으면 가장 먼저 신규 traffic을 중단한다.

- Cloud Run traffic을 이전 healthy revision으로 이동
- worker queue pause
- 필요 시 public Invoker binding 제거

### 19.2 Cloud Run revision rollback

각 service의 이전 healthy revision ID를 approval packet에 기록한다. revision을 삭제하지 않고 traffic만 이전한다.

### 19.3 Queue pause

```bash
gcloud tasks queues pause "${PARSE_QUEUE}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}"

gcloud tasks queues pause "${EXPORT_QUEUE}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
```

resume은 원인 해결과 사용자 승인 후 수행한다.

### 19.4 Firebase rollback

- Hosting: 이전 release
- Firestore/Storage Rules: 이전 검증 commit 파일 재배포
- Index: 삭제가 필요한 경우 impact를 검토하고 별도 승인

### 19.5 Secret rollback

- 문제 있는 새 version disable
- 이전 정상 version으로 두 service revision 교체
- 검증 완료 전 destroy 금지

### 19.6 Data cleanup

staging source, snapshots, exports와 Firestore documents 삭제는 irreversible 작업이다. retention 정책과 대상 목록을 사용자에게 보여주고 별도 승인 후 수행한다.

## 20. Post-deployment monitoring

배포 직후 최소 다음을 관찰한다.

```text
Cloud Run 4xx/5xx and latency
Collaboration reconnect failures
Cloud Tasks queue depth and oldest task age
Task retry count
Worker timeout
Firestore and Storage permission denied
Snapshot flush failure
Budget actual and forecast thresholds
```

초기 staging observation window 동안 오류가 없어도 비용과 열린 WebSocket 세션을 확인한다.

## 21. Deployment completion record

```text
Approval reference:
Approved by:
Deployed by:
Deployment date and time:

Project ID:
Project number:
Billing account:
Region:

Firebase Web App ID:
Authorized domains:
Firestore location:
Storage bucket and location:
Hosting site:

Artifact repository:
Collaboration image digest:
Document API image digest:
Document worker image digest:

Collaboration revision:
Document API revision:
Document worker revision:
Previous rollback revisions:

Parse queue configuration:
Export queue configuration:
Task dispatch deadline decision:

Internal secret name and version ID:
Internal flush security decision:

IAM review evidence:
Budget amount in KRW:
Budget thresholds:
Notification channel:
Data retention days:

Rules release/commit:
Hosting release:
Acceptance evidence:
Known issues:
Rollback point:
Cloud mutations performed:
```

Secret value, Firebase ID token, Authorization header 또는 service account key는 completion record에 기록하지 않는다.

## 22. 이번 문서 단계의 완료 조건

- 이 runbook과 architecture 설계 문서가 repository에 존재한다.
- 기존 template 수치와 service/queue 이름이 문서와 일치한다.
- 현재 구현의 dispatch deadline과 internal flush 제한이 명시됐다.
- PR은 Draft 상태다.
- 실제 Firebase/GCP mutation이 수행되지 않았다.
- 다음 작업이 machine-readable manifest와 read-only preflight validator로 제한됐다.
