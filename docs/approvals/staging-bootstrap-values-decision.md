# Staging Bootstrap 운영 값 결정서

## 문서 상태

- 문서 상태: **초안 / 미승인**
- 대상 환경: `staging` only
- 대상 브랜치: `feat/firebase-collaboration-mvp-v1`
- 대상 PR: `WBmaker2/rhwp#1`
- 실제 리소스 변경 승인 여부: **아니오**
- deployment 승인 여부: **아니오**
- `operations.cloudMutationApproved`: 반드시 `false`
- 승인 가능한 작업: 값 검토, readiness 평가, static materialization, static preflight, bootstrap approval packet 생성
- 금지 작업: GCP/Firebase 생성·수정·삭제, billing 연결, API 활성화, IAM 변경, image build/push, live preflight, deployment

## 1. 결정 원칙

1. staging과 production은 project, Firebase resources, service accounts, IAM, Storage, Hosting, Cloud Run, Cloud Tasks를 공유하지 않는다.
2. 금액은 `KRW`로 기록하며 변환하지 않는다.
3. secret 원문, token, credential, password, private key, service-account key는 운영 값이나 승인 artifact에 넣지 않는다.
4. repository의 `deploy/staging/staging-manifest.json`은 placeholder 기반 설계 원본으로 유지한다.
5. 실제 운영 값은 gitignored readiness JSON 또는 승인된 `staging-bootstrap` Environment Variables로만 주입한다.
6. bootstrap packet 승인, infrastructure mutation 승인, deployment 승인은 서로 다른 승인이다.
7. planned resource는 승인된 의도이며 observed resource는 리소스 생성 후 확인한 실제 상태다.
8. `observed=null`은 정상적인 bootstrap 이전 상태이며 planned 값을 observed로 복사하지 않는다.
9. 모든 actual approval은 대상 commit SHA와 artifact SHA-256에 결합한다.

## 2. 실제 운영 값 결정표

모든 필수 항목과 governance evidence가 확정되기 전에는 actual bootstrap packet을 생성하지 않는다.

| 번호 | 결정 항목 | 현재 상태 | 기록 위치 |
|---:|---|---|---|
| 1 | Staging Project ID | 미확정 | readiness `values.project.id` |
| 2 | Billing Account | 미확정 | `values.project.billingAccount` |
| 3 | Forbidden Project IDs | 미확정 | `values.project.forbiddenProjectIds` |
| 4 | Firebase Storage planned bucket | 미확정 | `values.firebase.storageBucket.planned` |
| 5 | Firebase Storage observed bucket | infrastructure 전 `null` | `values.firebase.storageBucket.observed` |
| 6 | 월간 예산 KRW | 미확정 | `values.budget.amountKrw` |
| 7 | 예산 알림 채널 | 미확정 | `values.budget.notificationChannels` |
| 8 | 데이터 보존 기간 | 미확정 | `values.operations.dataRetentionDays` |
| 9 | Approval Reference | 미확정 | `values.operations.approvalReference` |
| 10 | Internal Flush 보안 결정 | 검토안 존재 | `values.operations.internalFlushSecurityDecision` |

## 3. Project ID

필수 조건:

- GCP project ID 형식을 만족한다.
- `staging` 문자열을 포함한다.
- `prod` 또는 `production` 구간을 포함하지 않는다.
- production project ID와 일치하지 않는다.
- 다른 서비스 또는 개인 실험 프로젝트를 재사용하지 않는다.
- Firebase Hosting site와 service account 이름으로 사용해도 의미가 명확하다.
- 실제 계정에서 ID 사용 가능 여부를 확인한다.

형식 예시:

```text
rhwp-collaboration-staging-123
```

## 4. Billing Account와 비용 책임

필수 조건:

- 형식: `XXXXXX-XXXXXX-XXXXXX`
- staging 비용을 부담할 계정인지 확인한다.
- billing account 사용 권한 보유자와 비용 책임자를 확인한다.
- 월간 예산과 알림 수신자를 확인한다.
- billing account는 secret은 아니지만 필요한 승인 artifact에만 최소한으로 기록한다.
- 예산은 비용 차단 장치가 아니라 알림 장치임을 이해한다.

## 5. Forbidden Project IDs

JSON 배열로 기록한다.

```json
["rhwp-production"]
```

필수 조건:

- 실제 production project ID를 모두 포함한다.
- 빈 배열을 허용하지 않는다.
- staging project ID를 포함하지 않는다.
- 중복 ID를 허용하지 않는다.

## 6. Firebase Storage planned/observed 계약

### 6.1 Planned bucket

Bootstrap 전에 승인하는 resource intent다.

```text
<STAGING_PROJECT_ID>.firebasestorage.app
```

필수 조건:

- staging project ID에 종속된다.
- production bucket과 다르다.
- `.firebasestorage.app` 또는 `.appspot.com` suffix를 사용한다.
- `asia-northeast3` 데이터 위치 결정과 충돌하지 않는다.
- planned 값이 cloud에 이미 존재한다고 주장하지 않는다.

