# Staging Bootstrap 운영 값 결정서

## 문서 상태

- 문서 상태: **초안 / 미승인**
- 대상 환경: `staging` only
- 대상 브랜치: `feat/firebase-collaboration-mvp-v1`
- 대상 PR: `WBmaker2/rhwp#1`
- 이 문서가 허용하는 작업: 값 검토, static materialization, static preflight, bootstrap approval packet 생성
- 이 문서가 허용하지 않는 작업: GCP/Firebase 리소스 생성·수정·삭제, billing 연결, API 활성화, IAM 변경, image build/push, live preflight, 배포
- 실제 리소스 변경 승인 여부: **아니오**
- `operations.cloudMutationApproved`: 반드시 `false`

## 1. 결정 원칙

1. staging과 production은 프로젝트 ID, Firebase 리소스, service account, IAM, Storage, Hosting, Cloud Run, Cloud Tasks를 공유하지 않는다.
2. 금액은 `KRW`로 기록하며 다른 통화로 변환하지 않는다.
3. actual value는 token, password, private key, service-account key가 아닌 운영 메타데이터만 허용한다.
4. actual value는 GitHub `staging-bootstrap` protected environment의 Environment Variables 또는 gitignored local JSON으로만 주입한다.
5. repository의 `deploy/staging/staging-manifest.json`은 placeholder 기반 원본으로 유지한다.
6. bootstrap packet 승인과 infrastructure mutation 승인은 서로 다른 승인이다.
7. bootstrap packet이 승인돼도 project 생성, billing 연결 또는 배포를 실행할 수 없다.
8. 모든 승인 기록은 commit SHA와 artifact SHA-256에 결합한다.

## 2. 실제 운영 값 결정표

모든 항목이 `확정` 상태가 되기 전에는 실제 bootstrap workflow를 실행하지 않는다.

| 번호 | 결정 항목 | 현재 상태 | 권장 기준 | 최종 결정 값 기록 방식 |
|---|---|---|---|---|
| 1 | Staging Project ID | 미확정 | 소문자·숫자·하이픈, `staging` 포함, production과 명확히 구분 | GitHub variable `STAGING_PROJECT_ID` |
| 2 | Billing Account | 미확정 | 사용 권한과 예산 책임자가 확인한 실제 billing account | `STAGING_BILLING_ACCOUNT` |
| 3 | Forbidden Project IDs | 미확정 | production 및 공유 금지 프로젝트를 모두 포함 | `STAGING_FORBIDDEN_PROJECT_IDS_JSON` |
| 4 | Firebase Storage Bucket | 미확정 | project ID에 종속된 `<project-id>.firebasestorage.app` 또는 실제 Firebase bucket | `STAGING_STORAGE_BUCKET` |
| 5 | 월간 예산 | 미확정 | 원화 정수, 초기 staging은 낮은 한도로 시작 | `STAGING_MONTHLY_BUDGET_KRW` |
| 6 | 예산 알림 채널 | 미확정 | 비용 책임자가 실제 수신하는 이메일 또는 notification channel 식별자 | `STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON` |
| 7 | 데이터 보존 기간 | 미확정 | staging 데이터 최소 보존, 기본 검토안 14일 | `STAGING_DATA_RETENTION_DAYS` |
| 8 | Approval Reference | 미확정 | 날짜와 순번을 포함한 변경 불가능한 승인 식별자 | `STAGING_APPROVAL_REFERENCE` |
| 9 | Internal Flush 보안 결정 | 검토안 존재 | staging 한정 `mvp-staging-internal-token`; production 전 private endpoint 분리 | `STAGING_INTERNAL_FLUSH_DECISION` |

## 3. 항목별 결정 기준

### 3.1 Staging Project ID

허용 예시 형식:

```text
rhwp-collaboration-staging-123
rhwp-staging-korea-123
```

필수 조건:

- 6~30자 GCP project ID 규칙을 만족한다.
- `staging` 문자열을 포함한다.
- `prod` 또는 `production`을 포함하지 않는다.
- 기존 production project ID와 일치하지 않는다.
- 개인 실험용 또는 다른 서비스용 프로젝트를 재사용하지 않는다.
- 향후 Firebase Hosting site, service account, resource label에 사용해도 의미가 분명하다.

결정 증빙:

- GCP 조직 또는 계정에서 ID 사용 가능 여부 확인
- production project 목록과 대조
- 비용 책임자 확인

### 3.2 Billing Account

필수 조건:

- 형식: `XXXXXX-XXXXXX-XXXXXX`
- staging 비용을 부담할 계정인지 확인한다.
- 사용자 또는 배포 identity에 필요한 최소 billing 권한을 별도 검토한다.
- billing account 자체를 repository에 secret으로 저장하지 않는다.
- bootstrap packet에는 검토용 메타데이터로 포함될 수 있다.

결정 증빙:

- billing account 표시 이름
- 비용 책임자
- 월간 원화 예산 승인
- 예산 알림 수신자

### 3.3 Forbidden Project IDs

JSON 문자열 배열로 기록한다.

```json
["rhwp-production", "another-production-project"]
```

필수 조건:

