# rhwp Staging Infrastructure Bootstrap Runbook

## Lifecycle 개요와 인계 문서

| 단계 | 상태 | 인계/근거 |
| ---: | --- | --- |
| 1-3 | 선행 절차 | [inputs](staging-bootstrap-inputs.md) → [readiness](staging-bootstrap-readiness.md) → [operator](staging-bootstrap-operator.md) |
| 4 | 선행 검토 | [bootstrap packet review](staging-bootstrap-packet-review.md) 및 bootstrap approval record |
| 5 | plan 생성 | `scripts/staging_infrastructure_plan.py`가 bootstrap manifest, packet, approval record에서 plan을 만듭니다. |
| 6 | 현재 범위 | 아래 approval validator/action manifest/readiness gate와 apply review package가 plan review 증거를 확인합니다. |
| 7 | 차단 | 별도 actual package 검토, cloud mutation approval과 미래 executor가 필요합니다. |
| 8-9 | 차단 | actual resource identifier 관찰 및 live read-only preflight는 7의 evidence 뒤에만 가능합니다. |
| 10-12 | 차단 | deployment packet, 별도 deployment approval, deployment는 독립 절차입니다. |

선행 runbook의 non-secret 산출물을 operator-local 경로로 복사한 뒤 아래 명령의 입력으로 사용합니다. bootstrap approval record와 `staging_infrastructure_plan.py`가 만든 plan이 없으면 이 runbook의 명령을 시작하지 않습니다.

## 상태와 안전 경계

이 runbook은 staging 전용 infrastructure 검토 증거를 생성하고 확인하는 현재 구현을 설명합니다. 현재 구현은 클라우드 인증, cloud CLI 호출, resource 생성·변경, GitHub Environment 변경, workflow dispatch, 배포를 수행하지 않습니다.

- tracked repository 상태: `no-tracked-actual-approval-record`
- 현재 지원: infrastructure plan 승인 검증, 구조화 action manifest 생성, execution readiness gate,
  non-mutating apply review package
- 현재 미지원: dry-run, apply, WIF 인증, environment 생성·구성, resource mutation, live preflight, image build/push, deployment
- 공통 출력 경계: `mutationCommands=[]`, deployment 권한은 항상 `false`, 실행 가능한 shell/argv는 생성하지 않습니다.

실제 운영 값, 승인 artifact, credential, token, private key, service-account key, Firebase API key 값, internal flush 원문은 추적 문서나 예시에 기록하지 않습니다.

## 세 가지 별도 승인

| 승인 | 검토 대상 | 현재 구현의 결과 | 다른 승인과의 관계 |
| --- | --- | --- | --- |
| Plan review approval | exact infrastructure plan bytes, commit, project/billing 바인딩, stage 순서, 예산, rollback 검토 | `cloudMutationApproved=false`이면 `awaiting-cloud-mutation-approval` | apply 권한이 아닙니다. |
| Cloud mutation approval | 동일한 증거에 바인딩한 별도 `cloudMutationApproved=true` record | 현재 executor가 없으므로 실행하지 않습니다. | plan review·deployment approval을 대체하지 않습니다. |
| Deployment approval | deployment packet, immutable image digest, live preflight, IAM diff, rollback/acceptance evidence | 현재 범위 밖이며 항상 별도입니다. | infrastructure mutation approval을 대체하지 않습니다. |

operator-local reviewed plan record가 존재하고 `cloudMutationApproved=false`라면 `awaiting-cloud-mutation-approval`으로 평가됩니다. 이는 apply 입력이 아니며 `--require-cloud-mutation` 검증도 통과하지 못합니다. tracked repository에는 actual approval record가 없습니다.

## 현재 구현된 검토 명령

이 구현은 operational metadata를 ignored local `artifacts/actual-infrastructure-review/`에만 보관하도록 선택합니다. `docs/approvals/records/`는 repository archival 호환 경로이지만, 그곳에 기록하려면 별도 사용자 승인과 redaction policy가 필요하며 여기서는 수행하지 않습니다.

### 1. Infrastructure approval 검증

```bash
python3 scripts/staging_infrastructure_approval.py \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --approval artifacts/actual-infrastructure-review/staging-infrastructure-approval-record.json \
  --json-output artifacts/actual-infrastructure-review/infrastructure-approval-result.json \
  --markdown-output artifacts/actual-infrastructure-review/infrastructure-approval-result.md
```

이 명령은 plan의 실제 바이트 SHA-256, canonical plan object digest, commit, project/billing, ordered stage IDs, budget, rollback acknowledgement를 fail-closed로 결합합니다. `cloudMutationApproved=false` record는 정상 검토 결과로 처리할 수 있지만 status는 `awaiting-cloud-mutation-approval`입니다. `--require-cloud-mutation`은 향후 별도 승인 record 검증용이며, 현재 record에는 사용하지 않습니다.

