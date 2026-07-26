# rhwp Staging Manifest and Read-only Preflight

## 상태

- 적용 환경: staging only
- machine-readable manifest: `deploy/staging/staging-manifest.json`
- validator: `scripts/staging_preflight.py`
- GitHub Actions: `.github/workflows/staging-config-validate.yml`
- 실제 Firebase/GCP 리소스 변경: 없음
- live cloud 조회 실행: 아직 수행하지 않음

이 문서는 staging resource 생성·변경·배포를 승인하는 문서가 아니다. preflight는 현재 repository 계약과, 승인 후 선택적으로 조회한 실제 cloud 상태의 차이를 보고할 뿐이다.

## 1. 해결된 timeout 계약

Document API가 Cloud Tasks HTTP task를 생성할 때 다음 값을 명시한다.

```json
{
  "dispatchDeadline": {
    "seconds": 900
  }
}
```

동일 값은 다음 위치에서 하나의 계약으로 검증된다.

```text
services/document-api/src/firebase-adapters.ts
services/document-api/src/runtime-environment.ts
deploy/cloudrun/document-api.service.yaml
firebase/staging.env.example
deploy/staging/staging-manifest.json
scripts/staging_preflight.py
```

환경 변수:

```text
TASK_DISPATCH_DEADLINE_SECONDS=900
```

허용 범위는 Cloud Tasks HTTP task 계약에 맞춰 15초부터 1,800초까지이며, staging manifest에서는 worker Cloud Run timeout과 동일한 900초만 허용한다.

## 2. Machine-readable manifest

Manifest schema version:

```text
rhwp.staging/v1
```

Manifest에는 다음 범주가 포함된다.

- staging project ID·number·billing account와 금지 project 목록
- `asia-northeast3` region과 Firebase 데이터 위치
- Firebase Web App, Auth domain, Firestore, Storage, Hosting 식별자
- Artifact Registry repository
- Collaboration, Document API, Document worker Cloud Run runtime
- parse/export Cloud Tasks queue, retry, rate limit, 900초 deadline
- 전용 service account 4개
- Secret Manager secret 이름과 version reference
- 최소 권한 IAM binding 계획
- 원화 예산 금액 placeholder와 50%·80%·100% threshold
- retention, approval reference와 rollback revision placeholder
- `cloudMutationApproved=false`

### Placeholder 원칙

아직 승인되지 않은 값은 빈 문자열이나 예시 credential 대신 `${PLACEHOLDER}` 형식으로 둔다.

```json
{
  "project": {
    "id": "${FIREBASE_STAGING_PROJECT_ID}"
  },
  "budget": {
    "currency": "KRW",
    "amount": "${STAGING_MONTHLY_BUDGET_KRW}"
  }
}
```

Secret 원문, access token, service-account key JSON과 Firebase Admin credential은 manifest에 넣지 않는다.

## 3. Static preflight

Repository 파일만 읽으며 cloud CLI를 호출하지 않는다.

```bash
python3 scripts/staging_preflight.py \
  --manifest deploy/staging/staging-manifest.json \
  --report artifacts/staging-preflight-static.json
```

검증 항목:

- manifest schema와 staging-only safety flag
- production-like project ID와 금지 project ID
- Cloud Run service name, ingress, CPU, memory, timeout, concurrency, scale
- parse/export queue name, location, retry, rate limit, deadline
- broad `roles/owner`, `roles/editor` 금지
- secret value field 금지
- budget currency `KRW`와 threshold
- Cloud Run YAML, staging environment와 manifest 정합성
- worker timeout 900초와 concurrency 1

성공 report 핵심 계약:

```json
{
  "mode": "static",
  "status": "pass",
  "cloudQueries": [],
  "mutationCommands": []
}
```

기존 정적 validator도 manifest를 함께 검증한다.

```bash
python3 scripts/validate_staging_config.py
```

## 4. Live read-only preflight

### 실행 게이트

다음 조건을 모두 만족하기 전에는 실행하지 않는다.

1. 실제 staging project ID와 forbidden project ID가 manifest에 확정됐다.
2. 조회 전용 identity와 최소 조회 IAM이 준비됐다.
3. GitHub `staging-preflight` environment 보호 규칙이 설정됐다.
4. `GCP_WORKLOAD_IDENTITY_PROVIDER`와 `GCP_PREFLIGHT_SERVICE_ACCOUNT` repository secret이 구성됐다.
5. 사용자가 live read-only 조회 범위와 대상 project를 확인했다.

