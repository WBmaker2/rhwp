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
release_metadata_path=deploy/staging/staging-release-metadata.json
```

이 경우 workflow는 `staging-preflight` environment를 사용하고 Workload Identity Federation으로 인증한다. 장기 service-account key는 사용하지 않는다.
인증 전에 보호 Environment의 9개 승인 값을 `staging_bootstrap_materializer.py --from-environment`으로
`artifacts/staging-manifest-deployment-preflight-bootstrap.json`에 materialize한다. 이어서 동일 source
commit에 결합된 release metadata를 `scripts/staging_deployment_manifest.py`로 검증해
`artifacts/staging-manifest-deployment-preflight.json`을 만든다. static preflight, live read-only
preflight, deployment packet은 이 최종 manifest만 입력으로 사용한다. release metadata가 없으면
packet을 만들지 않고 인증 전에 fail-closed한다. 이 단계에는 build, push, deploy 또는 cloud mutation
command가 없다.

단, bootstrap materializer가 남기는 image digest, Firebase Web App ID, worker URL과 rollback revision은
배포 packet 전용 release metadata가 확정되기 전까지 미해결 상태다. 이 값을 임의로 채우지 않는다.
`scripts/staging_deployment_manifest.py`는 동일 source commit에 결합된 release metadata만 받아
승인된 Artifact Registry의 서비스별 canonical repository, lowercase SHA-256 digest, concrete task URL과
rollback ID를 검증하고 최종 deployment manifest를 만든다. metadata가 없거나 placeholder가 남으면
deployment packet 생성은 fail-closed로 중단된다.
workflow는 metadata의 `workflowRunId`와 `workflowRunAttempt`를 GitHub Actions read-only API로 다시
조회해 실제 성공한 run의 `headSha`가 현재 checkout의 `GITHUB_SHA`와 같은지도 확인한다. 이 관찰이
일치하지 않으면 WIF 인증 전에 중단한다.

`release metadata`는 이미지 build/push evidence가 확정된 뒤 별도 승인 경계에서 생성되어야 한다.
deployment packet이 image digest를 요구하므로, deployment approval 뒤에 처음으로 build/push를 하는
순서는 유효하지 않다. 먼저 immutable release-candidate evidence를 만들고, 그 source-commit-bound
metadata를 이 live preflight에 입력한 뒤 packet을 사람에게 제시한다. 이 구현에서는 build/push와
deployment를 실행하지 않는다.

metadata의 root 계약은 `rhwp.staging-deployment-release/v1`이며 다음 키만 허용한다.

```text
schemaVersion, sourceCommitSha, workflowRunId, workflowRunAttempt, deploymentStage,
project.number, firebase.webAppId, firebase.apiKeyReference,
cloudRun.collaboration|documentApi|documentWorker.{image,digest},
tasks.parse|export.targetUrl, rollbackRevisionIds[3]
```

`deploymentStage`는 `initial` 또는 `upgrade`다. 최초 배포인 `initial`에서는 이전 Cloud Run
revision이 없을 수 있으므로 `rollbackRevisionIds`를 `[null, null, null]`로 명시한다. 기존 배포를
교체하는 `upgrade`에서는 실제 revision ID 세 개를 요구하며 placeholder·임의 문자열·null을 허용하지
않는다. 이 구분 없이 rollback ID를 추측해 metadata를 만드는 것은 금지한다.

`apiKeyReference`는 참조 이름만 허용하고 Firebase API key 원문은 거부한다. metadata 원문은
deployment packet artifact에 업로드하지 않으며, 검증된 최종 manifest만 artifact에 포함한다.

생성 artifact:

```text
staging-preflight-report-static
staging-preflight-report-live
staging-approval-packet-deployment
staging-manifest-deployment-preflight
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
