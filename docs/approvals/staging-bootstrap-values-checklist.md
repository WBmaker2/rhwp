# Staging Bootstrap 실제 값 및 Readiness 확정 체크리스트

이 체크리스트는 `docs/approvals/staging-bootstrap-values-decision.md`와 함께 사용한다. 모든 필수 항목을 확인하기 전에는 actual bootstrap packet, infrastructure mutation, live preflight 또는 deployment를 진행하지 않는다.

## A. 저장소와 승인 범위

- [ ] 저장소가 `WBmaker2/rhwp`다.
- [ ] 브랜치가 `feat/firebase-collaboration-mvp-v1`다.
- [ ] PR #1이 Draft·미병합 상태다.
- [ ] manifest가 `deploy/staging/staging-manifest.json`이다.
- [ ] manifest environment가 `staging`이다.
- [ ] `operations.cloudMutationApproved=false`다.
- [ ] `deploymentApproved=false`다.
- [ ] actual local readiness 파일이 Git에 커밋되지 않는다.
- [ ] token·password·credential·private key·service-account key를 입력하지 않는다.

## B. 대상 commit과 workflow evidence

- [ ] 대상 commit SHA를 확정했다.
- [ ] readiness repository commit SHA와 각 workflow commit SHA가 같다.
- [ ] CI가 `completed/success`다.
- [ ] CodeQL이 `completed/success`다.
- [ ] Render Diff가 `completed/success`다.
- [ ] Staging configuration이 `completed/success`다.
- [ ] 네 workflow 이름이 중복되지 않는다.
- [ ] 새 commit 이후 이전 run evidence를 재사용하지 않는다.

기록:

```text
TARGET_COMMIT_SHA=
CI_RUN_NUMBER=
CODEQL_RUN_NUMBER=
RENDER_DIFF_RUN_NUMBER=
STAGING_CONFIGURATION_RUN_NUMBER=
```

## C. Staging Project ID

- [ ] 실제 `STAGING_PROJECT_ID`를 확정했다.
- [ ] GCP project ID 형식을 만족한다.
- [ ] `staging`이 포함된다.
- [ ] `prod` 또는 `production` 구간이 없다.
- [ ] production project ID와 다르다.
- [ ] 다른 서비스 또는 개인 실험 프로젝트를 재사용하지 않는다.
- [ ] GCP 계정에서 ID 사용 가능 여부를 확인했다.
- [ ] Firebase Hosting site와 service account naming에 적합하다.

기록:

```text
STAGING_PROJECT_ID=
```

## D. Billing Account와 비용 책임

- [ ] 실제 `STAGING_BILLING_ACCOUNT`를 확정했다.
- [ ] 형식이 `XXXXXX-XXXXXX-XXXXXX`다.
- [ ] staging 비용을 부담할 billing account다.
- [ ] billing account 사용 권한 보유자를 확인했다.
- [ ] 비용 책임자를 확인했다.
- [ ] 월간 KRW 예산 승인자를 확인했다.
- [ ] 예산은 비용 차단이 아니라 알림 장치임을 이해했다.

마스킹 기록:

```text
STAGING_BILLING_ACCOUNT=XXXXXX-******-XXXXXX
```

## E. Production 차단 목록

- [ ] 실제 production project ID 전체를 확인했다.
- [ ] `forbiddenProjectIds`는 비어 있지 않다.
- [ ] staging project ID를 포함하지 않는다.
- [ ] 중복 ID가 없다.
- [ ] 모든 값이 placeholder가 아닌 concrete ID다.

형식:

```json
["production-project-id"]
```

Environment 형식:

```text
STAGING_FORBIDDEN_PROJECT_IDS_JSON=["production-project-id"]
```

## F. Firebase 위치와 Planned Storage bucket

- [ ] Firestore location `asia-northeast3`을 확인했다.
- [ ] Storage location `asia-northeast3`을 확인했다.
- [ ] planned bucket을 확정했다.
- [ ] planned bucket이 staging project ID로 시작한다.
- [ ] suffix가 `.firebasestorage.app` 또는 `.appspot.com`이다.
- [ ] production bucket과 다르다.
- [ ] planned 값이 아직 실제 resource 존재를 의미하지 않음을 이해했다.
- [ ] first bootstrap packet의 `STAGING_STORAGE_BUCKET`에는 planned 값을 사용한다.

기록:

```text
PLANNED_STORAGE_BUCKET=
STAGING_STORAGE_BUCKET=<PLANNED_STORAGE_BUCKET>
```

## G. Observed Storage bucket

- [ ] infrastructure 생성 전 `observed`를 `null`로 유지했다.
- [ ] planned 값을 observed로 복사하지 않았다.
- [ ] observed 값은 cloud resource 생성 후 read-only evidence로만 기록한다.
- [ ] observed가 생기면 planned와 정확히 일치하는지 확인한다.
- [ ] 불일치 시 자동 수정하지 않고 새 approval reference로 재검토한다.

Bootstrap 전 기록:

```json
{
  "planned": "<planned-bucket>",
  "observed": null
}
```

Infrastructure 후 기록:

```json
{
  "planned": "<planned-bucket>",
  "observed": "<read-only-observed-bucket>"
}
```

## H. 월간 예산과 알림

- [ ] `STAGING_MONTHLY_BUDGET_KRW`를 확정했다.
- [ ] 쉼표 없는 양의 정수다.
- [ ] 통화는 `KRW`다.
- [ ] threshold는 50%·80%·100%다.
- [ ] 최소 1개의 notification recipient가 있다.
- [ ] 모든 recipient가 실제 수신 가능하다.
- [ ] 개인정보와 불필요한 개인 주소 노출을 검토했다.

기록:

```text
STAGING_MONTHLY_BUDGET_KRW=
STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON=[]
```

## I. 데이터 보존과 개인정보

- [ ] `STAGING_DATA_RETENTION_DAYS`를 확정했다.
- [ ] 양의 정수다.
- [ ] 장애 재현에 필요한 최소 기간이다.
- [ ] 학교·조직 개인정보 정책과 충돌하지 않는다.
- [ ] 이 값만으로 자동 삭제가 허용되지 않음을 확인했다.

검토안:

```text
STAGING_DATA_RETENTION_DAYS=14
```

## J. Approval Reference

- [ ] `STAGING_APPROVAL_REFERENCE`를 확정했다.
- [ ] 기존 승인과 중복되지 않는다.
- [ ] 날짜와 순번이 포함된다.
- [ ] readiness, packet, approval record, infrastructure plan에서 동일하다.
- [ ] 값·commit·environment evidence 변경 시 새 reference를 발급한다.

형식:

```text
STAGING_APPROVAL_REFERENCE=staging-bootstrap-approval-YYYY-MM-DD-NNN
```

## K. Internal Flush 보안 결정

- [ ] `STAGING_INTERNAL_FLUSH_DECISION`을 검토했다.
- [ ] staging 한정 `mvp-staging-internal-token`의 의미를 이해했다.
- [ ] internal token 원문은 어떤 artifact에도 기록하지 않는다.
- [ ] production 전 private service 또는 private endpoint 분리가 필요함을 기록했다.
- [ ] 이 결정이 production 또는 deployment 승인이 아님을 확인했다.

기록:

```text
STAGING_INTERNAL_FLUSH_DECISION=mvp-staging-internal-token
```

## L. Governance attestation

Readiness JSON의 다음 항목을 실제 검토 후 기록한다.

- [ ] `decisionStatus=approved`
- [ ] `checklistComplete=true`
- [ ] `billingOwnerConfirmed=true`
- [ ] `budgetApprovedKrw=true`
- [ ] `notificationRecipientsConfirmed=true`
- [ ] `privacyRetentionReviewed=true`
- [ ] `internalFlushExceptionAccepted=true`

Boolean 값을 `true`로 바꾸는 행위 자체가 승인이 아니다. 위 각 항목의 실제 증빙을 먼저 확인한다.

## M. `staging-bootstrap` Protected Environment

GitHub UI에서 직접 확인한다.

- [ ] Environment 이름이 `staging-bootstrap`이다.
- [ ] Required reviewer가 최소 1명이다.
- [ ] 승인된 branch 또는 수동 workflow로 제한됐다.
- [ ] Environment secrets가 비어 있다.
- [ ] WIF provider 또는 GCP service account credential이 없다.
- [ ] workflow에 `id-token: write`가 없다.
- [ ] 아래 Environment Variables 9개와 정확히 일치한다.

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

Readiness attestation:

- [ ] `configured=true`
- [ ] `requiredReviewerCount>=1`
- [ ] `branchRestricted=true`
- [ ] `secretNames=[]`
- [ ] `cloudCredentialsPresent=false`
- [ ] `idTokenWrite=false`
- [ ] `variableNames`가 정확한 allowlist와 일치한다.