Live mode는 다음처럼 실행한다.

```bash
python3 scripts/staging_preflight.py \
  --manifest deploy/staging/staging-manifest.json \
  --live \
  --report artifacts/staging-preflight-live.json
```

현재 placeholder manifest로 `--live`를 실행하면 validator가 cloud command 실행 전에 중단한다.

### 허용된 조회 범위

Validator는 정확한 command prefix allowlist를 적용한다.

```text
gcloud auth list
gcloud config get-value
gcloud projects describe
gcloud billing projects describe
gcloud services list --enabled
gcloud run services list/describe
gcloud tasks queues list/describe
gcloud secrets list/describe
gcloud iam service-accounts list/describe
gcloud projects get-iam-policy
gcloud artifacts repositories list/describe
firebase projects:list
```

다음 mutation token은 command 실행 전에 거부한다.

```text
create
delete
deploy
enable
disable
update
add-iam-policy-binding
remove-iam-policy-binding
set-iam-policy
```

Shell control character와 pipeline·redirect도 허용하지 않는다.

### Report 내용

Live report는 다음을 분리해 기록한다.

- 이미 존재하는 승인 대상 리소스
- 생성 또는 활성화가 필요할 것으로 예상되는 리소스
- 예상하지 못한 `rhwp` prefix 리소스
- 활성 account/project 불일치
- project·billing·enabled API·Cloud Run·Tasks·Secret·service account·IAM·Artifact Registry·Firebase project 조회 결과

Credential, access token, ID token, Authorization header, private key와 secret payload는 report에서 제거하거나 `[REDACTED]`로 치환한다.

## 5. GitHub Actions 사용

Workflow: `Staging configuration`

### Pull request

PR에서는 다음 static 단계만 실행한다.

1. Python unit tests
2. 기존 staging configuration validator
3. static preflight JSON report 생성
4. `staging-preflight-report-static` artifact 업로드

Live job은 skipped 상태여야 한다.

### workflow_dispatch

Actions 화면에서 `Staging configuration` workflow를 선택하고 다음 input을 사용한다.

```text
live_check=false
manifest_path=deploy/staging/staging-manifest.json
```

이 값은 cloud 인증 없이 static report만 다시 생성한다.

Live 조회가 승인된 경우에만 다음을 선택한다.

```text
live_check=true
manifest_path=deploy/staging/staging-manifest.json
```

이 경우 workflow는 `staging-preflight` environment를 사용하고 Workload Identity Federation으로 인증한다. 장기 service-account key는 사용하지 않는다.

생성 artifact:

```text
staging-preflight-report-static
staging-preflight-report-live
```

Workflow에는 deploy 또는 cloud mutation job이 없다.

## 6. Live report 이후 승인 패킷

Live report를 얻은 뒤에도 자동으로 resource를 생성하지 않는다. 다음 내용을 사용자에게 제시한 후 별도의 명시적 승인을 받아야 한다.

1. project ID, project number, billing account
2. region, Firestore와 Storage location
3. 생성·변경·활성화 대상 리소스 전체
4. service account별 IAM binding
5. secret 이름·version·access principal, secret 값 제외
6. queue retry·rate·concurrency·deadline
7. Cloud Run public/private policy
8. Collaboration internal flush의 staging 보안 제한
9. 월간 예산 원화 금액, threshold와 notification channel
10. image digest와 rollback revision
11. 예상 과금 서비스와 삭제·rollback 절차
12. staging acceptance test 목록

## 7. 현재 완료 경계

완료:

- task payload `dispatchDeadline=900s`
- manifest schema와 repository manifest
- static validator와 unit tests
- 선택적 live read-only validator
- static/live JSON report 형식
- GitHub Actions `workflow_dispatch`
- PR static report artifact 생성

미수행:

- 실제 staging project 값 확정
- WIF 또는 조회 IAM 생성·변경
- live preflight 실행
- billing·API·IAM·Secret·queue·Cloud Run·Firebase mutation
- image build/push
- staging deployment와 acceptance test
