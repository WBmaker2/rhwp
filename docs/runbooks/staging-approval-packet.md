# rhwp Staging Approval Packet Generator

## 상태

- 적용 환경: staging only
- generator: `scripts/staging_approval_packet.py`
- unit tests: `scripts/tests/test_staging_approval_packet.py`, `scripts/tests/test_staging_approval_packet_phases.py`
- workflow: `.github/workflows/staging-config-validate.yml`
- 실제 Firebase/GCP 리소스 변경: 없음
- generator의 cloud CLI 실행: 없음
- packet 생성은 리소스 생성이나 배포 승인을 의미하지 않음

## 1. 목적

Staging Approval Packet Generator는 staging 수명 주기의 승인 시점을 다음 두 단계로 분리한다.

| Phase | 시점 | Cloud 조회 | Placeholder 정책 |
|---|---|---|---|
| `bootstrap` | staging 리소스 생성 전 | 없음 | 정확히 허용된 resource-derived 값만 유예 |
| `deployment` | live preflight 후, 배포 전 | 기존 read-only preflight 결과 사용 | 모든 placeholder 금지 |

두 phase 모두 다음 파일을 출력한다.

```text
artifacts/staging-approval-packet.json
artifacts/staging-approval-packet.md
```

Generator는 manifest와 preflight JSON만 읽는다. `gcloud`, `firebase`, Docker, Cloud Run, Cloud Tasks, IAM, billing 또는 Secret Manager 명령을 실행하지 않는다.

## 2. 공통 입력 계약

다음 조건 중 하나라도 충족하지 않으면 packet을 생성하지 않는다.

1. manifest schema가 `rhwp.staging/v1`이다.
2. environment가 `staging`이다.
3. `operations.cloudMutationApproved=false`가 유지된다.
4. static report schema가 `rhwp.preflight-report/v1`이다.
5. static report mode와 status가 각각 `static`, `pass`다.
6. static report의 `cloudQueries`와 `mutationCommands`가 빈 배열이다.
7. 모든 report의 `projectId`가 manifest project ID와 일치한다.
8. 모든 report의 `mutationCommands`가 빈 배열이다.
9. secret 원문, token, credential 또는 private key를 입력 계약이나 출력에 포함하지 않는다.

## 3. Bootstrap phase

### 3.1 목적

Bootstrap packet은 staging project·billing·region·원화 예산·IAM·service account·queue·보안 결정을 검토한 뒤, 아직 생성되지 않은 리소스의 준비 작업을 별도로 승인하기 위한 문서다.

Bootstrap은 live report를 받지 않는다. live report가 전달되면 실패한다.

### 3.2 Bootstrap에서 반드시 concrete여야 하는 값

- staging project ID
- forbidden production project ID 목록
- billing account
- `asia-northeast3` region
- Firebase auth domain과 authorized domain
- Artifact Registry 이름과 위치
- Cloud Run service 이름, service account, ingress, runtime
- Cloud Tasks caller account, queue 이름, target URL, retry, rate limit, deadline
- IAM principal, role, resource
- Secret 이름과 version reference
- 월간 예산 원화 금액, 50%·80%·100% threshold, 알림 채널
- data retention
- approval reference
- internal flush security decision

### 3.3 Bootstrap에서만 허용되는 deferred path

다음 14개 경로만 placeholder를 유지할 수 있다.

```text
manifest.project.number
manifest.firebase.webAppId
manifest.firebase.apiKeyReference
manifest.firebase.storageBucket
manifest.firebase.hostingSite
manifest.cloudRun.collaboration.image
manifest.cloudRun.collaboration.digest
manifest.cloudRun.documentApi.image
manifest.cloudRun.documentApi.digest
manifest.cloudRun.documentWorker.image
manifest.cloudRun.documentWorker.digest
manifest.operations.rollbackRevisionIds[0]
manifest.operations.rollbackRevisionIds[1]
manifest.operations.rollbackRevisionIds[2]
```

허용 이유:

- project number: staging project가 존재한 뒤 확정
- Firebase 식별자: Firebase resource 생성 뒤 확정
- image와 digest: container build와 digest 조회 뒤 확정
- rollback revision: 최초 Cloud Run 배포 뒤 확정

목록에 없는 placeholder는 bootstrap에서도 실패한다. 오류에는 값이 아니라 JSON path만 기록한다.

### 3.4 실행