Validator는 GitHub Environment를 조회하거나 생성하지 않는다. 이 항목은 운영자가 GitHub UI를 확인한 결과를 기록한 것이다.

## N. Readiness local file

```bash
cp deploy/staging/staging-bootstrap-readiness.example.json \
  deploy/staging/staging-bootstrap-readiness.local.json
```

- [ ] actual values를 입력했다.
- [ ] target commit과 workflow evidence를 입력했다.
- [ ] governance evidence를 입력했다.
- [ ] protected environment attestation을 입력했다.
- [ ] planned bucket을 입력했다.
- [ ] infrastructure 전 observed bucket은 `null`이다.
- [ ] secret-like key가 없다.

실행:

```bash
mkdir -p artifacts/readiness

python3 scripts/staging_bootstrap_readiness.py \
  --input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/readiness/staging-bootstrap-readiness.json \
  --markdown-output artifacts/readiness/staging-bootstrap-readiness.md \
  --normalized-values-output artifacts/readiness/staging-bootstrap-values-normalized.json
```

## O. Readiness 결과

### `blocked`

- [ ] blocked reason을 모두 검토했다.
- [ ] normalized values가 생성되지 않았다.
- [ ] actual packet을 생성하지 않았다.

### `ready-for-protected-environment`

- [ ] values, workflow, governance는 통과했다.
- [ ] environment 설정과 attestation이 다음 작업임을 확인했다.
- [ ] normalized values가 생성되지 않았다.

### `ready-for-bootstrap-packet`

- [ ] `blockedReasons=[]`다.
- [ ] `cloudMutationApproved=false`다.
- [ ] `deploymentApproved=false`다.
- [ ] `mutationCommands=[]`다.
- [ ] normalized values가 생성됐다.
- [ ] Storage `source`가 planned 또는 observed로 명시됐다.
- [ ] `observed=null`이 planned로 조작되지 않았다.

## P. 기존 Materializer와 Static Preflight

Readiness가 `ready-for-bootstrap-packet`일 때만 실행한다.

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --values artifacts/readiness/staging-bootstrap-values-normalized.json \
  --output artifacts/staging-manifest-bootstrap.json

python3 scripts/staging_preflight.py \
  --manifest artifacts/staging-manifest-bootstrap.json \
  --report artifacts/staging-preflight-static.json
```

- [ ] source manifest가 변경되지 않았다.
- [ ] output project ID와 billing account가 승인 값과 같다.
- [ ] output Storage bucket provenance를 readiness report와 함께 검토했다.
- [ ] budget currency가 `KRW`다.
- [ ] service accounts가 staging project에 종속된다.
- [ ] `cloudMutationApproved=false`다.
- [ ] static report `status=pass`다.
- [ ] `cloudQueries=[]`다.
- [ ] `mutationCommands=[]`다.

## Q. 최초 Actual Bootstrap Packet

Readiness가 `ready-for-bootstrap-packet`이고 static preflight가 pass일 때만 실행한다.

```bash
python3 scripts/staging_approval_packet.py \
  --phase bootstrap \
  --manifest artifacts/staging-manifest-bootstrap.json \
  --static-report artifacts/staging-preflight-static.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

- [ ] packet status가 `ready-for-bootstrap-approval`이다.
- [ ] packet이 deployment approval이 아님을 확인했다.
- [ ] readiness JSON/Markdown을 packet과 함께 보존했다.
- [ ] normalized values를 packet evidence와 함께 보존했다.
- [ ] packet SHA-256을 계산했다.
- [ ] actual bootstrap approval record는 별도 검토 후 작성한다.

## R. 최종 중단 조건

다음 중 하나라도 있으면 actual packet을 생성하지 않는다.

- [ ] workflow 미완료 또는 실패
- [ ] production project 또는 bucket 참조
- [ ] billing owner 또는 KRW budget 미확정
- [ ] notification recipient 미확인
- [ ] 개인정보 retention 미검토
- [ ] protected environment reviewer·branch restriction 미설정
- [ ] environment secret 또는 cloud credential 존재
- [ ] `id-token: write` 존재
- [ ] planned/observed bucket 불일치
- [ ] secret 원문 또는 sensitive key 발견
- [ ] `cloudMutationApproved=true`
- [ ] `deploymentApproved=true`
- [ ] readiness status가 packet-ready가 아님
