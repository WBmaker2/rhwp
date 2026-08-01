# rhwp Staging Infrastructure Bootstrap Runbook

## Lifecycle 개요와 인계 문서

| 단계 | 상태 | 인계/근거 |
| ---: | --- | --- |
| 1-3 | 선행 절차 | [inputs](staging-bootstrap-inputs.md) → [readiness](staging-bootstrap-readiness.md) → [operator](staging-bootstrap-operator.md) |
| 4 | 선행 검토 | [bootstrap packet review](staging-bootstrap-packet-review.md) 및 bootstrap approval record |
| 5 | plan 생성 | `scripts/staging_infrastructure_plan.py`가 bootstrap manifest, packet, approval record에서 plan을 만듭니다. |
| 6 | 현재 범위 | approval/action/readiness/review package와 guarded apply executor·operator attestation CLI가 계약을 확인합니다. |
| 7 | 차단 | operator의 read-only Environment/WIF attestation, immutable signing-key registry onboarding, exact-byte v3 approval, protected job 승인과 별도 cloud mutation 승인이 필요합니다. |
| 8-9 | 차단 | actual resource identifier 관찰 및 live read-only preflight는 7의 evidence 뒤에만 가능합니다. |
| 10-12 | 차단 | deployment packet, 별도 deployment approval, deployment는 독립 절차입니다. |

선행 runbook의 non-secret 산출물을 operator-local 경로로 복사한 뒤 아래 명령의 입력으로 사용합니다. bootstrap approval record와 `staging_infrastructure_plan.py`가 만든 plan이 없으면 이 runbook의 명령을 시작하지 않습니다.

## 상태와 안전 경계

이 runbook은 staging 전용 infrastructure 검토·attestation·guarded apply 계약을 설명합니다. 이 저장소의
review workflow와 로컬 검증은 cloud authentication, resource 변경, GitHub Environment 변경, workflow dispatch,
배포를 수행하지 않습니다. 별도 operator CLI만 인증된 운영자가 의도적으로 실행할 때 fixed read-only
`gh api`/`gcloud` 조회를 수행하며, 그 원문 응답·토큰·credential은 출력 또는 evidence에 기록하지 않습니다.

- tracked repository 상태: `no-tracked-actual-approval-record`
- 현재 지원: infrastructure plan 승인 검증, 구조화 action manifest/readiness/review package, fixed-query
  Environment/WIF operator attestation, immutable-key signed apply-ready v3/v3 approval 검증, guarded dry-run/apply executor
- 현재 미지원: Environment/WIF/IAM 생성·구성, cloud mutation의 자동 승인, image build/push, deployment
- 공통 출력 경계: `mutationCommands=[]`, deployment 권한은 항상 `false`, 실행 가능한 shell/argv는 생성하지 않습니다.

실제 운영 값, 승인 artifact, credential, token, private key, service-account key, Firebase API key 값, internal flush 원문은 추적 문서나 예시에 기록하지 않습니다.

## 세 가지 별도 승인

| 승인 | 검토 대상 | 현재 구현의 결과 | 다른 승인과의 관계 |
| --- | --- | --- | --- |
| Plan review approval | exact infrastructure plan bytes, commit, project/billing 바인딩, stage 순서, 예산, rollback 검토 | `cloudMutationApproved=false`이면 `awaiting-cloud-mutation-approval` | apply 권한이 아닙니다. |
| Cloud mutation approval | immutable-key signed operator attestation이 결합된 apply-ready v3 exact bytes와 동일 run에 바인딩한 `cloudMutationApproved=true` v3 record | executor는 protected job과 모든 pre-auth 검증 뒤에만 실행합니다. | plan review·deployment approval을 대체하지 않습니다. |
| Deployment approval | deployment packet, immutable image digest, live preflight, IAM diff, rollback/acceptance evidence | 현재 범위 밖이며 항상 별도입니다. | infrastructure mutation approval을 대체하지 않습니다. |

operator-local reviewed plan record가 존재하고 `cloudMutationApproved=false`라면 `awaiting-cloud-mutation-approval`으로 평가됩니다. 이는 apply 입력이 아니며 `--require-cloud-mutation` 검증도 통과하지 못합니다. tracked repository에는 actual approval record가 없습니다.

## 현재 구현된 검토 명령

