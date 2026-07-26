# Staging Approval Records

이 디렉터리는 실제 staging 승인 artifact를 approval reference별로 보관하기 위한 위치다.

## 디렉터리 구조

```text
docs/approvals/records/<approval-reference>/
```

각 디렉터리는 하나의 변경 불가능한 승인 단위를 나타낸다. artifact 또는 운영 값이 변경되면 기존 디렉터리를 수정해 승인을 재사용하지 않고 새 approval reference를 발급한다.

## 허용 파일

```text
staging-bootstrap-operator-status.json
staging-bootstrap-operator-status.md
staging-bootstrap-packet-review-draft.json
staging-manifest-bootstrap.json
staging-preflight-static.json
staging-approval-packet.json
staging-approval-packet.md
staging-bootstrap-packet-review.json
staging-bootstrap-packet-review-result.json
staging-bootstrap-packet-review-result.md
staging-bootstrap-approval-record.json
staging-infrastructure-plan.json
staging-infrastructure-plan.md
staging-infrastructure-approval-record.json
staging-preflight-live.json
staging-deployment-approval-packet.json
staging-deployment-approval-packet.md
staging-deployment-approval-record.json
```

`staging-bootstrap-operator-status.*`는 현재 lifecycle 단계와 다음 허용 작업을 기록하는 비변경형 상태 증빙이다. `staging-bootstrap-packet-review-draft.json`은 exact packet bytes에서 생성된 pending 초안이며 승인 기록이 아니다.

`staging-bootstrap-packet-review.json`은 사람이 작성한 검토 선언이다. `staging-bootstrap-packet-review-result.*`와 `staging-bootstrap-approval-record.json`은 generator가 exact packet bytes와 review declaration을 검증한 뒤 생성한다.

## Operator status와 pending draft

Actual 운영 단계에서는 다음 순서로 operator evidence를 사용할 수 있다.

```text
actual readiness input
→ operator status
→ actual bootstrap packet
→ operator exact-byte digest 검증
→ pending packet review draft
→ 사람의 packet 검토
→ approved packet review declaration
```

관련 runbook:

```text
docs/runbooks/staging-bootstrap-operator.md
```

다음 artifact는 승인으로 해석하지 않는다.

- `staging-bootstrap-operator-status.json`
- `staging-bootstrap-operator-status.md`
- `staging-bootstrap-packet-review-draft.json`
- `decision=pending`인 모든 review declaration

Operator status가 `ready-for-infrastructure-plan`이어도 infrastructure mutation 또는 deployment가 승인된 것은 아니다.

## Packet review와 approval record

Bootstrap approval record를 만들기 전에 다음 순서를 따른다.

```text
actual bootstrap packet artifact
→ exact packet SHA-256 계산
→ 사람의 packet 검토
→ approved review declaration
→ review/result generator
→ planner-compatible bootstrap approval record
```

관련 runbook:

```text
docs/runbooks/staging-bootstrap-packet-review.md
```

Packet JSON 파일은 digest 계산 전후에 formatter, key sorting, newline 변경 또는 pretty-print를 적용하지 않는다. 파일 바이트가 바뀌면 기존 review와 approval record를 재사용하지 않는다.

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
- internal flush token 원문
- cloud mutation command

Billing account, project ID, 이메일 알림 채널은 secret은 아니지만 운영 메타데이터이므로 필요한 승인 artifact에만 최소한으로 기록한다.

## 승인 결합 규칙

- Bootstrap operator는 packet source commit·workflow run ID와 exact packet bytes를 결합하지만 승인자를 만들지 않는다.
- Bootstrap packet review declaration은 exact bootstrap packet JSON 원문 바이트의 SHA-256을 `expectedPacketSha256`으로 기록한다.
- Bootstrap approval record는 generator가 다시 계산한 packet SHA-256, packet의 project·billing·deferred paths·security exception, commit SHA, workflow run ID, 승인자와 UTC 승인 시각에 결합한다.
- Infrastructure approval record는 infrastructure plan JSON 원문 바이트의 SHA-256에 결합한다.
- Deployment approval record는 deployment packet, image digest, IAM diff, rollback evidence에 결합한다.
- 모든 record는 대상 commit SHA, 승인자, UTC 승인 시각을 기록한다.
- Bootstrap approval은 infrastructure mutation 또는 deployment를 허용하지 않는다.
- Infrastructure approval은 deployment를 허용하지 않는다.
- 별도 deployment approval 없이 staging deployment를 실행하지 않는다.

## 현재 상태

현재 repository에는 example record, pending review template와 synthetic test evidence만 있고 actual approval record는 없다. 실제 운영 값, 실제 packet, 실제 승인자와 별도 승인이 없는 상태에서는 이 디렉터리에 approved record를 생성하지 않는다.
