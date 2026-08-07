# rhwp Staging Bootstrap Packet Review and Approval Record

## 상태

- 적용 환경: `staging` only
- packet generator: `scripts/staging_approval_packet.py`
- review/record generator: `scripts/staging_bootstrap_approval_record.py`
- packet review schema: `rhwp.staging-bootstrap-packet-review/v1`
- review result schema: `rhwp.staging-bootstrap-packet-review-result/v1`
- approval record schema: `rhwp.staging-bootstrap-approval/v1`
- cloud authentication: 없음
- cloud query: 없음
- cloud mutation: 없음
- deployment authorization: 없음

## 1. 목적

이 단계는 실제 `staging-approval-packet-bootstrap` artifact를 사람이 검토한 뒤, 검토한 **정확한 packet 파일 바이트**에 승인 정보를 결합한다.

Approval record는 다음 항목을 하나의 변경 불가능한 증거로 묶는다.

1. packet JSON 원문 SHA-256
2. packet의 project ID와 billing account
3. packet의 approval reference
4. packet에 남아 있는 deferred path 전체
5. staging internal-flush security exception
6. 대상 commit SHA
7. packet을 생성한 workflow run ID
8. 승인자와 UTC 승인 시각

이 record는 infrastructure plan 생성 입력일 뿐이며 project 생성, billing 연결, API 활성화, IAM 변경, resource mutation 또는 deployment를 승인하지 않는다.

## 2. 시작 조건

다음 조건이 모두 충족되지 않으면 중단한다.

- 현재 head의 `CI`, `CodeQL`, `Render Diff`, `Staging configuration`이 동일 commit에서 `completed/success`
- 실제 운영 값 결정서와 체크리스트가 승인됨
- readiness status가 `ready-for-bootstrap-packet`
- `staging-bootstrap` protected environment가 검토됨
- 실제 bootstrap workflow가 성공함
- artifact 이름이 `staging-approval-packet-bootstrap`
- artifact에서 추출한 `staging-approval-packet.json`이 존재함
- packet의 `phase=bootstrap`
- packet의 `status=ready-for-bootstrap-approval`

## 3. 실제 packet 보관

권장 승인 디렉터리:

```text
docs/approvals/records/<approval-reference>/
```

Artifact에서 다음 파일을 그대로 복사한다.

```text
staging-manifest-bootstrap.json
staging-preflight-static.json
staging-approval-packet.json
staging-approval-packet.md
```

`staging-approval-packet.json`은 digest 계산 전에 pretty-print, key sorting, newline 변경 또는 formatter 실행을 하지 않는다. JSON 의미가 같아도 파일 바이트가 바뀌면 SHA-256이 달라진다.

## 4. Packet SHA-256 계산

macOS:

```bash
shasum -a 256 staging-approval-packet.json
```

Python:

```bash
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

path = Path('staging-approval-packet.json')
print(sha256(path.read_bytes()).hexdigest())
PY
```

계산한 64자리 lowercase digest를 review declaration의 `expectedPacketSha256`에 기록한다.

Generator는 packet 파일 원문 바이트를 다시 계산해 digest가 정확히 일치하는지 검사한다. Packet에 공백 또는 newline 하나가 추가돼도 기존 review declaration은 거부된다.

## 5. Review declaration 작성

Template:

```text
docs/approvals/staging-bootstrap-packet-review.example.json
```

실제 승인 디렉터리에 다음 이름으로 복사한다.

```text
staging-bootstrap-packet-review.json
```

Pending template의 다음 필드는 실제 검토가 끝난 후에만 수정한다.

```text
decision=approved
approvedAt=<UTC YYYY-MM-DDTHH:MM:SSZ>
approvedBy=[<actual approver>]
commitSha=<packet 대상 commit SHA>
workflowRunId=<actual bootstrap workflow run ID>
expectedPacketSha256=<exact packet file digest>
expectedApprovalReference=<packet approval.reference>
```

모든 acknowledgement는 실제 확인 후 `true`로 변경한다.

```text
packetReviewed
deferredPathsAccepted
billingAndBudgetReviewed
internalFlushExceptionAccepted
cloudMutationNotApproved
deploymentNotApproved
```

`decision=pending`, `decision=rejected`, null 승인 시각, 빈 승인자, zero run ID 또는 false acknowledgement가 있으면 generator는 approval record를 만들지 않는다.

## 6. 사람이 검토할 packet 항목

### Project와 production 분리

- project ID가 staging 전용이다.
- project ID에 `staging`이 포함된다.
- project ID에 `prod` 또는 `production`이 포함되지 않는다.
- forbidden project 목록에 실제 production project가 포함된다.
- staging project ID가 forbidden 목록에 포함되지 않는다.

### Billing과 예산

- billing account가 승인된 비용 계정이다.
- 월간 예산 통화가 `KRW`다.
- 예산 금액이 승인된 양의 정수다.
- threshold가 50%, 80%, 100%다.
- notification channel이 실제 수신 가능하다.

### Deferred paths

