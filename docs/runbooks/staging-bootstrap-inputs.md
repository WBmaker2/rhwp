# rhwp Staging Bootstrap Inputs

## 상태

- 적용 범위: staging bootstrap approval only
- readiness gate: `scripts/staging_bootstrap_readiness.py`
- materializer: `scripts/staging_bootstrap_materializer.py`
- readiness example: `deploy/staging/staging-bootstrap-readiness.example.json`
- legacy materializer example: `deploy/staging/staging-bootstrap-values.example.json`
- protected environment contract: `staging-bootstrap`
- 실제 GitHub Environment 생성·변경: 수행하지 않음
- 실제 GCP/Firebase resource 생성·변경: 수행하지 않음
- cloud authentication 또는 live preflight: 수행하지 않음

## 1. 입력 흐름

Actual bootstrap은 readiness input을 직접 기존 materializer에 전달하지 않는다.

```text
reviewed readiness input
→ readiness report
→ normalized rhwp.staging-bootstrap-values/v1
→ staging manifest materialization
→ static preflight
→ bootstrap approval packet
```

Readiness Gate가 packet-ready가 아니면 normalized values를 생성하지 않는다.

## 2. Readiness input

Schema:

```text
rhwp.staging-bootstrap-readiness-input/v1
```

주요 구성:

```text
repository
workflows
governance
protectedEnvironment
values
```

실제 로컬 파일 권장 경로:

```text
deploy/staging/staging-bootstrap-readiness.local.json
```

이 파일은 secret 원문을 포함하지 않으며 Git에 커밋하지 않는다.

## 3. Planned/observed Storage

Readiness input은 Storage bucket을 다음처럼 분리한다.

```json
{
  "firebase": {
    "storageBucket": {
      "planned": "<project-id>.firebasestorage.app",
      "observed": null
    }
  }
}
```

- `planned`: bootstrap 전 승인한 resource intent
- `observed`: resource 생성 후 read-only evidence로 확인한 실제 값
- infrastructure 전 `observed=null` 유지
- planned 값을 observed로 복사하지 않음
- observed가 존재하면 planned와 일치해야 함
- 불일치 시 자동 수정 없이 중단

기존 materializer는 문자열 bucket을 요구하므로 readiness normalizer가 provenance를 기록한 뒤 effective 값을 legacy schema로 변환한다.

```text
observed가 있으면 observed
observed가 null이면 planned
```

## 4. Normalized materializer values

Schema:

```text
rhwp.staging-bootstrap-values/v1
```

형식:

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-values/v1",
  "project": {
    "id": "rhwp-collaboration-staging-123",
    "billingAccount": "000000-111111-222222",
    "forbiddenProjectIds": ["rhwp-production"]
  },
  "firebase": {
    "storageBucket": "rhwp-collaboration-staging-123.firebasestorage.app"
  },
  "budget": {
    "amountKrw": 50000,
    "notificationChannels": ["billing-admins@example.com"]
  },
  "operations": {
    "dataRetentionDays": 14,
    "approvalReference": "staging-bootstrap-approval-2026-07-26-001",
    "internalFlushSecurityDecision": "mvp-staging-internal-token"
  }
}
```

위 값은 문서 형식 예시이며 actual staging 운영 값이 아니다.

## 5. Readiness 필수 workflow

동일한 target commit에서 다음 workflow가 모두 `completed/success`여야 한다.

```text
CI
CodeQL
Render Diff
Staging configuration
```

새 commit이 생성되면 이전 commit의 workflow evidence를 재사용하지 않는다.

## 6. Governance evidence

다음 항목이 모두 실제 검토 후 승인돼야 한다.

```text
decisionStatus=approved
checklistComplete=true
billingOwnerConfirmed=true
budgetApprovedKrw=true
notificationRecipientsConfirmed=true
privacyRetentionReviewed=true
internalFlushExceptionAccepted=true
```

근거 문서:

```text
docs/approvals/staging-bootstrap-values-decision.md
docs/approvals/staging-bootstrap-values-checklist.md
```

## 7. Protected Environment evidence

Environment name:

```text
staging-bootstrap
```

필수 attestation:

```text
configured=true
requiredReviewerCount>=1
branchRestricted=true
secretNames=[]
cloudCredentialsPresent=false
idTokenWrite=false
```

Environment variable 이름은 다음 9개와 정확히 일치한다.

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

First bootstrap packet에서 `STAGING_STORAGE_BUCKET`은 reviewed planned value다. Observed value는 infrastructure 후 별도 evidence와 새 approval reference로 검토한다.

Validator는 GitHub Environment를 조회하거나 설정하지 않는다. Evidence는 GitHub UI를 확인한 운영자의 attestation이다.

## 8. 금지 입력

다음 값을 readiness, normalized values, packet 또는 approval artifact에 넣지 않는다.

```text
access token
ID token
Authorization header
credential
password
private key
service-account key JSON
secret 원문
Firebase Web API key 원문
cloudMutationApproved=true
deploymentApproved=true
```

Unknown key는 fail-closed로 거부한다. 오류는 key path만 기록하고 secret 값을 출력하지 않는다.

## 9. Readiness 실행

```bash
cp deploy/staging/staging-bootstrap-readiness.example.json \
  deploy/staging/staging-bootstrap-readiness.local.json

mkdir -p artifacts/readiness

python3 scripts/staging_bootstrap_readiness.py \
  --input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/readiness/staging-bootstrap-readiness.json \
  --markdown-output artifacts/readiness/staging-bootstrap-readiness.md \
  --normalized-values-output artifacts/readiness/staging-bootstrap-values-normalized.json
```

상태:

- `blocked`: exit 1, normalized values 없음
- `ready-for-protected-environment`: exit 0, normalized values 없음
- `ready-for-bootstrap-packet`: exit 0, normalized values 생성

## 10. Materializer 실행

Readiness가 `ready-for-bootstrap-packet`일 때만 실행한다.

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --values artifacts/readiness/staging-bootstrap-values-normalized.json \
  --output artifacts/staging-manifest-bootstrap.json
```

Materializer는 다음을 보장한다.

- source manifest 불변
- project, billing, budget, retention, approval reference 반영
- deterministic Firebase domains와 service accounts
- `operations.cloudMutationApproved=false`
- 허용된 resource-derived placeholder만 잔존
- `mutationCommands=[]`
- subprocess 또는 cloud CLI 없음

## 11. Static preflight와 packet

```bash
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

Readiness evidence, normalized values, materialized manifest, static report와 packet을 하나의 approval reference 아래 함께 보존한다.

## 12. 실제 값 확정이 필요한 항목

```text
actual staging project ID
actual billing account
production project ID 목록
planned Storage bucket
월간 예산 KRW
notification recipients
retention 일수
고유 approval reference
internal flush staging 예외 수용 여부
```

Repository는 이 값들을 추측하거나 자동 결정하지 않는다.

## 13. 중단 경계

다음 상태에서는 actual packet을 생성하지 않는다.

- readiness status가 `ready-for-bootstrap-packet`이 아님
- target workflow 미완료 또는 실패
- governance 미승인
- protected environment evidence 미완료
- production project 또는 bucket 참조
- planned/observed Storage 불일치
- secret-like key 또는 원문 값 발견
- `cloudMutationApproved=true`
- `deploymentApproved=true`

## 14. 상세 문서

```text
docs/runbooks/staging-bootstrap-readiness.md
docs/approvals/staging-bootstrap-values-decision.md
docs/approvals/staging-bootstrap-values-checklist.md
docs/runbooks/staging-approval-packet.md
```
