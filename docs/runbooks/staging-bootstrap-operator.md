# rhwp Actual Staging Bootstrap Operator

## 상태

- 적용 환경: `staging` only
- operator: `scripts/staging_bootstrap_operator.py`
- report schema: `rhwp.staging-bootstrap-operator-status/v1`
- cloud authentication: 없음
- GitHub API mutation: 없음
- GCP/Firebase query 또는 mutation: 없음
- workflow dispatch: operator가 직접 실행하지 않음
- actual approval 생성: 사람의 packet 검토와 approved review declaration 이후 별도 단계

## 1. 목적

이 operator는 다음 실제 운영 순서를 하나의 fail-closed 상태 보고서로 연결한다.

```text
실제 운영 값 확정
→ readiness 실행
→ staging-bootstrap Environment 설정·attestation
→ readiness 재실행
→ actual bootstrap packet 생성
→ exact packet bytes 검토
→ bootstrap approval record 생성
→ infrastructure plan 준비
```

operator는 외부 시스템을 변경하지 않는다. 입력 증빙의 내부 일관성을 검사하고 **현재 허용된 다음 작업 하나만** 출력한다.

## 2. 입력과 출력

### 필수 입력

```text
deploy/staging/staging-bootstrap-readiness.local.json
```

이 파일은 `.gitignore` 대상이다. 실제 project ID, billing account, production 차단 목록, 원화 예산과 알림 수신자 등 운영 메타데이터를 repository에 커밋하지 않는다.

### 선택 입력

현재 단계에 따라 다음 입력을 추가한다.

```text
actual bootstrap packet JSON
packet source workflow run ID
packet source commit SHA
approved packet review declaration
bootstrap approval record
```

### 출력

```text
artifacts/operator/staging-bootstrap-operator-status.json
artifacts/operator/staging-bootstrap-operator-status.md
artifacts/operator/staging-bootstrap-packet-review-draft.json
```

마지막 파일은 packet 검토 단계에서만 선택적으로 생성한다.

모든 status report는 다음 경계를 강제한다.

```json
{
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "mutationCommands": []
}
```

## 3. 상태 해석

### `collect-operating-values`

Readiness local 파일이 아직 없다.

다음 9개 운영 값을 실제 계정과 운영 정책에서 확인한다.

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

값을 추측하거나 example 값을 actual 값으로 복사하지 않는다. 금액은 승인된 원화 금액 그대로 기록한다.

### `blocked`

다음 중 하나 이상이 실패했다.

- workflow evidence가 현재 commit과 다름
- 필수 workflow가 성공하지 않음
- governance 확인 미완료
- production 차단 목록 불충분
- staging project/billing/approval reference 불일치
- packet source commit 또는 run ID 불일치
- packet bytes와 parsed object 불일치
- packet SHA-256과 review 불일치
- approval record와 exact reviewed record 불일치
- secret-like key 또는 unsafe packet 발견

`blockedReasons`를 해결하기 전 다음 단계로 진행하지 않는다.

### `configure-staging-bootstrap-environment`

운영 값과 workflow evidence는 통과했지만 protected environment attestation이 아직 없다.

GitHub UI에서 다음 Environment를 설정한다.

```text
staging-bootstrap
```

필수 조건:

- required reviewer 최소 1명
- branch restriction 활성화
- Environment Secrets 없음
- cloud credential 없음
- `id-token: write` 없음
- 정확한 Environment Variables 9개

설정 후 GitHub UI를 직접 확인하고 readiness local JSON의 `protectedEnvironment` attestation을 사실에 맞게 갱신한다. Operator는 Environment 존재 여부를 조회하지 않는다.

### `generate-actual-bootstrap-packet`

Readiness가 `ready-for-bootstrap-packet`이다.

GitHub Actions에서 수동 실행한다.

```text
Workflow: Staging configuration
approval_phase: bootstrap
live_check: false
manifest_path: deploy/staging/staging-manifest.json
```

필요한 protected environment:

```text
staging-bootstrap
```

예상 artifact:

```text
staging-approval-packet-bootstrap
```

Operator는 이 workflow를 직접 dispatch하지 않는다.

### `review-actual-bootstrap-packet`

Actual packet과 source workflow evidence가 검증됐다. 이제 사람이 exact packet bytes를 검토해야 한다.

검토 항목:

- staging project ID
- billing account
- forbidden production project IDs
- 월간 KRW 예산
- 예산 threshold 50%·80%·100%
- 알림 수신 채널
- accepted deferred paths
- internal flush staging exception
- static-only preflight
- `cloudMutationApproved=false`
- `packetIsDeploymentApproval=false`
- `containsCloudMutationCommands=false`
- `mutationCommands=[]`

#### Packet 파일 보존

GitHub artifact에서 받은 `staging-approval-packet.json`을 formatter, editor 또는 JSON pretty-printer로 다시 저장하지 않는다. SHA-256은 파일 원문 바이트를 기준으로 계산된다.