### 2. Action manifest 생성

```bash
python3 scripts/staging_infrastructure_actions.py \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --approval artifacts/actual-infrastructure-review/staging-infrastructure-approval-record.json \
  --json-output artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.json \
  --markdown-output artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.md
```

이 명령은 검토 증거만 생성합니다. action에는 `id`, `stageId`, classification, structured resource/evidence 정보만 포함되며 executable argv, shell string, credential, secret value는 포함되지 않습니다.

### 3. Execution readiness gate

```bash
python3 scripts/staging_infrastructure_execution_gate.py \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --execution-manifest artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.json \
  --approval-result artifacts/actual-infrastructure-review/infrastructure-approval-result.json \
  --json-output artifacts/actual-infrastructure-review/staging-infrastructure-readiness.json \
  --markdown-output artifacts/actual-infrastructure-review/staging-infrastructure-readiness.md \
  --strict-blocked-exit
```

gate는 canonical manifest와 approval-result의 digest·commit·plan object provenance를 재검증하고, 필요한 승인 목록만 보고합니다. 어떠한 cloud authentication이나 mutation도 하지 않습니다.

### 4. Apply review package

```bash
python3 scripts/staging_infrastructure_apply_review.py \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --approval-result artifacts/actual-infrastructure-review/infrastructure-approval-result.json \
  --execution-manifest artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.json \
  --executor-commit-sha <CALLER_DECLARED_UNVERIFIED_EXECUTOR_COMMIT_SHA> \
  --json-output artifacts/actual-infrastructure-review/staging-infrastructure-apply-review-package.json \
  --markdown-output artifacts/actual-infrastructure-review/staging-infrastructure-apply-review-package.md
```

이 명령은 exact plan bytes, canonical plan object, approval result, action set을 다시 결합하고,
`api-baseline`, `service-accounts`, `artifact-registry`, `secret-metadata` 네 stage의 구조화 mutation
후보만 추출합니다. 결과 status는 `ready-for-apply-review`이며 실제 apply 권한이 아닙니다.

package에는 `staging-infrastructure-apply` Environment desired state, GitHub OIDC claim mapping/조건과 WIF
변수 이름, 최소권한 custom role permission-set/scope diff, 실제 apply 전에 필요한 승인 목록, 그리고
호출자가 선언한 executor commit SHA가 포함됩니다. 이 SHA는 immutable verified provenance가 아니며,
미래 apply executor는 인증 전에 승인 브랜치 포함성, commit object/tree, 승인된 apply workflow 경로와
내용을 독립 검증해야 합니다. 실제 WIF provider ID, deployer service-account email, live IAM before-state는
자동 결정하지 않습니다.

현재 workflow `.github/workflows/staging-infrastructure-apply-review.yml`은 합성 증거로 이 package
생성 계약만 검증합니다. `contents: read`만 사용하며 environment, OIDC 권한, cloud authentication,
resource mutation이 없습니다. tracked pending declaration은
`docs/approvals/staging-infrastructure-mutation-approval-record.example.json`에 있습니다. 실제 승인
record는 사람이 actual package의 exact-byte SHA-256과 설정 diff를 검토한 뒤 ignored `artifacts/`
아래에서만 작성합니다.

### Completion marker와 strict blocked exit

approval validator, action manifest, readiness gate, apply review package CLI가 성공적으로 두 출력 파일을 모두 publish하면 JSON output 옆에 `.complete` completion marker를 만듭니다. 예를 들어 `artifacts/actual-infrastructure-review/staging-infrastructure-readiness.json.complete`입니다. marker는 두 산출물이 동일 실행에서 완성되었다는 로컬 publish 증거일 뿐, 승인·인증·apply 완료·배포 완료를 뜻하지 않습니다.

`--strict-blocked-exit`은 readiness status가 `blocked`일 때 exit code `2`를 반환합니다. 정상적인 `awaiting-cloud-mutation-approval` 또는 `awaiting-executor-design-approval`은 blocked가 아니므로 exit code `0`입니다. 입력/출력 계약 오류는 exit code `1`입니다.

### Bounded JSON과 digest 의미

네 CLI의 file 입력은 `O_NONBLOCK | O_CLOEXEC`로 file descriptor를 한 번 열고 같은 descriptor의 `fstat` 결과가 regular file이 아니면 즉시 거부합니다. 따라서 FIFO 같은 blocking special file을 기다리지 않습니다. regular file에서만 `MAX_JSON_BYTES + 1` bytes를 읽고, `MAX_JSON_BYTES=1,000,000`을 초과하면 거부합니다. 이후 strict UTF-8/JSON parsing과 duplicate-key, non-finite number, 최대 depth 64, 최대 node 10,000, 문자열 16,384 UTF-8 bytes의 JSON-domain 제한을 적용합니다. Public API에 직접 전달되는 raw bytes도 동일한 `MAX_JSON_BYTES` 제한을 받습니다.

