# rhwp Staging Bootstrap Inputs

## 상태

- 적용 범위: staging bootstrap approval only
- materializer: `scripts/staging_bootstrap_materializer.py`
- example values: `deploy/staging/staging-bootstrap-values.example.json`
- protected environment contract: `staging-bootstrap`
- 실제 GitHub environment 생성·변경: 수행하지 않음
- 실제 GCP/Firebase 리소스 생성·변경: 수행하지 않음
- cloud authentication 또는 live preflight: 수행하지 않음

## 1. 목적

Repository의 `deploy/staging/staging-manifest.json`은 공유 가능한 설계 계약이므로 운영 project, billing, 예산과 승인 참조를 placeholder로 유지한다.

Staging Bootstrap Input Materializer는 다음 두 입력을 결합해 임시 bootstrap manifest를 생성한다.

```text
deploy/staging/staging-manifest.json
+ approved non-secret bootstrap values
= artifacts/staging-manifest-bootstrap.json
```

생성된 manifest는 기존 static preflight와 bootstrap approval packet generator에 전달된다. Materializer는 cloud CLI, subprocess, 네트워크 요청 또는 resource mutation을 실행하지 않는다.

## 2. Values schema

Schema version:

```text
rhwp.staging-bootstrap-values/v1
```

허용되는 전체 구조는 다음과 같다.

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-values/v1",
  "project": {
    "id": "rhwp-collaboration-staging-123",
    "billingAccount": "000000-111111-222222",
    "forbiddenProjectIds": [
      "rhwp-production"
    ]
  },
  "firebase": {
    "storageBucket": "rhwp-collaboration-staging-123.firebasestorage.app"
  },
  "budget": {
    "amountKrw": 50000,
    "notificationChannels": [
      "billing-admins@example.com"
    ]
  },
  "operations": {
    "dataRetentionDays": 14,
    "approvalReference": "approval-2026-07-26-001",
    "internalFlushSecurityDecision": "mvp-staging-internal-token"
  }
}
```

예시 값은 테스트와 형식 설명용이며 실제 staging 운영 값이 아니다.

## 3. 필드 검증

### 3.1 Project

- `project.id`는 유효한 GCP project ID 형식이어야 한다.
- `production` 또는 독립된 `prod` 구간을 포함한 project ID는 거부한다.
- `project.id`는 `forbiddenProjectIds`에 포함될 수 없다.
- `forbiddenProjectIds`는 중복 없는 concrete 문자열 목록이어야 한다.
- `billingAccount`는 `XXXXXX-XXXXXX-XXXXXX` 형식이어야 한다.

### 3.2 Firebase Storage

`firebase.storageBucket`은 project ID로 시작하고 다음 suffix 중 하나를 사용해야 한다.

```text
.firebasestorage.app
.appspot.com
```

Bucket은 Firebase project 생성 방식에 따라 suffix가 달라질 수 있으므로 자동 추측하지 않고 명시적으로 승인한다.

### 3.3 Budget

- 통화는 기존 manifest의 `KRW`를 유지한다.
- `amountKrw`는 0보다 큰 정수여야 한다.
- boolean, 문자열, 소수와 쉼표가 포함된 금액은 거부한다.
- 원화 값을 환산하거나 변환하지 않는다.
- notification channel은 비어 있지 않은 문자열 목록이어야 한다.

### 3.4 Operations

- `dataRetentionDays`는 0보다 큰 정수여야 한다.
- `approvalReference`는 비어 있지 않은 문자열이어야 한다.
- 현재 허용된 internal flush 결정은 `mvp-staging-internal-token`뿐이다.
- `cloudMutationApproved`는 values 입력으로 받을 수 없으며 결과에서도 항상 `false`다.

## 4. 허용되지 않는 입력

Unknown key는 모두 fail-closed로 거부한다. 다음 항목은 values schema에 추가할 수 없다.

```text
secret 원문
token
credential
password
private key
authorization header
service-account key file
cloudMutationApproved
IAM role 또는 resource 변경
Cloud Run runtime 변경
Cloud Tasks retry·rate·deadline 변경
Firebase Web App ID
container image 또는 digest
rollback revision
```

민감 key가 발견되면 오류에는 key path만 기록하고 값은 기록하지 않는다.

## 5. 자동 파생 값

Project ID를 기준으로 다음 값을 결정적으로 생성한다.

```text
firebase.authDomain=<project-id>.firebaseapp.com
firebase.authorizedDomains=[<project-id>.firebaseapp.com, <project-id>.web.app]
firebase.hostingSite=<project-id>
cloudRun.collaboration.serviceAccount=rhwp-collaboration-staging@<project-id>.iam.gserviceaccount.com
cloudRun.documentApi.serviceAccount=rhwp-document-api-staging@<project-id>.iam.gserviceaccount.com
cloudRun.documentWorker.serviceAccount=rhwp-document-worker-staging@<project-id>.iam.gserviceaccount.com
tasks.callerServiceAccount=rhwp-tasks-staging@<project-id>.iam.gserviceaccount.com
```

동일한 service account와 bucket 값으로 IAM principal·resource placeholder도 치환한다. IAM role, resource 종류와 runtime 계약은 원본 manifest에서 변경하지 않는다.

## 6. Bootstrap 이후에도 deferred인 값

Materializer 결과에는 다음 resource-derived 값만 placeholder로 남을 수 있다.

```text
manifest.project.number
manifest.firebase.webAppId
manifest.firebase.apiKeyReference
manifest.cloudRun.collaboration.image
manifest.cloudRun.collaboration.digest
manifest.cloudRun.documentApi.image
manifest.cloudRun.documentApi.digest
manifest.cloudRun.documentWorker.image
manifest.cloudRun.documentWorker.digest
manifest.tasks.parse.targetUrl
manifest.tasks.export.targetUrl
manifest.operations.rollbackRevisionIds[0]
manifest.operations.rollbackRevisionIds[1]
manifest.operations.rollbackRevisionIds[2]
```

Cloud Tasks target URL은 private document worker endpoint가 존재한 뒤 확정된다. Deployment approval에서는 위 placeholder도 모두 허용되지 않는다.

## 7. 로컬 파일 실행

실제 값 파일은 다음 경로를 권장한다.

```text
deploy/staging/staging-bootstrap-values.local.json
```

이 경로는 `.gitignore`에 포함되어 있다.

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --values deploy/staging/staging-bootstrap-values.local.json \
  --output artifacts/staging-manifest-bootstrap.json
```