- 실제 production project ID를 모두 포함한다.
- staging project ID는 포함하지 않는다.
- 빈 배열을 허용하지 않는다.
- 동일한 ID를 중복하지 않는다.

### 3.4 Firebase Storage Bucket

권장 결정:

```text
<STAGING_PROJECT_ID>.firebasestorage.app
```

필수 조건:

- staging project ID에 종속된다.
- production bucket과 다르다.
- `asia-northeast3` 데이터 위치 결정과 충돌하지 않는다.
- bucket 생성 여부는 bootstrap approval 이후 infrastructure 실행 단계에서 확인한다.

### 3.5 월간 예산

- 통화: `KRW`
- 입력 형식: 쉼표 없는 양의 정수
- 예: `50000`
- threshold는 manifest의 `50%`, `80%`, `100%`를 유지한다.
- 예산은 비용 차단 장치가 아니라 알림 장치임을 승인자가 이해해야 한다.
- 초기 운영 후 실제 사용량을 근거로 별도 승인 아래 조정한다.

### 3.6 예산 알림 채널

JSON 문자열 배열로 기록한다.

```json
["billing-admins@example.com"]
```

필수 조건:

- 최소 1개 채널을 포함한다.
- 실제 수신 가능한 책임자 주소 또는 GCP notification channel 식별자를 사용한다.
- 개인적으로 확인하지 않는 임시 이메일은 사용하지 않는다.

### 3.7 데이터 보존 기간

검토 기준:

- 기본 검토안: `14`일
- 최소한의 재현·장애 분석 기간만 보존한다.
- 학생 또는 사용자 데이터가 포함될 경우 학교·조직 개인정보 정책을 우선한다.
- 자동 삭제 구현은 별도 작업이며 이 값만으로 삭제를 허용하지 않는다.

### 3.8 Approval Reference

권장 형식:

```text
staging-bootstrap-approval-YYYY-MM-DD-NNN
```

필수 조건:

- 기존 승인과 중복되지 않는다.
- packet, approval record, infrastructure plan에서 동일하게 사용한다.
- 승인 내용을 변경하면 새 reference를 발급한다.

### 3.9 Internal Flush 보안 결정

현재 materializer가 허용하는 값:

```text
mvp-staging-internal-token
```

승인 의미:

- staging 한정으로 public Collaboration service와 high-entropy internal token 경계를 임시 수용한다.
- token 원문은 이 문서, values JSON, packet 또는 plan에 기록하지 않는다.
- production 배포 승인이 아니다.
- production 전에는 private service 또는 private endpoint 분리를 별도 설계·승인한다.

## 4. `staging-bootstrap` protected environment 결정

Environment 이름:

```text
staging-bootstrap
```

필수 설정:

- Required reviewer: 저장소 소유자 또는 staging 비용·보안 책임자
- Deployment branch/tag 제한: 수동 workflow와 승인된 branch만 허용
- Environment secrets: **없음**
- GCP WIF credential: **없음**
- `id-token: write`: **없음**
- Environment variables: 아래 9개만 등록

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

## 5. 승인 전 필수 증빙

- [ ] 실제 project ID 사용 가능 여부를 확인했다.
- [ ] production project ID 전체 목록을 확인했다.
- [ ] billing account 사용 권한과 비용 책임자를 확인했다.
- [ ] 월간 예산을 KRW로 승인받았다.
- [ ] budget notification 수신자가 실제 수신 가능함을 확인했다.
- [ ] Firebase 데이터 위치와 Storage bucket naming을 확인했다.
- [ ] staging 데이터 보존 기간이 개인정보 정책에 부합한다.
- [ ] internal flush staging 예외의 범위와 production 개선 의무를 이해했다.
- [ ] `staging-bootstrap` environment에 secret 또는 cloud credential을 넣지 않는다.
- [ ] bootstrap packet이 cloud mutation 또는 deployment 승인이 아님을 확인했다.

## 6. 결정 완료 조건

다음 조건을 모두 만족할 때만 이 문서의 상태를 `확정 / bootstrap packet 생성 승인`으로 변경한다.

1. 9개 값이 모두 concrete value다.
2. project ID와 forbidden project IDs가 충돌하지 않는다.
3. Storage bucket이 staging project에 종속된다.
4. billing account와 예산 책임자가 확인됐다.
5. 예산은 KRW 양의 정수다.
6. notification channel이 비어 있지 않다.
7. retention은 양의 정수다.
8. approval reference가 고유하다.
9. internal flush decision이 허용된 staging 값이다.
10. protected environment reviewer가 지정됐다.
11. 모든 값이 materializer validation을 통과한다.
12. `cloudMutationApproved=false`가 유지된다.

## 7. 승인 서명란

이 문서는 현재 초안이므로 아래 항목은 미기재 상태로 유지한다.

| 항목 | 기록 |
|---|---|
| 결정 상태 | 미승인 |
| 승인자 | 미기재 |
| 승인 시각 | 미기재 |
| 대상 commit SHA | 미기재 |
| Bootstrap workflow run ID | 미기재 |
| Packet SHA-256 | 미기재 |
| 비고 | 실제 값 확정 후 별도 승인 기록 생성 |
