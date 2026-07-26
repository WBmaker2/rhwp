# Staging Bootstrap 실제 값 확정 체크리스트

이 체크리스트는 `docs/approvals/staging-bootstrap-values-decision.md`와 함께 사용한다. 모든 항목을 확인하기 전에는 actual bootstrap packet 생성, infrastructure plan 승인, cloud resource 생성 또는 deployment를 진행하지 않는다.

## A. 저장소와 변경 범위

- [ ] 대상 저장소가 `WBmaker2/rhwp`인지 확인했다.
- [ ] 대상 브랜치가 `feat/firebase-collaboration-mvp-v1`인지 확인했다.
- [ ] PR #1이 Draft·미병합 상태인지 확인했다.
- [ ] 대상 manifest가 `deploy/staging/staging-manifest.json`인지 확인했다.
- [ ] repository manifest의 `environment`가 `staging`인지 확인했다.
- [ ] repository manifest의 `operations.cloudMutationApproved`가 `false`인지 확인했다.
- [ ] actual values 파일 `deploy/staging/staging-bootstrap-values.local.json`이 `.gitignore` 대상인지 확인했다.
- [ ] actual values, packet, approval record에 token·password·credential·private key를 넣지 않는다.

## B. Project ID

- [ ] `STAGING_PROJECT_ID` 값을 확정했다.
- [ ] 값은 GCP project ID 형식을 만족한다.
- [ ] 값에 `staging`이 포함된다.
- [ ] 값에 `prod` 또는 `production`이 포함되지 않는다.
- [ ] production project ID와 일치하지 않는다.
- [ ] 다른 서비스 또는 개인 실험 프로젝트를 재사용하지 않는다.
- [ ] 향후 Firebase Hosting site와 service account 이름으로 사용 가능하다.
- [ ] GCP에서 project ID 사용 가능 여부를 확인했다.

기록:

```text
STAGING_PROJECT_ID=
```

## C. Billing Account와 비용 책임

- [ ] `STAGING_BILLING_ACCOUNT` 값을 확정했다.
- [ ] 형식이 `XXXXXX-XXXXXX-XXXXXX`인지 확인했다.
- [ ] staging 비용을 부담할 billing account인지 확인했다.
- [ ] billing account 사용 권한 보유자를 확인했다.
- [ ] 월간 예산 승인자를 확인했다.
- [ ] 예산은 비용 차단이 아니라 알림 장치임을 확인했다.

마스킹 기록:

```text
STAGING_BILLING_ACCOUNT=XXXXXX-******-XXXXXX
```

## D. Production 차단 목록

- [ ] 실제 production project ID 전체를 확인했다.
- [ ] `STAGING_FORBIDDEN_PROJECT_IDS_JSON`을 JSON 문자열 배열로 작성했다.
- [ ] 배열이 비어 있지 않다.
- [ ] staging project ID가 배열에 포함되지 않는다.
- [ ] 중복 ID가 없다.

형식:

```text
STAGING_FORBIDDEN_PROJECT_IDS_JSON=["production-project-id"]
```

## E. Firebase와 Storage

- [ ] Firebase 데이터 위치 `asia-northeast3` 사용 가능성을 확인했다.
- [ ] Firestore 위치와 Storage 위치가 manifest 계약과 일치한다.
- [ ] `STAGING_STORAGE_BUCKET`을 확정했다.
- [ ] bucket 이름이 staging project ID에 종속된다.
- [ ] production bucket과 다르다.
- [ ] 권장 형식 `<project-id>.firebasestorage.app`과 실제 Firebase 생성 결과의 차이를 인지했다.
- [ ] bucket 실제 생성은 bootstrap packet 승인 이후 별도 infrastructure 단계임을 확인했다.

기록:

```text
STAGING_STORAGE_BUCKET=
```

## F. 월간 예산과 알림

