# rhwp Staging Approval Packet Generator

## 상태

- 적용 환경: staging only
- generator: `scripts/staging_approval_packet.py`
- unit tests: `scripts/tests/test_staging_approval_packet.py`
- workflow: `.github/workflows/staging-config-validate.yml`
- 실제 Firebase/GCP 리소스 변경: 없음
- cloud CLI 실행: 없음
- 이 문서 또는 생성된 packet 자체가 배포 승인을 의미하지 않음

## 1. 목적

Staging Approval Packet Generator는 다음 세 입력을 검토 가능한 하나의 JSON·Markdown 승인 패킷으로 변환한다.

```text
deploy/staging/staging-manifest.json
artifacts/staging-preflight-static.json
artifacts/staging-preflight-live.json  # 선택 입력
```

생성 결과:

```text
artifacts/staging-approval-packet.json
artifacts/staging-approval-packet.md
```

Generator는 입력 파일만 읽는다. `gcloud`, `firebase`, Docker, Cloud Run, Cloud Tasks, IAM, billing 또는 Secret Manager 명령을 실행하지 않는다.

## 2. 실행 전 필수 조건

다음 조건 중 하나라도 충족하지 않으면 승인 패킷을 생성하지 않는다.

1. manifest schema가 `rhwp.staging/v1`이다.
2. environment가 `staging`이다.
3. `operations.cloudMutationApproved=false`가 유지된다.
4. manifest 전체에 `${PLACEHOLDER}` 또는 문자열 내부 placeholder가 남아 있지 않다.
5. static report schema가 `rhwp.preflight-report/v1`이다.
6. static report mode와 status가 각각 `static`, `pass`다.
7. static report의 `cloudQueries`와 `mutationCommands`가 빈 배열이다.
8. live report를 입력하면 mode가 `live`이고 status가 `pass` 또는 `review`다.
9. 모든 report의 `projectId`가 manifest project ID와 일치한다.
10. 모든 report의 `mutationCommands`가 빈 배열이다.

현재 repository manifest에는 승인 전 placeholder가 의도적으로 남아 있으므로 PR static job에서는 packet을 생성하지 않는다. 실제 packet 생성은 concrete manifest와 보호된 `workflow_dispatch live_check=true` 실행에서만 수행한다.

## 3. 로컬 실행

Static report만 사용하는 검토 초안:

```bash
python3 scripts/staging_approval_packet.py \
  --manifest deploy/staging/staging-manifest.json \
  --static-report artifacts/staging-preflight-static.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

Static·live report를 모두 사용하는 실제 승인 검토 패킷:

```bash
python3 scripts/staging_approval_packet.py \
  --manifest deploy/staging/staging-manifest.json \
  --static-report artifacts/staging-preflight-static.json \
  --live-report artifacts/staging-preflight-live.json \
  --json-output artifacts/staging-approval-packet.json \
  --markdown-output artifacts/staging-approval-packet.md
```

Placeholder가 남아 있으면 generator는 종료 코드 1로 중단하며 성공 packet을 쓰지 않는다. 오류에는 placeholder가 발견된 JSON path만 기록하고 값은 기록하지 않는다.

## 4. Packet 내용

### 4.1 Project와 Firebase

- project ID와 project number
- billing account
- `asia-northeast3` region
- forbidden project ID 목록
- Firebase Web App ID와 API key reference
- authorized domains
- Firestore·Storage location
- Storage bucket과 Hosting site

### 4.2 Budget

- 통화 `KRW`
- 승인 대상 월간 예산 금액
- 50%·80%·100% threshold
- notification channel

금액은 변환하지 않고 manifest의 원화 정수 값을 그대로 기록한다.

### 4.3 IAM diff

기존 live preflight가 조회하는 project IAM policy 범위에서는 다음처럼 비교한다.

```text
present  -> plannedAction=none
missing  -> plannedAction=grant-after-approval
```

Secret, queue, bucket, Cloud Run처럼 resource-level IAM policy를 기존 preflight가 직접 조회하지 않는 항목은 누락으로 단정하지 않는다.

```text
state=not-observed
plannedAction=verify-before-grant
```

이 항목은 실제 mutation 전에 별도 조회와 승인이 필요하다.

### 4.4 Secret metadata

Packet에는 다음 metadata만 들어간다.

- secret 이름
- version reference
- manifest IAM 계약에서 파생한 access principal
- `valueIncluded=false`

Secret 원문, token과 credential은 넣지 않는다.

### 4.5 Cloud Run과 Cloud Tasks

Cloud Run:

- service 이름
- image와 digest
- service account
- ingress
- 공개 도달 경계
- CPU, memory, concurrency, timeout, scale

Cloud Tasks:

- parse/export queue 이름과 location
- target URL
- retry와 rate limit
- `dispatchDeadlineSeconds=900`
- caller service account

### 4.6 보안 결정과 rollback

- `internalFlushSecurityDecision`
- staging의 public Collaboration service + high-entropy internal token 제한
- production 전 private service 또는 private endpoint 분리 권고
- Cloud Run revision ID 3개
- data retention
- 자동 삭제 금지

### 4.7 Acceptance tests

Packet은 다음 11개 검증 항목을 pending checklist로 생성한다.

1. Google 로그인과 ACL
2. 200 MiB 이하 HWP 업로드
3. parse worker 완료
4. 두 번째 계정의 공유 링크 수락
5. 두 브라우저 동시 편집
6. WebSocket 재연결과 상태 수렴
7. Collaboration restart와 snapshot 복구
8. HWPX export
9. export HWPX 재가져오기
10. 편집 내용과 readonly 복잡 개체 보존
11. rollback revision 준비

## 5. Redaction 계약

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

Markdown은 raw manifest나 raw report에서 직접 렌더링하지 않는다. 먼저 sanitized JSON packet을 만든 뒤 그 packet만 사용한다.

## 6. GitHub Actions

Workflow: `Staging configuration`

PR과 `live_check=false` 실행:

- 기존 Python tests와 static preflight만 실행
- repository placeholder manifest로 packet 생성하지 않음
- 기존 static report artifact 유지

승인된 `workflow_dispatch live_check=true` 실행:

1. `staging-preflight` protected environment 승인을 통과한다.
2. WIF로 read-only identity를 사용한다.
3. live job 안에서 static report를 다시 생성한다.
4. 기존 live read-only preflight를 실행한다.
5. 두 report와 concrete manifest로 packet을 생성한다.
6. 다음 artifact를 업로드한다.

```text
staging-preflight-report-live
staging-approval-packet
```

`staging-approval-packet` artifact에는 다음 파일이 포함된다.

```text
staging-preflight-static.json
staging-preflight-live.json
staging-approval-packet.json
staging-approval-packet.md
```

Workflow에는 cloud mutation job이나 직접적인 `gcloud`·`firebase` mutation 명령이 없다.

## 7. 검증

```bash
python3 -m py_compile \
  scripts/staging_approval_packet.py \
  scripts/tests/test_staging_approval_packet.py

python3 -m unittest \
  scripts.tests.test_staging_approval_packet \
  -v

python3 -m unittest discover \
  -s scripts/tests \
  -p 'test_*.py' \
  -v

python3 scripts/validate_staging_config.py
```

배포 또는 cloud mutation은 이 검증 범위에 포함되지 않는다.