### 6.2 Observed bucket

리소스 생성 후 read-only evidence로 확인한 실제 값이다.

```json
{
  "planned": "rhwp-collaboration-staging-123.firebasestorage.app",
  "observed": null
}
```

- infrastructure 생성 전에는 `null`이 정상이다.
- repository나 validator가 planned 값을 observed로 자동 복사하지 않는다.
- observed가 생기면 planned와 일치해야 한다.
- 다르면 lifecycle을 중단하고 새 approval reference로 재검토한다.

### 6.3 Protected environment 변수

첫 bootstrap packet에서는 reviewed planned value를 기존 변수에 등록한다.

```text
STAGING_STORAGE_BUCKET=<planned value>
```

Observed 값은 infrastructure 후 별도 readiness evidence에 기록한다.

## 7. 월간 예산과 알림

- 통화: `KRW`
- 입력: 쉼표 없는 양의 정수
- threshold: `50%`, `80%`, `100%`
- 최소 1개의 실제 수신 가능한 notification recipient
- 개인 주소 노출과 비용 책임 범위를 검토한다.
- 초기 운영 후 조정은 새 approval reference와 별도 승인을 요구한다.

검토 예시:

```text
STAGING_MONTHLY_BUDGET_KRW=50000
```

이 값은 예시이며 실제 승인 금액이 아니다.

## 8. 데이터 보존 기간

검토 기준:

- 양의 정수
- 기본 검토안: `14`일
- 장애 재현과 감사에 필요한 최소 기간
- 학교·조직 개인정보 정책 우선
- 이 값만으로 자동 삭제를 허용하지 않음

## 9. Approval Reference

권장 형식:

```text
staging-bootstrap-approval-YYYY-MM-DD-NNN
```

필수 조건:

- 기존 승인과 중복되지 않는다.
- readiness, packet, approval record, infrastructure plan에서 동일하게 사용한다.
- 값, workflow commit, environment evidence 또는 planned resource가 변경되면 새 reference를 발급한다.

## 10. Internal Flush 보안 결정

현재 staging에서 허용하는 결정:

```text
mvp-staging-internal-token
```

승인 의미:

- staging 한정 public Collaboration service와 high-entropy internal token 경계를 임시 수용한다.
- token 원문은 어떤 JSON, Markdown, packet, log에도 기록하지 않는다.
- production 배포 승인이 아니다.
- production 전 private service 또는 private endpoint 분리를 별도 설계·승인한다.

## 11. Workflow evidence

동일한 대상 commit에서 다음 workflow가 모두 `completed/success`여야 한다.

```text
CI
CodeQL
Render Diff
Staging configuration
```

새 commit이 생기면 이전 run 결과를 재사용하지 않고 새 head 결과로 readiness evidence를 갱신한다.

## 12. `staging-bootstrap` protected environment 결정

필수 설정:

- Environment name: `staging-bootstrap`
- Required reviewer: 최소 1명
- 승인된 branch 또는 수동 workflow로 제한
- Environment secrets: 없음
- GCP WIF 또는 cloud credential: 없음
- `id-token: write`: 없음
- Environment Variables: 아래 9개와 정확히 일치

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

Validator는 GitHub Environment를 조회하거나 생성하지 않는다. 운영자가 GitHub UI를 확인한 뒤 readiness JSON의 attestation을 사실에 맞게 기록한다.

## 13. 결정 완료 조건

다음 조건을 모두 만족할 때만 문서 상태를 `확정 / bootstrap packet 생성 승인`으로 변경한다.

1. 실제 운영 값이 모두 concrete다.
2. project ID와 forbidden project IDs가 충돌하지 않는다.
3. planned Storage bucket이 staging project에 종속된다.
4. observed Storage bucket은 infrastructure 전 `null`이다.
5. billing owner와 비용 책임자가 확인됐다.
6. 월간 예산이 KRW 양의 정수다.
7. notification recipients가 확인됐다.
8. retention 개인정보 검토가 완료됐다.
9. approval reference가 고유하다.
10. internal flush staging 예외를 이해하고 수용했다.
11. 대상 commit의 필수 workflow가 모두 성공했다.
12. `staging-bootstrap` Environment attestation이 통과했다.
13. Readiness status가 `ready-for-bootstrap-packet`이다.
14. `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`다.

## 14. 승인 서명란

현재 문서는 초안이므로 미기재 상태로 유지한다.

| 항목 | 기록 |
|---|---|
| 결정 상태 | 미승인 |
| 승인자 | 미기재 |
| 승인 시각 | 미기재 |
| 대상 commit SHA | 미기재 |
| Readiness report SHA-256 | 미기재 |
| Bootstrap workflow run ID | 미기재 |
| Packet SHA-256 | 미기재 |
| 비고 | 실제 값과 environment evidence 확정 후 기록 |