성공 출력에는 project ID, output path, deferred path와 다음 안전 계약이 포함된다.

```json
{
  "mutationCommands": []
}
```

검증 실패 시 final output과 `.tmp` 파일을 남기지 않는다.

## 8. Environment 실행

Materializer가 읽는 environment variable은 다음 9개뿐이다.

```text
STAGING_PROJECT_ID
STAGING_BILLING_ACCOUNT
STAGING_FORBIDDEN_PROJECT_IDS_JSON
STAGING_STORAGE_BUCKET
STAGING_MONTHLY_BUDGET_KRW
STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON
STAGING_DATA_RETENTION_DAYS
STAGING_APPROVAL_REFERENCE
STAGING_INTERNAL_FLUSH_DECISION
```

목록 값은 JSON array 문자열로 입력한다.

```text
STAGING_FORBIDDEN_PROJECT_IDS_JSON=["rhwp-production"]
STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON=["billing-admins@example.com"]
```

실행:

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --from-environment \
  --output artifacts/staging-manifest-bootstrap.json
```

Materializer는 전체 environment를 열거하거나 출력하지 않는다.

## 9. GitHub protected environment 계약

Workflow는 `staging-bootstrap` environment를 참조한다. 실제 environment 생성과 값 입력은 repository 운영자가 별도로 승인한 뒤 GitHub UI에서 수행해야 한다.

권장 설정:

- environment name: `staging-bootstrap`
- required reviewer: staging 운영 승인자
- deployment branch restriction: `feat/firebase-collaboration-mvp-v1` 검증 중에는 해당 branch 또는 보호된 정책 적용
- environment secrets: 없음
- cloud identity 또는 WIF: 없음
- 위 9개 값을 environment variables로 등록

Bootstrap job은 다음 권한만 요청한다.

```yaml
permissions:
  contents: read
```

`id-token: write`, GCP authentication, gcloud setup과 Firebase CLI 설치는 bootstrap job에 포함되지 않는다.

## 10. Workflow 순서

`approval_phase=bootstrap`, `live_check=false` 수동 실행에서:

```text
protected environment review
→ repository checkout
→ approved vars로 bootstrap manifest materialize
→ materialized manifest static preflight
→ bootstrap JSON/Markdown packet 생성
→ artifact 업로드
```

Artifact `staging-approval-packet-bootstrap`에는 다음 파일이 포함된다.

```text
staging-manifest-bootstrap.json
staging-preflight-static.json
staging-approval-packet.json
staging-approval-packet.md
```

## 11. 실제 최초 packet 생성 조건

실제 최초 bootstrap approval packet은 다음 값이 모두 확정된 뒤에만 생성할 수 있다.

1. staging project ID
2. billing account ID
3. forbidden production project ID 목록
4. Firebase storage bucket 이름
5. 월간 예산 원화 금액
6. 예산 notification channel 목록
7. data retention 일수
8. approval reference
9. internal flush security 결정

현재 구현 과정에서는 이 실제 값들을 추측하거나 입력하지 않았으며, `staging-bootstrap` environment도 생성하지 않았다. Example values로 생성되는 결과는 deterministic test evidence일 뿐 실제 staging 승인 패킷이 아니다.

## 12. 검증

```bash
python3 -m py_compile \
  scripts/staging_bootstrap_materializer.py \
  scripts/staging_approval_packet.py \
  scripts/tests/test_staging_bootstrap_materializer.py

python3 -m unittest discover \
  -s scripts/tests \
  -p 'test_*.py' \
  -v

python3 scripts/validate_staging_config.py
```

이 검증에는 cloud authentication, live query, resource 생성·변경, image build/push 또는 배포가 포함되지 않는다.