Packet을 다시 저장했다면 새 digest와 새 review declaration이 필요하다.

#### Pending review draft 생성

```bash
mkdir -p artifacts/operator

python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --packet /absolute/path/to/staging-approval-packet.json \
  --packet-workflow-run-id <ACTUAL_RUN_ID> \
  --packet-commit-sha <ACTUAL_PACKET_COMMIT_SHA> \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md \
  --review-draft-output artifacts/operator/staging-bootstrap-packet-review-draft.json
```

생성된 draft는 항상 다음 상태다.

```text
decision=pending
approvedAt=null
approvedBy=[]
acknowledgements=false
```

Operator는 승인자나 승인 시각을 만들지 않는다.

### `generate-bootstrap-approval-record`

사람이 packet을 검토하고 review declaration을 `approved` 상태로 완성했다.

Review declaration에는 실제 값을 기록한다.

```text
approvedAt: UTC YYYY-MM-DDTHH:MM:SSZ
approvedBy: 실제 승인자 목록
commitSha: packet source commit
workflowRunId: packet source run ID
expectedPacketSha256: operator가 계산한 exact-byte digest
expectedApprovalReference: packet approval reference
acknowledgements: 실제 검토 후 모두 true
```

Protected review workflow를 수동 실행한다.

```text
Workflow: Staging configuration
approval_phase: bootstrap-review
live_check: false
bootstrap_packet_path: repository-relative reviewed packet path
bootstrap_review_path: repository-relative approved review declaration path
```

필요한 protected environment:

```text
staging-bootstrap-approval
```

예상 artifact:

```text
staging-bootstrap-approval-review
```

이 단계는 approval record를 만들지만 infrastructure mutation 또는 deployment를 승인하지 않는다.

### `ready-for-infrastructure-plan`

다음 증거가 모두 exact packet bytes에 결합됐다.

- current readiness input
- actual packet
- packet source commit/run
- approved human review
- planner-compatible bootstrap approval record

다음 허용 작업은 plan-only workflow다.

```text
approval_phase: infrastructure-plan
live_check: false
```

이 상태는 **계획 생성만 허용**한다. Project 생성, billing 연결, API 활성화, IAM 변경, resource 생성, live preflight, image build 또는 deployment 권한이 아니다.

## 4. 단계별 실행

### 단계 A: actual 값이 없을 때

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md
```

파일이 없으면 `collect-operating-values`가 출력된다.

### 단계 B: 첫 readiness와 environment gate

Readiness local JSON을 작성하고 같은 명령을 실행한다.

- Environment attestation 전: `configure-staging-bootstrap-environment`
- Environment attestation 후: `generate-actual-bootstrap-packet`

### 단계 C: packet 생성 후

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --packet /absolute/path/to/staging-approval-packet.json \
  --packet-workflow-run-id <ACTUAL_RUN_ID> \
  --packet-commit-sha <ACTUAL_PACKET_COMMIT_SHA> \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md \
  --review-draft-output artifacts/operator/staging-bootstrap-packet-review-draft.json
```

기대 상태:

```text
review-actual-bootstrap-packet
```

### 단계 D: human review 후

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --packet /absolute/path/to/staging-approval-packet.json \
  --packet-workflow-run-id <ACTUAL_RUN_ID> \
  --packet-commit-sha <ACTUAL_PACKET_COMMIT_SHA> \
  --review /absolute/path/to/staging-bootstrap-packet-review.json \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md
```

기대 상태:

```text
generate-bootstrap-approval-record
```

### 단계 E: approval record 생성 후

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --packet /absolute/path/to/staging-approval-packet.json \
  --packet-workflow-run-id <ACTUAL_RUN_ID> \
  --packet-commit-sha <ACTUAL_PACKET_COMMIT_SHA> \
  --review /absolute/path/to/staging-bootstrap-packet-review.json \
  --approval-record /absolute/path/to/staging-bootstrap-approval-record.json \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md
```

기대 상태:

```text
ready-for-infrastructure-plan
```

## 5. 엄격 모드

자동화나 검사 단계에서는 blocked status를 exit code 1로 처리할 수 있다.

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md \
  --strict-blocked-exit
```

엄격 모드에서 blocked이면 최종 출력과 `.tmp` 파일을 남기지 않는다.

## 6. 금지 사항

Operator 입력·출력 또는 approval records 디렉터리에 다음 값을 넣지 않는다.

- access token 또는 ID token
- Authorization header
- password
- private key
- service-account key JSON
- secret 원문
- refresh token
- cookie 또는 session credential
- Firebase API key 원문

## 7. 최종 중단 경계

Operator 구현과 status 생성은 다음 작업을 승인하지 않는다.

```text
project creation
billing linkage
API activation
IAM mutation
service account creation
Secret Manager mutation
Firestore/Storage/Hosting creation
Cloud Run/Cloud Tasks creation
image build or push
live preflight
deployment
```

각 작업은 기존 infrastructure approval 및 deployment approval lifecycle에서 별도로 승인돼야 한다.
