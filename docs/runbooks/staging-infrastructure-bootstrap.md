# rhwp Staging Infrastructure Bootstrap Runbook

## 상태

- 적용 환경: staging only
- 대상 PR: `WBmaker2/rhwp#1`
- 현재 구현된 범위: 운영 값 결정, materialization, static preflight, bootstrap packet, bootstrap approval record 계약, infrastructure plan 생성
- 현재 실행 금지 범위: project·billing·API·Firebase·IAM·service account·Artifact Registry·Secret·Cloud Tasks·Budget·Cloud Run 생성 또는 변경
- live preflight: 실제 infrastructure 준비와 별도 승인 전 금지
- deployment: deployment packet과 별도 deployment approval 전 금지

## 1. 전체 수명 주기

| 단계 | 목적 | 현재 지원 | Cloud mutation |
|---:|---|---|---|
| 1 | 실제 운영 값 결정서와 체크리스트 | 지원 | 없음 |
| 2 | `staging-bootstrap` protected environment 설정 | workflow 계약·체크리스트 지원, 실제 설정은 저장소 소유자가 수행 | 없음 |
| 3 | 최초 actual bootstrap packet 생성 | workflow 지원, actual values 필요 | 없음 |
| 4 | packet 검토와 bootstrap approval record | schema·example·검증 지원 | 없음 |
| 5 | infrastructure bootstrap plan 생성 | planner·protected plan-only workflow 지원 | 없음 |
| 6 | 별도 infrastructure 승인 | example record와 검토 기준 지원 | 없음 |
| 7 | staging resource 생성 | **미구현 / 별도 승인 단위** | 있음 |
| 8 | 실제 resource identifier 반영 | 7단계 후 별도 구현 | 없음 또는 승인된 설정 변경 |
| 9 | live read-only preflight | 기존 workflow 지원, 7·8단계 완료 필요 | 조회만 |
| 10 | deployment approval packet | 기존 generator 지원 | 없음 |
| 11 | 별도 deployment 승인 | example record 지원 | 없음 |
| 12 | staging deployment | **미구현 / 별도 승인 단위** | 있음 |

## 2. 관련 문서와 파일

```text
docs/approvals/staging-bootstrap-values-decision.md
docs/approvals/staging-bootstrap-values-checklist.md
docs/approvals/staging-bootstrap-approval-record.example.json
docs/approvals/staging-infrastructure-approval-record.example.json
docs/approvals/staging-deployment-approval-record.example.json
deploy/staging/staging-bootstrap-values.example.json
scripts/staging_bootstrap_materializer.py
scripts/staging_preflight.py
scripts/staging_approval_packet.py
scripts/staging_infrastructure_plan.py
.github/workflows/staging-config-validate.yml
```

실제 승인 artifact를 저장소에 기록할 경우 다음 디렉터리를 사용한다.

```text
docs/approvals/records/<approval-reference>/
```

권장 파일 이름:

```text
staging-manifest-bootstrap.json
staging-preflight-static.json
staging-approval-packet.json
staging-approval-packet.md
staging-bootstrap-approval-record.json
staging-infrastructure-plan.json
staging-infrastructure-plan.md
staging-infrastructure-approval-record.json
staging-preflight-live.json
staging-deployment-approval-packet.json
staging-deployment-approval-packet.md
staging-deployment-approval-record.json
```

이 디렉터리에는 secret 원문, token, credential, password, private key 또는 service-account key를 저장하지 않는다.

## 3. 단계 1: 실제 운영 값 결정

다음 문서를 순서대로 검토한다.

```text
docs/approvals/staging-bootstrap-values-decision.md
docs/approvals/staging-bootstrap-values-checklist.md
```

확정할 값:

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

아래 조건에서는 중단한다.

- project ID가 production-like이거나 forbidden project와 일치
- billing account·비용 책임자·KRW 예산이 미확정
- Storage bucket이 staging project에 종속되지 않음
- notification channel이 비어 있음
- security decision이 `mvp-staging-internal-token`이 아님
- values에 secret-like key가 포함됨

## 4. 단계 2: `staging-bootstrap` protected environment

실제 GitHub Environment 설정은 repository owner가 GitHub UI에서 수행한다. repository workflow는 환경을 생성하지 않는다.

필수 설정:

- Environment name: `staging-bootstrap`
- Required reviewer: 최소 1명
- Environment secrets: 없음
- WIF provider 또는 GCP service account secret: 없음
- 허용 variables: 운영 값 9개
- workflow 권한: `contents: read`
- `id-token: write`: 없음