`planSha256`은 입력 파일의 exact raw bytes digest이므로 공백·key 순서·마지막 newline 변경도 감지합니다. `planObjectSha256`은 JSON domain 검증 후 key를 정렬한 canonical serialization digest입니다. action generator와 readiness gate API에는 `plan_bytes`가 필수이며, parsed dict만 받는 two-argument 호출은 provenance를 충족하지 않습니다.

## Canonical stage 분류와 실행 경계

모든 stage는 canonical table에서만 분류합니다. 알 수 없는 stage, 누락된 required field, classification/action 불일치, disposition에 어긋나는 action은 fail-closed입니다. 어느 분류도 executable argv를 만들지 않습니다.

| 분류 | Stage | 현재 허용 범위 |
| --- | --- | --- |
| observation-only | `project-billing`, `post-bootstrap-evidence` | read-only identity/billing/evidence 확인만 합니다. |
| eligible-mutation | `api-baseline`, `service-accounts`, `artifact-registry`, `secret-metadata` | 미래 executor에서만 별도 allowlist와 승인 뒤 idempotent create/enable을 설계할 수 있습니다. 현재는 구조화 검토 증거만 생성합니다. |
| irreversible-manual-decision | `firebase-foundation`, `budget-guardrails` | 현재 observation only입니다. 위치·budget/channel의 실제 생성은 별도 콘솔/API 의사결정과 승인이 필요합니다. |
| deferred-resource-specific | `iam-bindings` | 모든 referenced resource 존재 및 exact before/after IAM diff 승인 전까지 deferred입니다. |
| blocked-deferred | `cloud-run-prerequisites`, `cloud-tasks-prerequisites` | immutable image digest, worker URL, deployment approval 및 queue/IAM diff 전까지 blocked입니다. |

`project-billing`은 project 생성·삭제·billing relink를 수행하지 않습니다. eligible-mutation stage도 API 자동 disable, service-account key 생성, secret version의 추가·읽기·출력, repository 삭제를 허용하지 않습니다.

## 구현된 review-package trust design과 미래 executor

현재 review-package builder는 caller가 넣은 attestation boolean이나 parsed object만 신뢰하지 않고 exact
plan bytes와 canonical execution manifest를 재구성합니다. 그러나 실제 apply workflow를 구현하기
전에는 추적하지 않는 actual plan/approval/manifest package의 비밀 없는 전달·저장 방식과 artifact
provenance 검증을 사용자가 별도로 승인해야 합니다.

미래 executor는 인증 전에 다음을 모두 수행해야 합니다.

1. caller-declared executor commit을 provenance로 신뢰하지 않고, 승인 브랜치 포함성 및 commit object/tree와
   `.github/workflows/staging-infrastructure-apply.yml`의 승인된 내용을 독립 검증한 뒤 실행한 revision을 evidence에 기록합니다.
2. exact plan bytes, approval record, execution manifest의 SHA-256과 canonical object digest를 서로 대조합니다.
3. GitHub protected environment의 required-reviewer 승인을 approval event로 사용합니다.
4. approved non-secret evidence transport에서 받은 artifact의 provenance와 digest를 검증합니다.
5. 검증 실패, 예상 밖 resource, allowlist 밖 action, evidence 불일치 시 첫 실패에서 중단하고 증거를 보존합니다.

특히 `cloudMutationApproved=true`라는 caller-provided boolean만으로 인증이나 apply를 시작해서는 안 됩니다.

## FUTURE REQUIREMENTS: actual transport, dry-run, apply, environment, WIF

다음은 현재 사용 가능한 명령이 아닙니다. 별도 사용자 승인과 구현이 완료되기 전에는 실행할 수 없습니다.

- Dry-run: exact canonical mutation subset에 대한 read-before-write evidence와 예상 diff를 산출하되, resource 변경은 하지 않아야 합니다.
- Apply: protected environment 승인, caller-declared commit의 독립 membership/tree/workflow 검증, exact
  plan/approval/manifest digest 검증을 끝낸 뒤에만 허용됩니다.
- `staging-infrastructure-apply` environment: required reviewer 최소 1명, prevent self-review 활성화,
  `canAdminsBypass=false`를 요구합니다. 이 setting의 platform/account 지원 여부는
  `required-before-apply`로 남으며 unsupported 또는 unverified이면 approval/apply를 fail-closed로 차단합니다.
  deployment branch policy에서 protected branches는 `false`, custom branch policies는 `true`로 두고
  branch policy `[{'name':'feat/firebase-collaboration-mvp-v1','type':'branch'}]`, tag policy `[]`만 허용합니다.
  long-lived cloud credential
  없음, WIF provider/audience/service-account identifier만 사용, least-privilege role diff가 필요합니다.
  이 environment의 생성·구성 자체도 별도 사용자 승인이 필요합니다.