이 구현은 operational metadata를 ignored local `artifacts/actual-infrastructure-review/`에만 보관하도록 선택합니다. `docs/approvals/records/`는 repository archival 호환 경로이지만, 그곳에 기록하려면 별도 사용자 승인과 redaction policy가 필요하며 여기서는 수행하지 않습니다.

### 1. Infrastructure approval 검증

```bash
python3 -m scripts.staging_infrastructure_approval \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --approval artifacts/actual-infrastructure-review/staging-infrastructure-approval-record.json \
  --json-output artifacts/actual-infrastructure-review/infrastructure-approval-result.json \
  --markdown-output artifacts/actual-infrastructure-review/infrastructure-approval-result.md
```

이 명령은 plan의 실제 바이트 SHA-256, canonical plan object digest, commit, project/billing, ordered stage IDs, budget, rollback acknowledgement를 fail-closed로 결합합니다. `cloudMutationApproved=false` record는 정상 검토 결과로 처리할 수 있지만 status는 `awaiting-cloud-mutation-approval`입니다. `--require-cloud-mutation`은 향후 별도 승인 record 검증용이며, 현재 record에는 사용하지 않습니다.

### 2. Action manifest 생성

```bash
python3 -m scripts.staging_infrastructure_actions \
  --plan artifacts/actual-infrastructure-review/staging-infrastructure-plan.json \
  --approval artifacts/actual-infrastructure-review/staging-infrastructure-approval-record.json \
  --json-output artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.json \
  --markdown-output artifacts/actual-infrastructure-review/staging-infrastructure-execution-manifest.md
```

이 명령은 검토 증거만 생성합니다. action에는 `id`, `stageId`, classification, structured resource/evidence 정보만 포함되며 executable argv, shell string, credential, secret value는 포함되지 않습니다.

### 3. Execution readiness gate

```bash
python3 -m scripts.staging_infrastructure_execution_gate \
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
python3 -m scripts.staging_infrastructure_apply_review \
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

### 5. Operator attestation과 apply-ready promotion

다음 명령은 authenticated operator만 operator-local ignored 경로에서 실행합니다. `--environment-attestation`
또는 `--wif-attestation` 같은 관찰 JSON 입력은 없습니다. promotion CLI가 고정 repository/environment의
read-only `gh api` endpoints와 고정 `gcloud` argv를 직접 호출하고, provider mapping·CEL condition·exact
`roles/iam.workloadIdentityUser` service-account binding을 검증합니다.

```bash
python3 -m scripts.staging_infrastructure_apply_ready \
  --review-package artifacts/actual-infrastructure-review/staging-infrastructure-apply-review-package.json \
  --project-id <STAGING_PROJECT_ID> \
  --provider-resource-name <WIF_PROVIDER_RESOURCE_NAME> \
  --service-account <DEPLOYER_SERVICE_ACCOUNT_EMAIL> \
  --operator-signing-key-id <PINNED_OPERATOR_KEY_ID> \
  --operator-signing-private-key <OPERATOR_LOCAL_ED25519_PRIVATE_KEY_PATH> \
  --output artifacts/actual-infrastructure-review/staging-infrastructure-apply-ready-package.json
