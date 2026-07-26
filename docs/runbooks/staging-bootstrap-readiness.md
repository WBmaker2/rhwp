# rhwp Staging Bootstrap Readiness Gate

## 상태

- 적용 환경: `staging` only
- validator: `scripts/staging_bootstrap_readiness.py`
- input example: `deploy/staging/staging-bootstrap-readiness.example.json`
- report schema: `rhwp.staging-bootstrap-readiness/v1`
- cloud authentication: 없음
- cloud query: 없음
- GitHub Environment 생성·수정: 없음
- GCP/Firebase resource 생성·수정: 없음
- actual bootstrap packet 생성: readiness가 `ready-for-bootstrap-packet`일 때만 별도 실행

## 1. 목적

Readiness Gate는 실제 staging bootstrap packet을 만들기 전에 다음 증거가 하나의 검토 단위에 결합됐는지 검사한다.

1. 대상 repository, branch, PR, commit SHA
2. 필수 GitHub workflow 성공 결과
3. 운영 값 결정과 비용·개인정보·보안 확인
4. `staging-bootstrap` protected environment 설정 attestation
5. production 차단 목록
6. 월간 예산 `KRW`
7. Firebase Storage bucket의 planned/observed 구분
8. 기존 materializer가 수용할 수 있는 normalized values

이 도구는 GitHub나 Google Cloud API를 호출하지 않는다. 입력 JSON은 운영자가 확인한 사실에 대한 검토 증빙이며, validator는 그 내부 일관성만 검증한다.

## 2. 입력 파일

권장 실제 경로:

```text
deploy/staging/staging-bootstrap-readiness.local.json
```

이 파일에는 secret 원문을 넣지 않는다. 실제 파일을 repository에 커밋하지 않도록 로컬에서 관리한다.

형식은 다음 example을 복사한다.

```bash
cp deploy/staging/staging-bootstrap-readiness.example.json \
  deploy/staging/staging-bootstrap-readiness.local.json
```

Schema:

```text
rhwp.staging-bootstrap-readiness-input/v1
```

## 3. 필수 workflow gate

다음 네 workflow가 동일한 대상 commit에서 `completed/success`여야 한다.

```text
CI
CodeQL
Render Diff
Staging configuration
```

각 항목은 다음 필드를 가진다.

```json
{
  "name": "CI",
  "runNumber": 403,
  "commitSha": "40 lowercase hexadecimal characters",
  "status": "completed",
  "conclusion": "success"
}
```

`pending`, `queued`, `in_progress`, `failure`, `cancelled`, `skipped`, 다른 commit SHA, 중복 이름 또는 누락된 workflow가 있으면 readiness는 `blocked`다.

CI #403은 최초 기준 commit의 gate다. 이후 새 commit이 생기면 새 head의 workflow run 번호와 commit SHA로 evidence를 갱신해야 한다. 이전 commit의 성공 결과를 새 commit 승인에 재사용하지 않는다.

## 4. Governance gate

다음 값이 모두 충족돼야 한다.

```text
decisionStatus=approved
checklistComplete=true
billingOwnerConfirmed=true
budgetApprovedKrw=true
notificationRecipientsConfirmed=true
privacyRetentionReviewed=true
internalFlushExceptionAccepted=true
```

Readiness JSON의 boolean은 실제 검토를 대체하지 않는다. `docs/approvals/staging-bootstrap-values-decision.md`와 `docs/approvals/staging-bootstrap-values-checklist.md`를 검토한 운영자가 사실에 맞게 기록해야 한다.

## 5. Planned/observed resource 계약

Firebase Storage bucket은 다음 구조로 기록한다.

```json
{
  "storageBucket": {
    "planned": "rhwp-collaboration-staging-123.firebasestorage.app",
    "observed": null
  }
}
```

### Planned

`planned`는 bootstrap 전에 승인한 resource intent다.

- staging project ID에 종속돼야 한다.
- production bucket과 달라야 한다.
- `.firebasestorage.app` 또는 `.appspot.com` suffix를 사용한다.
- 아직 cloud에 존재한다고 주장하지 않는다.

### Observed

`observed`는 resource 생성 후 read-only evidence로 확인한 실제 값이다.

- bootstrap 전에는 `null`이 정상이다.
- validator는 planned 값을 observed로 복사하지 않는다.
- observed가 있으면 planned와 정확히 일치해야 한다.
- 다르면 자동 수정하지 않고 lifecycle을 중단한다.

### Effective

기존 materializer는 문자열 `firebase.storageBucket`을 요구한다. Readiness Gate는 다음 규칙으로 normalized values를 만든다.

```text
observed가 있으면 observed
observed가 null이면 planned
```

