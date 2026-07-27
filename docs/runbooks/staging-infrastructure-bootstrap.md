# rhwp Staging Infrastructure Bootstrap Runbook

## 상태와 안전 경계

이 runbook은 staging 전용 infrastructure 검토 증거를 생성하고 확인하는 현재 구현을 설명합니다. 현재 구현은 클라우드 인증, cloud CLI 호출, resource 생성·변경, GitHub Environment 변경, workflow dispatch, 배포를 수행하지 않습니다.

- 현재 상태: `awaiting-cloud-mutation-approval`
- 현재 지원: infrastructure plan 승인 검증, 구조화 action manifest 생성, execution readiness gate
- 현재 미지원: dry-run, apply, WIF 인증, environment 생성·구성, resource mutation, live preflight, image build/push, deployment
- 공통 출력 경계: `mutationCommands=[]`, deployment 권한은 항상 `false`, 실행 가능한 shell/argv는 생성하지 않습니다.

실제 운영 값, 승인 artifact, credential, token, private key, service-account key, Firebase API key 값, internal flush 원문은 추적 문서나 예시에 기록하지 않습니다.

## 세 가지 별도 승인

| 승인 | 검토 대상 | 현재 구현의 결과 | 다른 승인과의 관계 |
| --- | --- | --- | --- |
| Plan review approval | exact infrastructure plan bytes, commit, project/billing 바인딩, stage 순서, 예산, rollback 검토 | `cloudMutationApproved=false`이면 `awaiting-cloud-mutation-approval` | apply 권한이 아닙니다. |
| Cloud mutation approval | 동일한 증거에 바인딩한 별도 `cloudMutationApproved=true` record | 현재 executor가 없으므로 실행하지 않습니다. | plan review·deployment approval을 대체하지 않습니다. |
| Deployment approval | deployment packet, immutable image digest, live preflight, IAM diff, rollback/acceptance evidence | 현재 범위 밖이며 항상 별도입니다. | infrastructure mutation approval을 대체하지 않습니다. |

현재 actual plan-review record의 `cloudMutationApproved=false`는 plan 검토에만 유효합니다. 이 record는 apply 입력이 될 수 없으며, `--require-cloud-mutation` 검증도 통과하지 못합니다.

## 현재 구현된 검토 명령

아래 `<reviewed-evidence-dir>`은 비밀이 없는 검토 완료 증거를 보관하는 로컬 경로 placeholder입니다. 출력 경로도 로컬 검토 산출물 placeholder이며, 운영 값을 의미하지 않습니다.

### 1. Infrastructure approval 검증

```bash
python3 scripts/staging_infrastructure_approval.py \
  --plan <reviewed-evidence-dir>/staging-infrastructure-plan.json \
  --approval <reviewed-evidence-dir>/staging-infrastructure-approval-record.json \
  --json-output <review-output-dir>/infrastructure-approval-result.json \
  --markdown-output <review-output-dir>/infrastructure-approval-result.md
```

이 명령은 plan의 실제 바이트 SHA-256, canonical plan object digest, commit, project/billing, ordered stage IDs, budget, rollback acknowledgement를 fail-closed로 결합합니다. `cloudMutationApproved=false` record는 정상 검토 결과로 처리할 수 있지만 status는 `awaiting-cloud-mutation-approval`입니다. `--require-cloud-mutation`은 향후 별도 승인 record 검증용이며, 현재 record에는 사용하지 않습니다.

### 2. Action manifest 생성

```bash
python3 scripts/staging_infrastructure_actions.py \
  --plan <reviewed-evidence-dir>/staging-infrastructure-plan.json \
  --approval <reviewed-evidence-dir>/staging-infrastructure-approval-record.json \
  --json-output <review-output-dir>/staging-infrastructure-execution-manifest.json \
  --markdown-output <review-output-dir>/staging-infrastructure-execution-manifest.md
```

이 명령은 검토 증거만 생성합니다. action에는 `id`, `stageId`, classification, structured resource/evidence 정보만 포함되며 executable argv, shell string, credential, secret value는 포함되지 않습니다.

### 3. Execution readiness gate

```bash
python3 scripts/staging_infrastructure_execution_gate.py \
  --execution-manifest <review-output-dir>/staging-infrastructure-execution-manifest.json \
  --approval-result <review-output-dir>/infrastructure-approval-result.json \
  --json-output <review-output-dir>/staging-infrastructure-readiness.json \
  --markdown-output <review-output-dir>/staging-infrastructure-readiness.md \
  --strict-blocked-exit
```

gate는 canonical manifest와 approval-result의 digest·commit·plan object provenance를 재검증하고, 필요한 승인 목록만 보고합니다. 어떠한 cloud authentication이나 mutation도 하지 않습니다.