- WIF/IAM: subject는 아직 구현되지 않은 별도 `.github/workflows/staging-infrastructure-apply.yml`에만
  바인딩하고, 현재 review workflow는 명시적으로 제외합니다. mapping은 `google.subject=assertion.sub`,
  `attribute.repository=assertion.repository`, `attribute.ref=assertion.ref`,
  `attribute.workflow_ref=assertion.workflow_ref`, `attribute.repository_id=assertion.repository_id`,
  `attribute.repository_owner_id=assertion.repository_owner_id`, `attribute.workflow_sha=assertion.workflow_sha`만
  사용합니다. actual repository ID, owner ID, reviewed workflow SHA는 null/unresolved로 유지하며 이 template은
  `applicable=false`입니다. final condition은 승인된 immutable repository ID·owner ID·reviewed workflow SHA와
  repository `WBmaker2/rhwp`, ref
  `refs/heads/feat/firebase-collaboration-mvp-v1`, workflow_ref
  `WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1`와
  정확히 일치해야 하며 workflow path claim은 사용하지 않습니다. `roles/iam.workloadIdentityUser`는 deployer
  service account에만 scope합니다. API enable, service-account create, Artifact Registry repository
  create/read, Secret Manager metadata create/read/list에는 각각 project-scope custom role의 exact permission
  set만 제안하며 disable/delete/key/version/access 권한은 포함하지 않습니다. IAM project scope만으로는
  resource identifier를 제한할 수 없으므로 live project-scope binding before/after diff와 executor의 exact
  action ID/resource/precondition allowlist 검증을 별도로 승인해야 합니다. key file, static secret,
  long-lived credential은 허용하지 않습니다.
- Rollback: 자동 delete rollback을 하지 않습니다. 미래 executor는 first-error에서 즉시 멈추고, 이미 관찰·변경된 상태와 evidence를 보존하여 사람이 후속 결정을 내리게 해야 합니다.

현재 review workflow의 artifact `staging-infrastructure-apply-review`는 합성 계약 증거입니다. actual
evidence artifact를 가져오거나 신뢰하는 기능은 없습니다. 실제 transport 구현에서는 source run ID,
source commit, artifact digest, package exact-byte SHA-256과 caller-declared executor commit을 함께
기록하되, 이를 provenance로 신뢰해서는 안 됩니다. 미래 executor는 인증 전에 해당 commit의 승인 브랜치
포함성, commit object/tree, apply workflow 경로와 내용을 독립 검증해야 하며, 그 검증이 끝나기 전에는
OIDC token을 요청하지 않아야 합니다.

## 남은 명시적 승인

apply 전에는 다음 각각에 대한 별도 사용자 승인이 필요합니다.

1. actual review package exact-byte SHA-256
2. actual evidence transport와 artifact provenance
3. actual canonical mutation subset
4. `staging-infrastructure-apply` Environment 설정 화면 diff
5. actual WIF identity와 live least-privilege IAM before/after diff
6. 사람이 작성한 `cloudMutationApproved=true` record
7. 실제 apply workflow diff와 workflow dispatch

`implementation branch publish`는 위 apply 승인들을 대체하지 않는 별도 integration approval입니다.

## Lifecycle 후속 상태

단계 8-12는 실제 단계 7 apply가 성공하여 actual resource identifier evidence를 남길 때까지 blocked입니다. 그 뒤에만 manifest observation update, live read-only preflight, immutable image build/push evidence, deployment packet, 별도 deployment approval, deployment executor, acceptance test, rollback evidence를 새 계획으로 다룹니다. deployment는 infrastructure lifecycle과 독립 승인입니다.

## 로컬 검증

```bash
python3 -m py_compile \
  scripts/staging_infrastructure_approval.py \
  scripts/staging_infrastructure_actions.py \
  scripts/staging_infrastructure_execution_gate.py \
  scripts/staging_infrastructure_apply_review.py \
  scripts/staging_infrastructure_apply_review_paths.py \
  scripts/staging_infrastructure_apply_review_policy.py \
  scripts/staging_infrastructure_synthetic_fixture.py \
  scripts/staging_infrastructure_action_io.py \
  scripts/staging_infrastructure_validation.py \
  scripts/tests/test_staging_infrastructure_approval.py \
  scripts/tests/test_staging_infrastructure_actions.py \
  scripts/tests/test_staging_infrastructure_execution_gate.py \
  scripts/tests/test_staging_infrastructure_apply_review.py \
  scripts/tests/test_staging_infrastructure_apply_review_policy.py

python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

이 검증은 cloud authentication, cloud resource mutation, live query, image build/push, deployment, push, PR 변경을 수행하지 않습니다.