이 선택은 report의 `resources.firebaseStorageBucket.source`에 `planned` 또는 `observed`로 기록된다. 따라서 bootstrap packet에서 사용된 값의 provenance를 readiness report와 함께 검토해야 한다.

## 6. Protected environment evidence

입력의 `protectedEnvironment`는 GitHub 설정에 대한 operator attestation이다.

필수 조건:

```text
name=staging-bootstrap
configured=true
requiredReviewerCount>=1
branchRestricted=true
secretNames=[]
cloudCredentialsPresent=false
idTokenWrite=false
```

Environment variable 이름은 다음 아홉 개와 정확히 일치해야 한다.

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

`STAGING_STORAGE_BUCKET`에는 첫 bootstrap packet 생성 시 reviewed planned value를 등록한다. 리소스 생성 후 observed value가 확인되면 별도 evidence와 새 approval reference로 재검토한다.

Validator는 실제 GitHub Environment 존재 여부를 조회하거나 설정하지 않는다. 운영자는 GitHub UI의 Environment 화면을 확인하고 attestation을 작성한다.

## 7. 상태

### `blocked`

workflow, 값, governance, environment security 또는 planned/observed 일관성 중 하나라도 실패했다.

- CLI exit code: `1`
- readiness JSON/Markdown: 생성
- normalized values: 생성하지 않음
- actual packet: 금지

### `ready-for-protected-environment`

workflow, governance, 운영 값은 통과했지만 protected environment가 아직 설정되지 않았다.

- CLI exit code: `0`
- readiness JSON/Markdown: 생성
- normalized values: 생성하지 않음
- GitHub Environment 설정 검토가 다음 작업

### `ready-for-bootstrap-packet`

모든 검사와 environment attestation이 통과했다.

- CLI exit code: `0`
- readiness JSON/Markdown: 생성
- normalized materializer values: 생성
- static materialization과 bootstrap packet 생성 가능
- cloud resource 생성 또는 deployment 승인 의미는 아님

## 8. 실행

```bash
mkdir -p artifacts/readiness

python3 scripts/staging_bootstrap_readiness.py \
  --input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/readiness/staging-bootstrap-readiness.json \
  --markdown-output artifacts/readiness/staging-bootstrap-readiness.md \
  --normalized-values-output artifacts/readiness/staging-bootstrap-values-normalized.json
```

필수 출력 안전 계약:

```json
{
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "mutationCommands": []
}
```

## 9. 최초 actual bootstrap packet

Readiness status가 `ready-for-bootstrap-packet`일 때만 다음을 실행한다.

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --values artifacts/readiness/staging-bootstrap-values-normalized.json \
  --output artifacts/staging-manifest-bootstrap.json

python3 scripts/staging_preflight.py \
  --manifest artifacts/staging-manifest-bootstrap.json \
  --report artifacts/staging-preflight-static.json

python3 scripts/staging_approval_packet.py \
  --phase bootstrap \
  --manifest artifacts/staging-manifest-bootstrap.json \
  --static-report artifacts/staging-preflight-static.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

Packet과 함께 다음 readiness evidence를 보존한다.

```text
staging-bootstrap-readiness.json
staging-bootstrap-readiness.md
staging-bootstrap-values-normalized.json
```

## 10. 실제 값 확정이 필요한 항목

Repository가 자동 확정하지 않는 값:

```text
실제 staging project ID
실제 billing account
실제 production project ID 목록
planned Firebase Storage bucket
월간 예산 KRW
예산 알림 수신자
retention 일수
고유 approval reference
internal flush staging 예외 수용 여부
```

Observed Storage bucket은 infrastructure 생성 전에는 `null`로 유지한다.

## 11. 중단 조건

다음 중 하나라도 있으면 actual packet을 생성하지 않는다.

- 대상 commit workflow 미완료 또는 실패
- production-like project ID
- staging project가 forbidden 목록에 포함
- billing owner 또는 KRW budget 미확정
- notification 수신자 미확인
- retention 개인정보 검토 미완료
- protected environment reviewer·branch restriction 미설정
- environment secret 또는 cloud credential 존재
- `id-token: write` 존재
- planned/observed bucket 불일치
- secret-like key 또는 원문 값 포함
- `cloudMutationApproved=true`
- 별도 deployment 승인 전 `deploymentApproved=true`

## 12. 검증

```bash
python3 -m py_compile \
  scripts/staging_bootstrap_readiness.py \
  scripts/tests/test_staging_bootstrap_readiness.py

python3 -m unittest discover \
  -s scripts/tests \
  -p 'test_*.py' \
  -v

python3 scripts/validate_staging_config.py
```

이 검증은 cloud authentication, live query, GitHub Environment mutation, resource 생성, image build/push 또는 deployment를 수행하지 않는다.
