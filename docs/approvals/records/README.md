# Staging Approval Records

이 디렉터리는 실제 staging 승인 artifact를 approval reference별로 보관하기 위한 위치다.

## 디렉터리 구조

```text
docs/approvals/records/<approval-reference>/
```

각 디렉터리는 하나의 변경 불가능한 승인 단위를 나타낸다. artifact 또는 운영 값이 변경되면 기존 디렉터리를 수정해 승인을 재사용하지 않고 새 approval reference를 발급한다.

## 허용 파일

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

## 금지 내용

다음 값은 이 디렉터리나 Git 기록에 넣지 않는다.

- access token 또는 ID token
- Authorization header
- password
- private key
- service-account key JSON
- secret 원문
- refresh token
- cookie 또는 session credential
- Firebase Web API key 원문; reference만 허용

Billing account, project ID, 이메일 알림 채널은 secret은 아니지만 운영 메타데이터이므로 필요한 승인 artifact에만 최소한으로 기록한다.

## 승인 결합 규칙

- Bootstrap approval record는 bootstrap packet JSON 원문 바이트의 SHA-256에 결합한다.
- Infrastructure approval record는 infrastructure plan JSON 원문 바이트의 SHA-256에 결합한다.
- Deployment approval record는 deployment packet, image digest, IAM diff, rollback evidence에 결합한다.
- 모든 record는 대상 commit SHA, 승인자, UTC 승인 시각을 기록한다.
- Bootstrap approval은 infrastructure mutation 또는 deployment를 허용하지 않는다.
- Infrastructure approval은 deployment를 허용하지 않는다.
- 별도 deployment approval 없이 staging deployment를 실행하지 않는다.

## 현재 상태

현재 repository에는 example record만 있고 actual approval record는 없다. 실제 운영 값, 실제 packet, 실제 승인자와 별도 승인이 없는 상태에서는 이 디렉터리에 approved record를 생성하지 않는다.