```

각 receipt에는 query contract version, project/provider/service-account 및 immutable GitHub identifiers,
exact expected mapping/condition/principal, GitHub OIDC issuer/default audience mode, raw response SHA-256,
observedAt/expiresAt, verified result만 남습니다. canonical payload는 immutable tracked-code Ed25519 registry의
public key로 확인되는 signature envelope에 넣습니다. response body, reviewer identity, variable value, stderr,
token, credential 또는 private signing key는 남기지 않습니다. API disabled, 403, malformed/unknown response,
pagination 불완전, registry key 부재/서명 불일치는 모두 output 없이 fail-closed입니다. 단일 운영자 예외에서는
GitHub official GET Environment response에 `can_admins_bypass` 필드가 정확히 없을 때만
`unavailable-in-official-rest`를 관찰값으로 기록합니다. 필드가 제공되면 값이 정확히 `false`여야 하며,
`true`, `null`, 숫자 또는 문자열은 모두 거부합니다. 이는 사람이 `false`라고 진술한 것으로 기록하지 않으며
GitHub UI에서 administrator bypass를 비활성화해야 한다는 운영 요구를 제거하지 않습니다.

Google Cloud의 provider `disabled`는 optional boolean이며 `gcloud --format=json`이 기본값 `false`를 생략할
수 있습니다. WIF attestor는 provider `state=ACTIVE`와 함께 이 필드가 없거나 정확히 `false`인 경우만 enabled로
판정합니다. `true`, `null`, 숫자 또는 문자열은 모두 거부합니다.

`TRUSTED_OPERATOR_KEY_REGISTRY`에는 별도 승인된 `rhwp-staging-operator-2026-07-31` Ed25519 public key와
exact PEM SHA-256만 등록합니다. private key는 ignored operator-local 경로의 권한 `0600` 파일로만 보관하며
tracked source, Environment variable, log 또는 artifact에 넣지 않습니다. protected Environment variable의
public key를 trust root로 사용하지 않습니다.

operator가 signed v3 package의 exact raw SHA-256, 두 receipt envelope digest 및 expiry를 확인한 뒤에만 v3 human approval을
작성합니다. approval 시각과 protected apply run 시각은 두 receipt의 **최대 60분** validity window 안에 있어야 합니다.
60분은 source-level 고정 상한이며 workflow dispatch 입력이나 Repository/Environment 변수로 조정할 수 없습니다. window를
넘긴 package, attestation 또는 approval은 재사용하지 않고 새 fixed-query attestation부터 재생성합니다.

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
| eligible-mutation | `api-baseline`, `service-accounts`, `artifact-registry`, `secret-metadata` | guarded executor가 exact allowlist·operator attestation·v3 approval 뒤에만 idempotent create/enable을 수행할 수 있습니다. |
| irreversible-manual-decision | `firebase-foundation`, `budget-guardrails` | 현재 observation only입니다. 위치·budget/channel의 실제 생성은 별도 콘솔/API 의사결정과 승인이 필요합니다. |
| deferred-resource-specific | `iam-bindings` | 모든 referenced resource 존재 및 exact before/after IAM diff 승인 전까지 deferred입니다. |
| blocked-deferred | `cloud-run-prerequisites`, `cloud-tasks-prerequisites` | immutable image digest, worker URL, deployment approval 및 queue/IAM diff 전까지 blocked입니다. |

`project-billing`은 project 생성·삭제·billing relink를 수행하지 않습니다. eligible-mutation stage도 API 자동 disable, service-account key 생성, secret version의 추가·읽기·출력, repository 삭제를 허용하지 않습니다.

## 구현된 review-package trust design과 executor

현재 review-package builder는 caller가 넣은 attestation boolean이나 parsed object만 신뢰하지 않고 exact
plan bytes와 canonical execution manifest를 재구성합니다. review package는 검토 전용이며, 실제 apply에는
tracked review evidence를 실행하지 않고 ignored live attestation을 결합한 apply-ready promotion과 별도 human
approval을 사용합니다.

apply executor와 workflow는 인증 전에 다음을 모두 수행합니다.

1. caller-declared executor commit을 provenance로 신뢰하지 않고, 승인 브랜치 포함성 및 commit object/tree와
   `.github/workflows/staging-infrastructure-apply.yml`의 승인된 내용을 독립 검증한 뒤 실행한 revision을 evidence에 기록합니다.
2. exact plan bytes, approval record, execution manifest의 SHA-256과 canonical object digest를 서로 대조합니다.
3. GitHub protected environment의 required-reviewer 승인을 approval event로 사용합니다.
4. approved non-secret evidence transport에서 받은 artifact의 provenance와 digest를 검증합니다.
5. 검증 실패, 예상 밖 resource, allowlist 밖 action, evidence 불일치 시 첫 실패에서 중단하고 증거를 보존합니다.

특히 `cloudMutationApproved=true`라는 caller-provided boolean만으로 인증이나 apply를 시작해서는 안 됩니다.

## Approved apply executor와 protected workflow

`scripts/staging_infrastructure_apply_executor.py`는 review package를 직접 실행하지 않습니다. actual CLI는
관찰 JSON을 받지 않고, `scripts/staging_infrastructure_apply_ready.py`가 fixed-query operator receipt로 만든
`rhwp.staging-infrastructure-apply-ready/v3`의 exact bytes를 사람이 승인한 v3 record만 받습니다. tracked/synthetic
review package와 caller-supplied attestation dict는 apply-ready가 아니므로 fail-closed입니다. 기본값은 dry-run이며,
실제 apply는 `--apply`와 embedded attestation의 digest·expiry·runtime context 검증을 요구합니다. package 안의
command, argv, shell, credential, token, secret value는 지원하지 않습니다.

`.github/workflows/staging-infrastructure-apply.yml`은 `workflow_dispatch` 전용입니다. repository-level base64
package/declaration을 비보호 `prepare` job이 읽고, dispatch로 생성된 run ID/attempt를 declaration에 결합해
v3 approval과 exact apply-ready package를 같은 run artifact로 게시합니다. `prepare`는 cloud auth와 `id-token` 없이
실행됩니다. protected `apply` job은 `needs: prepare`와 Environment 승인을 모두 통과한 뒤 그 artifact만 download하고
exact approval digest, source commit에서 checked-out executor commit까지의 Git object/ancestor/approved-branch
관계, repository/owner immutable ID, workflow path/content SHA와 OIDC `workflow_ref`/`workflow_sha` claim을 검증한
뒤에만 WIF 인증을 요청합니다. 실제 ID/SHA와 cloud 설정만 protected Environment 변수에 두며, package/declaration은
Environment 변수나 dispatch input에 두지 않습니다.

성공/실패와 무관하게 apply evidence artifact에는 sanitized plan/post evidence만 올립니다. prepare가 만든
`staging-infrastructure-approved-evidence`에는 검증된 exact package와 run-bound approval이 포함되지만 credential은
포함하지 않습니다. package/declaration 입력값과 provenance temporary file은 별도 artifact로 올리지 않습니다. API enable, service-account create, Artifact
Registry create, secret metadata create 외 stage와 secret version/value, service-account key, broad IAM,
delete/disable, build/push/deploy는 executor allowlist 밖입니다.

## Dispatch 전 필수 운영 게이트

다음은 구현되어 있으나, review→apply-ready promotion·artifact transport·protected Environment 값·human approval이 모두
재생성·검토되기 전에는 dispatch할 수 없는 필수 게이트입니다.

- Dry-run: exact canonical mutation subset에 대한 plan/post evidence를 산출하되, resource 변경은 하지 않아야 합니다.
- Apply: protected environment 승인, caller-declared commit의 독립 membership/tree/workflow 검증, exact
  plan/approval/manifest digest 검증을 끝낸 뒤에만 허용됩니다.
- `staging-infrastructure-apply` environment: required reviewer `WBmaker2` 최소 1명, 단일 운영자 예외로
  prevent self-review 비활성화,
  GitHub UI에서는 `canAdminsBypass=false`를 요구합니다. operator는 official REST read contract가 필드를
  제공하면 정확히 `false`만 허용하고, 필드를 제공하지 않으면 승인된 단일 운영자 예외를 명시적으로
  `unavailable-in-official-rest`로 기록합니다. 사람 acknowledgement를 관찰된 `false`로 바꾸지 않습니다.
  deployment branch policy에서 protected branches는 `false`, custom branch policies는 `true`로 두고
  branch policy `[{'name':'feat/firebase-collaboration-mvp-v1','type':'branch'}]`, tag policy `[]`만 허용합니다.
  long-lived cloud credential
  없음, WIF provider/audience/service-account identifier만 사용, least-privilege role diff가 필요합니다.
  이 environment의 생성·구성 자체도 별도 사용자 승인이 필요합니다.
  이 예외는 승인 가능한 collaborator가 `WBmaker2` 한 명뿐인 현재 저장소에만 적용합니다. Required reviewer를
  제거하지 않으며 administrator bypass 금지, exact-byte approval, run binding과 dispatch 별도 승인은 유지합니다.
- WIF/IAM: subject는 `.github/workflows/staging-infrastructure-apply.yml`에만
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
- Rollback: 자동 delete rollback을 하지 않습니다. executor는 first-error에서 즉시 멈추고, 이미 관찰·변경된 상태와 evidence를 보존하여 사람이 후속 결정을 내리게 합니다.

현재 review workflow의 artifact `staging-infrastructure-apply-review`는 합성 계약 증거입니다. actual apply는
cross-run 입력을 사용하지 않습니다. 비보호 `prepare` job이 GitHub가 부여한 현재 run ID/attempt로 package와
승인 declaration을 검증·바인딩한 뒤 같은 run의 artifact를 게시하고, protected `apply` job은 그 artifact만
소비합니다. package raw digest, actual GitHub repository/ID/owner/ref/workflow claims, artifact source commit,
checked-out source/executor commit object·tree·ancestor·approved-branch 관계, approval run ID/attempt/nonce/expiry가
모두 맞아야 하며, 검증이 끝나기 전에는 OIDC token을 요청하지 않습니다.

### Same-run evidence publication 순서

1. immutable code registry에 별도 승인된 Ed25519 public key가 onboarding된 뒤에만 인증된 operator가 fixed `gh api` GET 및 fixed `gcloud` read-only argv로 Environment/WIF/IAM을 재조회합니다. 조회 원문 대신 response digest와 sanitized provenance를 canonical signed receipt에 넣어 최대 60분의 ignored apply-ready v3 package를 생성하고, 그 raw SHA-256과 canonical subset을 검토합니다.
2. 사람 승인은 run ID가 없는 declaration으로 기록합니다. exact package bytes와 declaration은 repository-level base64 변수(`STAGING_APPLY_READY_PACKAGE_B64`, `STAGING_MUTATION_APPROVAL_DECLARATION_B64`)에만 반영하며, protected Environment 변수에는 넣지 않습니다.
3. actual apply workflow를 dispatch합니다. 비보호 `prepare` job이 먼저 실행되고, `github.run_id`/`github.run_attempt`를 declaration에 추가해 full v3 approval record를 만든 뒤 package raw bytes와 record를 `staging-infrastructure-approved-evidence` 같은-run artifact로 게시합니다. 이 job은 `contents: read`, `actions: read`, `id-token: none`이며 cloud auth·mutation을 수행하지 않습니다.
4. protected `apply` job은 `needs: prepare`와 `environment: staging-infrastructure-apply`를 모두 요구합니다. 같은 run artifact만 다운로드하고 exact attestation digest·최대 60분 expiry·repository/owner/ref/workflow runtime context, artifact provenance와 Git object/tree를 검증합니다. 어느 하나라도 불일치·만료·unknown이면 WIF auth와 write 단계 전에 중단합니다.
5. `apply` job의 보호 승인 이후에만 `id-token: write`, WIF auth, gcloud setup, executor mutation을 순서대로 시작합니다.

Protected Environment 변수는 `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`,
`STAGING_PROJECT_ID`, `STAGING_APPROVED_REPOSITORY`, `STAGING_APPROVED_REPOSITORY_ID`,
`STAGING_APPROVED_REPOSITORY_OWNER_ID`, `STAGING_APPROVED_REF`, `STAGING_APPROVED_WORKFLOW_REF`,
`STAGING_APPROVED_WORKFLOW_SHA`, `STAGING_APPROVED_WORKFLOW_CONTENT_SHA256`,
`STAGING_APPROVED_EXECUTOR_TREE_SHA`만 사용합니다. package/approval JSON은 Environment 변수가 아니며,
repository-level base64 변수 `STAGING_APPLY_READY_PACKAGE_B64`,
`STAGING_MUTATION_APPROVAL_DECLARATION_B64`에서 prepare job으로만 전달됩니다.

GitHub Environment 변수 설정과 job 승인은 실제 GitHub 변경이므로 별도 사용자 승인 없이는 수행하지 않습니다.

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
  scripts/staging_infrastructure_operator_attestation.py \
  scripts/staging_infrastructure_environment_attestation.py \
  scripts/staging_infrastructure_wif_attestation.py \
  scripts/staging_infrastructure_apply_ready.py \
  scripts/staging_infrastructure_apply_approval.py \
  scripts/staging_infrastructure_apply_prepare.py \
  scripts/staging_infrastructure_apply_provenance.py \
  scripts/staging_infrastructure_apply_executor.py \
  scripts/staging_infrastructure_synthetic_fixture.py \
  scripts/staging_infrastructure_action_io.py \
  scripts/staging_infrastructure_validation.py \
  scripts/tests/test_staging_infrastructure_approval.py \
  scripts/tests/test_staging_infrastructure_actions.py \
  scripts/tests/test_staging_infrastructure_execution_gate.py \
  scripts/tests/test_staging_infrastructure_apply_review.py \
  scripts/tests/test_staging_infrastructure_apply_review_policy.py \
  scripts/tests/test_staging_infrastructure_operator_attestations.py \
  scripts/tests/test_staging_infrastructure_apply_executor.py

python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

이 검증은 cloud authentication, cloud resource mutation, live query, image build/push, deployment, push, PR 변경을 수행하지 않습니다.