- [ ] `STAGING_MONTHLY_BUDGET_KRW`를 확정했다.
- [ ] 쉼표 없는 양의 정수다.
- [ ] 통화는 `KRW`다.
- [ ] 50%·80%·100% threshold를 유지한다.
- [ ] `STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON`을 확정했다.
- [ ] JSON 문자열 배열이며 최소 1개 채널을 포함한다.
- [ ] 모든 수신자가 실제 수신 가능한지 확인했다.
- [ ] 개인정보 또는 불필요한 개인 주소 노출 여부를 검토했다.

기록:

```text
STAGING_MONTHLY_BUDGET_KRW=
STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON=[]
```

## G. 데이터 보존

- [ ] `STAGING_DATA_RETENTION_DAYS`를 확정했다.
- [ ] 양의 정수다.
- [ ] staging 장애 재현에 필요한 최소 기간이다.
- [ ] 학교·조직 개인정보 정책과 충돌하지 않는다.
- [ ] 이 값만으로 자동 삭제를 허용하지 않는다는 점을 확인했다.

기록:

```text
STAGING_DATA_RETENTION_DAYS=14
```

## H. Approval Reference

- [ ] `STAGING_APPROVAL_REFERENCE`를 확정했다.
- [ ] 기존 승인과 중복되지 않는다.
- [ ] 날짜와 순번을 포함한다.
- [ ] packet, approval record, infrastructure plan에서 동일하게 사용한다.
- [ ] 운영 값이 변경되면 새 reference를 발급한다.

기록:

```text
STAGING_APPROVAL_REFERENCE=staging-bootstrap-approval-YYYY-MM-DD-NNN
```

## I. Internal Flush 보안 결정

- [ ] `STAGING_INTERNAL_FLUSH_DECISION`을 검토했다.
- [ ] staging 한정 값 `mvp-staging-internal-token`을 사용하는 이유를 이해했다.
- [ ] internal token 원문은 어떤 artifact에도 기록하지 않는다.
- [ ] production 배포 전 private service 또는 private endpoint 분리가 필요함을 기록했다.
- [ ] 이 결정이 production 보안 승인이 아님을 확인했다.

기록:

```text
STAGING_INTERNAL_FLUSH_DECISION=mvp-staging-internal-token
```

## J. `staging-bootstrap` Protected Environment

GitHub 저장소의 Environment 설정은 저장소 소유자가 직접 검토한다.

- [ ] Environment 이름이 `staging-bootstrap`이다.
- [ ] Required reviewer를 지정했다.
- [ ] 승인된 branch 또는 수동 workflow만 접근하도록 제한했다.
- [ ] Environment secrets가 비어 있다.
- [ ] GCP WIF provider 또는 service account secret을 넣지 않았다.
- [ ] workflow에 `id-token: write` 권한이 없다.
- [ ] 아래 Environment Variables 9개만 등록했다.

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

변수별 확인:

- [ ] `STAGING_PROJECT_ID`
- [ ] `STAGING_BILLING_ACCOUNT`
- [ ] `STAGING_FORBIDDEN_PROJECT_IDS_JSON`
- [ ] `STAGING_STORAGE_BUCKET`
- [ ] `STAGING_MONTHLY_BUDGET_KRW`
- [ ] `STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON`
- [ ] `STAGING_DATA_RETENTION_DAYS`
- [ ] `STAGING_APPROVAL_REFERENCE`
- [ ] `STAGING_INTERNAL_FLUSH_DECISION`

## K. Local Materializer 검증

실제 값을 repository에 커밋하지 않고 local JSON으로 검증한다.

```bash
cp deploy/staging/staging-bootstrap-values.example.json \
  deploy/staging/staging-bootstrap-values.local.json
```

실제 값을 입력한 뒤 다음을 실행한다.

```bash
python3 scripts/staging_bootstrap_materializer.py \
  --manifest deploy/staging/staging-manifest.json \
  --values deploy/staging/staging-bootstrap-values.local.json \
  --output artifacts/staging-manifest-bootstrap.json
```