환경 설정이 존재하지 않거나 reviewer가 승인하지 않으면 bootstrap job을 실행하지 않는다.

## 5. 단계 3: 최초 actual bootstrap packet

GitHub Actions에서 `Staging configuration`을 수동 실행한다.

```text
approval_phase=bootstrap
live_check=false
manifest_path=deploy/staging/staging-manifest.json
```

예상 artifact:

```text
staging-approval-packet-bootstrap
```

필수 검토:

- materialized manifest project ID와 billing account
- forbidden production project IDs
- Firebase domain, Storage bucket, Hosting site
- KRW budget, thresholds, notification channels
- service account와 IAM bindings
- `cloudMutationApproved=false`
- `mutationCommands=[]`
- resource-derived deferred paths만 존재

이 packet은 infrastructure 생성 또는 deployment 승인이 아니다.

## 6. 단계 4: Bootstrap approval record

Packet JSON 원문 바이트의 SHA-256을 계산한다.

```bash
shasum -a 256 staging-approval-packet.json
```

다음 example을 복사해 실제 검토 결과를 기록한다.

```text
docs/approvals/staging-bootstrap-approval-record.example.json
```

승인 record 필수 조건:

- `schemaVersion=rhwp.staging-bootstrap-approval/v1`
- `decision=approved`
- UTC `approvedAt`
- 비어 있지 않은 `approvedBy`
- 대상 40자리 commit SHA
- 실제 workflow run ID
- packet SHA-256 일치
- project ID와 billing account 일치
- packet의 deferred path 전체와 정확히 일치
- staging internal-token 예외 명시
- `deploymentApproved=false`
- `cloudMutationApproved=false`

Packet이 수정되면 기존 record를 재사용하지 않고 새 digest와 새 승인 기록을 만든다.

## 7. 단계 5: Infrastructure bootstrap plan

### 7.1 Local 실행

```bash
python3 scripts/staging_infrastructure_plan.py \
  --manifest docs/approvals/records/<approval-reference>/staging-manifest-bootstrap.json \
  --bootstrap-packet docs/approvals/records/<approval-reference>/staging-approval-packet.json \
  --bootstrap-approval-record docs/approvals/records/<approval-reference>/staging-bootstrap-approval-record.json \
  --json-output artifacts/staging-infrastructure-plan.json \
  --markdown-output artifacts/staging-infrastructure-plan.md
```

Planner는 다음을 검증한다.

- bootstrap approval record가 `approved`
- packet digest 일치
- project ID와 billing account 일치
- deferred paths 일치
- production-like project 차단
- secret-like key 차단
- deployment 및 cloud mutation 승인 플래그가 `false`

생성 plan은 다음 11개 ordered stage를 포함한다.

```text
project-billing
api-baseline
firebase-foundation
service-accounts
artifact-registry
secret-metadata
iam-bindings
budget-guardrails
cloud-run-prerequisites
cloud-tasks-prerequisites
post-bootstrap-evidence
```

Plan은 shell 또는 cloud mutation command를 포함하지 않는다.

### 7.2 GitHub plan-only workflow

실제 non-secret reviewed files가 branch에 존재할 때 다음 입력으로 수동 실행한다.

```text
approval_phase=infrastructure-plan
live_check=false
manifest_path=docs/approvals/records/<approval-reference>/staging-manifest-bootstrap.json
bootstrap_packet_path=docs/approvals/records/<approval-reference>/staging-approval-packet.json
bootstrap_approval_record_path=docs/approvals/records/<approval-reference>/staging-bootstrap-approval-record.json
```

보호 환경:

```text
staging-infrastructure
```

이 job은 다음 특성을 가진다.

- `contents: read` only
- GCP authentication 없음
- Firebase authentication 없음
- cloud CLI 설치 없음
- `id-token: write` 없음
- resource mutation 없음

예상 artifact:

```text
staging-infrastructure-bootstrap-plan
```

## 8. 단계 6: 별도 Infrastructure 승인

다음 example을 사용한다.

```text
docs/approvals/staging-infrastructure-approval-record.example.json
```

현재 example은 의도적으로 다음 상태다.

```json
{
  "decision": "pending",
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "rollbackReviewed": false
}
```

실제 infrastructure 실행 승인을 만들기 전 검토할 사항:

- plan SHA-256
- 승인 stage ID 목록
- project ID와 billing account
- 최대 월간 예산 KRW
- API allowlist
- Firebase 데이터 위치
- service account별 IAM 역할
- Secret 이름과 access principal; secret 값은 제외
- resource별 rollback boundary
- 비용·보안·운영 승인자

`cloudMutationApproved=true`는 이 별도 record에서만 허용될 수 있으며, 현재 구현에는 이 record를 소비해 mutation을 수행하는 executor가 없다.

## 9. 단계 7: Staging resource 생성 — 현재 중단 경계

현재 repository에는 infrastructure mutation executor가 없다. 다음 조건을 모두 충족한 별도 구현 요청과 승인이 필요하다.

1. actual bootstrap packet
2. approved bootstrap record
3. reviewed infrastructure plan
4. approved infrastructure record
5. billing ownership 확인
6. protected environment reviewer 확인
7. WIF identity와 최소 권한 diff 확인
8. 단계별 rollback 절차 확인
9. 변경 가능한 resource allowlist 확인
10. dry-run 또는 read-only 사전 점검

이 단계는 현재 작업에서 실행하지 않는다.

## 10. 단계 8: 실제 resource identifier 반영

Infrastructure 실행 후 다음 실제 값을 evidence에서 수집한다.

- GCP project number
- Firebase Web App ID
- Firebase Web API key reference; 값이 아닌 reference
- 실제 Storage bucket
- 실제 Hosting site
- 생성된 service account 존재 상태
- Artifact Registry repository
- Secret metadata와 version reference
- actual IAM state
- Budget state

Image build 이후:

- Collaboration image와 digest
- Document API image와 digest
- Document Worker image와 digest

초기 deployment 이후:

- Document Worker URL
- parse/export target URL
- Cloud Run rollback revision IDs

모든 placeholder가 해결되기 전에는 deployment packet을 생성하지 않는다.

## 11. 단계 9: Live read-only preflight

필수 전제:

- infrastructure 승인과 실행 evidence 존재
- 실제 resource identifiers로 materialized manifest 완성
- `staging-preflight` protected environment
- read-only WIF identity
- active project가 승인된 staging project와 일치

Live preflight는 조회만 수행한다. 예상하지 못한 resource 또는 IAM binding이 있으면 status를 `review`로 설정하고 lifecycle을 중단한다.

## 12. 단계 10: Deployment approval packet

Deployment packet 필수 조건:

- 모든 placeholder 해결
- live report 존재
- project ID 일치
- immutable image digest
- actual IAM diff
- actual Cloud Tasks target URL
- rollback revision IDs 또는 명시적 최초 배포 전략
- `mutationCommands=[]`

## 13. 단계 11: 별도 Deployment 승인

다음 example을 사용한다.

```text
docs/approvals/staging-deployment-approval-record.example.json
```

승인은 deployment packet digest, commit SHA, image digests, IAM diff digest, acceptance tests, rollback evidence에 결합해야 한다.

Bootstrap 또는 infrastructure approval record를 deployment 승인으로 재사용하지 않는다.

## 14. 단계 12: Staging deployment — 현재 중단 경계

현재 repository에는 approval-bound staging deployment executor가 없다. 별도 구현과 승인이 필요하다.

배포 전 필수 조건:

- deployment approval record가 `approved`
- `deploymentApproved=true`
- approved immutable image digests 일치
- live preflight status `pass`
- IAM diff 승인
- rollback revision 또는 최초 배포 rollback 전략 승인
- acceptance test 계획 승인

## 15. 공통 중단 조건

다음 중 하나라도 발생하면 lifecycle을 중단한다.

- actual artifact와 승인 digest 불일치
- project ID 또는 billing account 불일치
- production project 또는 bucket 참조
- secret·token·credential 원문 노출
- unknown approval record key
- packet과 deferred path 승인 불일치
- 계획하지 않은 API, IAM role, service account 또는 resource
- 별도 승인 전 `cloudMutationApproved=true`
- deployment 승인 전 `deploymentApproved=true`
- live preflight에서 unexpected resource 발견
- rollback evidence 누락

## 16. 검증 명령

```bash
python3 -m py_compile \
  scripts/staging_bootstrap_materializer.py \
  scripts/staging_approval_packet.py \
  scripts/staging_infrastructure_plan.py \
  scripts/tests/test_staging_infrastructure_plan.py

python3 -m unittest discover \
  -s scripts/tests \
  -p 'test_*.py' \
  -v

python3 scripts/validate_staging_config.py
```

검증은 cloud resource 생성, live query, image build/push 또는 deployment를 수행하지 않는다.