### Completion marker와 strict blocked exit

action manifest와 readiness gate가 성공적으로 두 출력 파일을 모두 publish하면 JSON output 옆에 `<json-output>.complete` completion marker를 만듭니다. marker는 두 산출물이 동일 실행에서 완성되었다는 로컬 publish 증거일 뿐, 승인·인증·apply 완료·배포 완료를 뜻하지 않습니다.

`--strict-blocked-exit`은 readiness status가 `blocked`일 때 exit code `2`를 반환합니다. 정상적인 `awaiting-cloud-mutation-approval` 또는 `awaiting-executor-design-approval`은 blocked가 아니므로 exit code `0`입니다. 입력/출력 계약 오류는 exit code `1`입니다.

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

## FUTURE REQUIREMENTS: executor trust design

apply workflow를 구현하기 전에, 추적하지 않는 actual plan/approval/manifest package의 비밀 없는 실제 증거 전달·저장 방식을 사용자가 승인해야 합니다. caller가 넣은 attestation boolean이나 임의 경로 문자열을 신뢰해서는 안 됩니다.

미래 executor는 인증 전에 다음을 모두 수행해야 합니다.

1. immutable reviewed executor commit을 정확히 고정하고, 실행한 code revision을 evidence에 기록합니다.
2. exact plan bytes, approval record, execution manifest의 SHA-256과 canonical object digest를 서로 대조합니다.
3. GitHub protected environment의 required-reviewer 승인을 approval event로 사용합니다.
4. approved non-secret evidence transport에서 받은 artifact의 provenance와 digest를 검증합니다.
5. 검증 실패, 예상 밖 resource, allowlist 밖 action, evidence 불일치 시 첫 실패에서 중단하고 증거를 보존합니다.

특히 `cloudMutationApproved=true`라는 caller-provided boolean만으로 인증이나 apply를 시작해서는 안 됩니다.

## FUTURE REQUIREMENTS: dry-run, apply, environment, WIF

다음은 현재 사용 가능한 명령이 아닙니다. 별도 사용자 승인과 구현이 완료되기 전에는 실행할 수 없습니다.

- Dry-run: exact canonical mutation subset에 대한 read-before-write evidence와 예상 diff를 산출하되, resource 변경은 하지 않아야 합니다.
- Apply: protected environment 승인, immutable reviewed executor commit, exact plan/approval/manifest digest 검증을 끝낸 뒤에만 허용됩니다.
- `staging-infrastructure-apply` environment: required reviewer 최소 1명, branch restriction은 정확히 `codex/staging-infrastructure-executor`만 허용, long-lived cloud credential 없음, WIF provider/audience/service-account identifier만 사용, least-privilege role diff가 필요합니다. 이 environment의 생성·구성 자체도 별도 사용자 승인이 필요합니다.
- WIF/IAM: provider와 service account의 identifier 및 exact least-privilege IAM diff를 사람 검토·승인합니다. key file, static secret, long-lived credential은 허용하지 않습니다.
- Rollback: 자동 delete rollback을 하지 않습니다. 미래 executor는 first-error에서 즉시 멈추고, 이미 관찰·변경된 상태와 evidence를 보존하여 사람이 후속 결정을 내리게 해야 합니다.

## 남은 명시적 승인

apply 전에는 다음 각각에 대한 별도 사용자 승인이 필요합니다.

1. implementation branch publish
2. non-secret actual evidence transport/storage
3. canonical mutation subset
4. `staging-infrastructure-apply` environment 구성
5. WIF identifier와 least-privilege IAM diff
6. `cloudMutationApproved=true` infrastructure record
7. apply dispatch

## Lifecycle 후속 상태

단계 8-12는 실제 단계 7 apply가 성공하여 actual resource identifier evidence를 남길 때까지 blocked입니다. 그 뒤에만 manifest observation update, live read-only preflight, immutable image build/push evidence, deployment packet, 별도 deployment approval, deployment executor, acceptance test, rollback evidence를 새 계획으로 다룹니다. deployment는 infrastructure lifecycle과 독립 승인입니다.

## 로컬 검증

```bash
python3 -m py_compile \
  scripts/staging_infrastructure_approval.py \
  scripts/staging_infrastructure_actions.py \
  scripts/staging_infrastructure_execution_gate.py \
  scripts/staging_infrastructure_action_io.py \
  scripts/staging_infrastructure_validation.py \
  scripts/tests/test_staging_infrastructure_approval.py \
  scripts/tests/test_staging_infrastructure_actions.py \
  scripts/tests/test_staging_infrastructure_execution_gate.py

python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

이 검증은 cloud authentication, cloud resource mutation, live query, image build/push, deployment, push, PR 변경을 수행하지 않습니다.