- [ ] command exit code가 0이다.
- [ ] source manifest가 변경되지 않았다.
- [ ] output의 project ID가 actual staging project ID다.
- [ ] output의 billing account가 actual 값이다.
- [ ] output의 Storage bucket이 staging project에 종속된다.
- [ ] output의 budget currency가 `KRW`다.
- [ ] output의 monthly amount가 승인 금액과 일치한다.
- [ ] output의 service account가 모두 staging project를 사용한다.
- [ ] output의 `cloudMutationApproved`가 `false`다.
- [ ] output의 `mutationCommands`가 없다.
- [ ] 허용된 deferred path 외 placeholder가 없다.

## L. Static Preflight와 Bootstrap Packet

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

- [ ] static report status가 `pass`다.
- [ ] static report의 `cloudQueries=[]`다.
- [ ] static report의 `mutationCommands=[]`다.
- [ ] packet phase가 `bootstrap`이다.
- [ ] packet status가 `ready-for-bootstrap-approval`이다.
- [ ] packet project ID와 billing account가 결정서와 일치한다.
- [ ] packet의 forbidden project IDs가 결정서와 일치한다.
- [ ] packet의 budget과 notification channel이 결정서와 일치한다.
- [ ] packet의 `cloudMutationApproved=false`다.
- [ ] packet의 `mutationCommands=[]`다.
- [ ] packet에 secret 원문이 없다.
- [ ] deferred values가 승인된 resource-derived path로 한정된다.

## M. GitHub Workflow 실행

`Staging configuration` workflow의 수동 입력:

```text
approval_phase=bootstrap
live_check=false
manifest_path=deploy/staging/staging-manifest.json
```

- [ ] `staging-bootstrap` reviewer가 실행을 승인했다.
- [ ] materializer step이 성공했다.
- [ ] static preflight step이 성공했다.
- [ ] bootstrap packet step이 성공했다.
- [ ] `staging-approval-packet-bootstrap` artifact가 생성됐다.
- [ ] workflow에 GCP 인증 단계가 없다.
- [ ] workflow에 Firebase CLI 설치가 없다.
- [ ] workflow에 cloud mutation command가 없다.

## N. Bootstrap Packet 승인 기록

- [ ] packet JSON의 SHA-256을 계산했다.
- [ ] 대상 commit SHA를 기록했다.
- [ ] workflow run ID를 기록했다.
- [ ] 승인자를 기록했다.
- [ ] 승인 시각을 UTC ISO-8601로 기록했다.
- [ ] accepted deferred paths를 packet과 일치시켰다.
- [ ] security exception에 staging internal-token 결정을 기록했다.
- [ ] `deploymentApproved=false`를 유지했다.
- [ ] `cloudMutationApproved=false`를 유지했다.
- [ ] 승인 기록이 packet digest와 project ID에 결합됐다.

## O. 다음 단계로 이동할 수 있는 조건

다음 조건이 모두 충족돼야 infrastructure bootstrap plan을 생성할 수 있다.

- [ ] 결정서 상태가 `확정 / bootstrap packet 생성 승인`이다.
- [ ] actual values 9개가 모두 확정됐다.
- [ ] protected environment가 설정됐다.
- [ ] actual bootstrap packet이 생성됐다.
- [ ] packet 검토가 완료됐다.
- [ ] bootstrap approval record가 `approved`다.
- [ ] packet SHA-256, commit SHA, project ID, billing account가 approval record와 일치한다.
- [ ] resource 생성 또는 deployment 승인은 아직 부여되지 않았다.

## P. 절대 중단 조건

다음 중 하나라도 해당하면 즉시 중단한다.

- [ ] project ID가 production 또는 forbidden project와 일치한다.
- [ ] billing account가 미확정이거나 책임자가 불명확하다.
- [ ] budget이 미확정이거나 KRW 양의 정수가 아니다.
- [ ] notification channel이 비어 있다.
- [ ] actual values 또는 artifacts에 secret·token·credential이 포함됐다.
- [ ] `cloudMutationApproved=true`가 나타난다.
- [ ] bootstrap workflow가 GCP/Firebase 인증 또는 mutation을 요구한다.
- [ ] packet digest와 approval record가 일치하지 않는다.
- [ ] 별도 infrastructure approval 없이 resource 생성을 시도한다.
- [ ] 별도 deployment approval 없이 deployment를 시도한다.