```bash
python3 scripts/staging_approval_packet.py \
  --phase bootstrap \
  --manifest deploy/staging/staging-manifest.json \
  --static-report artifacts/staging-preflight-static.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

Bootstrap packet 핵심 필드:

```json
{
  "schemaVersion": "rhwp.staging-approval-packet/v1",
  "phase": "bootstrap",
  "status": "ready-for-bootstrap-approval",
  "deferredValues": []
}
```

실제 deferred value가 있으면 `deferredValues`에 path와 해결 시점을 기록한다.

## 4. Deployment phase

### 4.1 목적

Deployment packet은 실제 staging project 상태를 read-only로 조회한 뒤 container image, Firebase 식별자, IAM diff와 rollback 정보를 포함해 배포 여부를 검토하는 문서다.

### 4.2 필수 조건

- live report가 반드시 존재한다.
- live report mode는 `live`다.
- live report status는 `pass` 또는 `review`다.
- manifest 전체에 placeholder가 하나도 없어야 한다.
- image digest, Firebase 식별자와 rollback 전략이 concrete여야 한다.

Live status가 `pass`이면 packet status는 `ready-for-deployment-approval`이다. 예상하지 못한 resource 등으로 live status가 `review`이면 packet status는 `review-required`다.

### 4.3 실행

```bash
python3 scripts/staging_approval_packet.py \
  --phase deployment \
  --manifest deploy/staging/staging-manifest.json \
  --static-report artifacts/staging-preflight-static.json \
  --live-report artifacts/staging-preflight-live.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

Deployment packet 핵심 필드:

```json
{
  "schemaVersion": "rhwp.staging-approval-packet/v1",
  "phase": "deployment",
  "status": "ready-for-deployment-approval",
  "deferredValues": []
}
```

## 5. Packet 공통 내용

- project ID, number, billing account, region, forbidden project IDs
- Firebase Web App·domain·Firestore·Storage·Hosting metadata
- 통화 `KRW`, 월간 예산, threshold와 notification channel
- IAM `present`, `missing`, `not-observed` 비교
- Secret 이름, version, access principal, `valueIncluded=false`
- Cloud Run service, digest, ingress, reachability, runtime
- Cloud Tasks queue, retry, rate limit, 900초 deadline
- internal flush security decision
- rollback revision과 data retention
- 11개 staging acceptance checklist
- static/live preflight evidence
- `mutationCommands=[]`

금액은 변환하지 않고 manifest의 원화 값을 그대로 기록한다.

## 6. Redaction 계약

다음 key 또는 값은 `[REDACTED]`로 치환한다.

```text
access token
ID token
authorization
credential
client secret
refresh token
password
private key
secret value
Bearer token 문자열
```

Markdown은 raw manifest나 raw report에서 직접 만들지 않는다. sanitized JSON packet만 사용해 렌더링한다.

## 7. GitHub Actions

Workflow: `Staging configuration`

### 7.1 workflow_dispatch 입력

```text
approval_phase=none|bootstrap|deployment
live_check=false|true
manifest_path=<repository-relative path>
```

허용 조합:

```text
none + false
bootstrap + false
deployment + true
```

다른 조합은 static job에서 실패한다.

### 7.2 Bootstrap job

```text
approval_phase=bootstrap
live_check=false
```

- GCP 인증 없음
- cloud CLI 설치 없음
- static preflight와 bootstrap generator만 실행
- artifact: `staging-approval-packet-bootstrap`

### 7.3 Deployment job

```text
approval_phase=deployment
live_check=true
```

- `staging-preflight` protected environment 사용
- WIF read-only identity 사용
- static report 재생성
- live read-only preflight 실행
- deployment generator 실행
- artifacts:
  - `staging-preflight-report-live`
  - `staging-approval-packet-deployment`

Workflow에는 cloud resource 생성·수정·삭제·배포 명령이 없다.

## 8. 검증

```bash
python3 -m py_compile \
  scripts/staging_approval_packet.py \
  scripts/tests/test_staging_approval_packet.py \
  scripts/tests/test_staging_approval_packet_phases.py

python3 -m unittest discover \
  -s scripts/tests \
  -p 'test_*.py' \
  -v

python3 scripts/validate_staging_config.py
```

배포, live preflight 실행, cloud authentication, image build/push와 cloud mutation은 이 구현 검증 범위에 포함되지 않는다.