Packet의 `deferredValues[*].path`를 모두 검토한다. Bootstrap approval에서는 resource 생성 후에만 확정되는 값만 허용된다.

예:

```text
manifest.project.number
manifest.firebase.webAppId
manifest.firebase.apiKeyReference
manifest.cloudRun.*.image
manifest.cloudRun.*.digest
manifest.tasks.parse.targetUrl
manifest.tasks.export.targetUrl
manifest.operations.rollbackRevisionIds[*]
```

Generator는 packet에서 path를 직접 추출하고 정렬해 approval record의 `acceptedDeferredPaths`로 기록한다. 중복 또는 allowlist 밖의 path가 있으면 거부한다.

### Internal flush security

현재 staging exception:

```text
mvp-staging-internal-token
```

승인 의미:

- staging 한정 public Collaboration service와 high-entropy internal token 경계를 임시 수용한다.
- token 원문을 packet, review 또는 record에 기록하지 않는다.
- production 승인으로 해석하지 않는다.
- production 전 private service 또는 private endpoint 분리가 필요하다.

### 안전 플래그

다음 값이 모두 유지돼야 한다.

```text
packet.approval.cloudMutationApproved=false
packet.approval.packetIsDeploymentApproval=false
packet.security.readOnly=true
packet.security.containsCloudMutationCommands=false
packet.security.mutationCommands=[]
packet.preflight.comparisonMode=static-only
packet.preflight.live=null
```

## 7. Local generator 실행

```bash
python3 scripts/staging_bootstrap_approval_record.py \
  --packet docs/approvals/records/<approval-reference>/staging-approval-packet.json \
  --review docs/approvals/records/<approval-reference>/staging-bootstrap-packet-review.json \
  --record-output docs/approvals/records/<approval-reference>/staging-bootstrap-approval-record.json \
  --review-json-output docs/approvals/records/<approval-reference>/staging-bootstrap-packet-review-result.json \
  --review-markdown-output docs/approvals/records/<approval-reference>/staging-bootstrap-packet-review-result.md
```

성공 출력:

```json
{
  "status": "approved-record-generated",
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "mutationCommands": []
}
```

출력 파일:

```text
staging-bootstrap-packet-review-result.json
staging-bootstrap-packet-review-result.md
staging-bootstrap-approval-record.json
```

실패 시 final output과 `.tmp` 파일을 남기지 않는다.

## 8. Approval record 독립 검증

Generator는 내부적으로 기존 infrastructure planner validator를 호출한다. 별도로 다음 검증을 수행할 수 있다.

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

from scripts.staging_infrastructure_plan import validate_bootstrap_approval_record

root = Path('docs/approvals/records/<approval-reference>')
packet_path = root / 'staging-approval-packet.json'
packet = json.loads(packet_path.read_text())
record = json.loads((root / 'staging-bootstrap-approval-record.json').read_text())
digest = hashlib.sha256(packet_path.read_bytes()).hexdigest()
validate_bootstrap_approval_record(record, packet, digest)
print('approval record validation: pass')
PY
```

## 9. GitHub protected review workflow

Manual workflow phase:

```text
approval_phase=bootstrap-review
live_check=false
bootstrap_packet_path=docs/approvals/records/<approval-reference>/staging-approval-packet.json
bootstrap_review_path=docs/approvals/records/<approval-reference>/staging-bootstrap-packet-review.json
```

Protected environment contract:

```text
staging-bootstrap-approval
```

Job properties:

- `contents: read` only
- `id-token: write` 없음
- GCP/Firebase authentication 없음
- cloud CLI 설치 없음
- mutation command 없음

Expected artifact:

```text
staging-bootstrap-approval-review
```

이 workflow contract는 repository에 정의할 뿐 실제 Environment를 생성하거나 reviewer를 지정하지 않는다.

## 10. 보관과 변경 규칙

Approval reference별 디렉터리는 변경 불가능한 승인 단위다.

다음 중 하나라도 바뀌면 새 approval reference와 새 review를 만든다.

- packet 파일 바이트
- project ID
- billing account
- budget 또는 notification channel
- deferred path
- security exception
- commit SHA
- workflow run ID
- approver 또는 승인 범위

기존 digest나 approval record를 수정해 새 packet에 재사용하지 않는다.

## 11. 금지 내용

다음 값은 review declaration, review result 또는 approval record에 넣지 않는다.

- access token 또는 ID token
- Authorization header
- password
- private key
- service-account key JSON
- secret 원문
- refresh token
- Firebase Web API key 원문
- internal flush token 원문
- cloud mutation command

## 12. 다음 단계

승인 record 생성과 독립 검증이 끝나면 다음 입력으로 infrastructure plan을 생성할 수 있다.

```text
staging-manifest-bootstrap.json
staging-approval-packet.json
staging-bootstrap-approval-record.json
```

Bootstrap approval record가 있어도 resource 생성은 허용되지 않는다. Infrastructure plan을 검토하고 별도 `staging-infrastructure-approval` record가 명시적으로 cloud mutation을 승인해야만 다음 실행 단계를 설계할 수 있다.
