# Staging apply attestation refresh plan

**작성일:** 2026-08-01  
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`  
**목표:** 만료된 apply-ready package와 승인 기록을 재사용하지 않고, 현재 보호된 Environment/WIF 상태를 새로 읽어 짧은 유효기간의 package와 run-bound 승인 기록을 준비한다.

**현재 상태:** refresh2 package SHA 승인, workflow dispatch, run-bound 승인 기록, Environment 승인까지 완료했으나 첫 precondition observation permission 부족으로 fail-closed되었다. 첫 write 전 중단했다.

**실패 action:** `api-baseline.ensure-api-01`  
**필요한 read permission:** `serviceusage.services.list`  
**현재 custom role:** `stagingApiEnableOnly`에는 `serviceusage.services.enable`만 포함

**승인된 보정:** API enable action의 fixed precondition observer가 `gcloud services list --enabled`를
사용하므로 `stagingApiEnableOnly`에 read-only `serviceusage.services.list`를 추가한다. disable, delete,
또는 broad service-usage role은 추가하지 않는다. source IAM diff와 live custom role을 함께 갱신한 뒤 새
review/apply-ready SHA를 다시 승인한다.

**새 refresh2 package SHA-256:** `55527367bfe83c5ddbc068b963bceb8ad29b8fcd776824c0e8ae1e0b66c51036`  
**새 attestation window:** `2026-08-01T01:52:01Z`–`2026-08-01T02:07:03Z`

**실패 run:** `30678348900` (attempt 1)  
**실패 시각:** `2026-08-01T01:46:49Z`  
**원인:** Environment attestation 만료 (`2026-08-01T01:45:57Z`)

## 현재 차단 원인

GitHub Environment Variables read 응답에는 apply-ready package 값(약 35KB)이 포함되어 있다. 고정
attestation parser의 단일 JSON 문자열 제한(16KB)을 넘기므로, 값이 필요 없는 Environment 이름 검증도
`strict JSON` 단계에서 fail-closed 된다.

## 안전한 보정

- 고정 GitHub API endpoint는 유지한다.
- Variables endpoint에 고정 `jq` projection을 적용해 `total_count`와 각 변수의 `name`만 반환한다.
- 변수 값, package JSON, approval JSON, 토큰 또는 credential은 attestation 입력·출력·로그에 포함하지 않는다.
- projection된 응답 바이트의 digest만 attestation response digest로 기록한다.
- pagination total, 이름 집합, 중복 검증 및 기존 fail-closed 정책은 유지한다.

## 실행 순서

1. projection argv에 대한 회귀 테스트를 추가한다.
2. 전체 관련 테스트와 정적 검사를 실행한다.
3. 현재 GitHub Environment와 GCP WIF/IAM을 read-only로 다시 attest한다.
4. 새 signed apply-ready package를 ignored `artifacts/` 경로에 생성하고 exact-byte SHA-256을 계산한다.
5. 새 SHA와 package 메타데이터를 사용자에게 제시하고 별도 승인을 받는다. (완료)
6. workflow dispatch 직전 사용자의 별도 실행 승인을 받는다.
7. 새 run ID/attempt에 결합한 승인 기록을 작성하고, attestation validity window 안에서 protected job 승인을 진행한다.
8. attestation 또는 approval expiry를 넘긴 run은 재사용하지 않고 새 package부터 재생성한다.
9. 승인 전에는 workflow dispatch, cloud mutation을 수행하지 않는다.

## 완료 경계

- 새 attestation과 package가 현재 시각 기준 유효하다.
- package는 `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 유지한다.
- 새 승인 기록은 사용자의 새 SHA 승인과 실제 새 workflow run/attempt 바인딩 전에는 apply 권한으로 사용하지 않는다.
- cloud resource, IAM, WIF, API, secret, deployment 변경은 0건이다.

## 2026-08-01 recovery run evidence

- Dispatch 승인 후 run `30679968730`, attempt `1`을 생성했다.
- Run URL: https://github.com/WBmaker2/rhwp/actions/runs/30679968730
- `publish-approved-evidence`가 `validate_apply_ready_package` 단계에서
  `operator attestation is invalid or expired`로 fail-closed 되었다.
- `apply` job은 skipped였고, WIF authentication과 executor action은 실행되지 않았다.
- 로그에서 확인된 입력은 이전 run-bound record `approvedRunId=30678904145`와
  이전 package SHA였으며, 새 run의 변수 반영이 job 시작 후에 이루어져 새 입력으로 재사용하지 않는다.
- 따라서 이 run의 cloud resource, IAM, API, secret, deployment mutation은 0건이다.
- 만료된 run-bound record와 package를 폐기하고, 외부 read-only attestation을 다시 실행했다.
- recovery apply-ready package:
  `artifacts/actual-infrastructure-review/task4-apply-ready-2026-08-01-recovery1/staging-infrastructure-apply-ready-package.json`
- recovery package exact-byte SHA-256:
  `3991e6fb677b4377a2a1a47eab3ef0fb24962442bd779547ff7989461f9a6a6a`
- recovery attestation window: `2026-08-01T02:30:20Z`–`2026-08-01T02:45:23Z`
- recovery package remains inert: `cloudMutationApproved=false`,
  `deploymentApproved=false`, `mutationCommands=[]`.

## Recovery stop boundary

The failed run must not be retried or re-run. The recovery SHA requires a fresh,
separate human approval. After that approval, dispatch and run-bound record
creation must be performed in one short sequence so the protected job reads the
fresh package and record before the attestation window expires.

## Recovery run 2

- User approved recovery package SHA `3991e6fb677b4377a2a1a47eab3ef0fb24962442bd779547ff7989461f9a6a6a`.
- New workflow run: `30680387024`, attempt `1`.
- Run URL: https://github.com/WBmaker2/rhwp/actions/runs/30680387024
- Run-bound approval record was locally validated and bound to this run before
  updating `STAGING_APPROVED_APPLY_READY_PACKAGE_JSON` and
  `STAGING_APPROVED_MUTATION_APPROVAL_JSON`.
- The protected `staging-infrastructure-apply` deployment is currently waiting
  for reviewer `WBmaker2`; `apply` has not started.
- No cloud mutation, deployment, API activation, Secret change, or IAM change
  occurred in this recovery run.

## Remote-head WIF contract stop

- Remote source commit is now `a627262f27e76de22fce5ee54315f4bda40e432c`.
- The live WIF provider remains `ACTIVE`, but its exact `attributeCondition`
  still binds `attribute.workflow_sha` to the prior commit
  `d220b456f2f8acd5a93ab175ebf2e09ba4f9f4bd`.
- The required condition changes only that immutable workflow SHA to
  `a627262f27e76de22fce5ee54315f4bda40e432c`; repository, repository IDs,
  branch ref, workflow ref, mapping, issuer, audience mode, and principal stay
  unchanged.
- Read-only WIF attestation correctly rejected the mismatch. No provider,
  IAM, API, Secret, resource, or deployment mutation was attempted.
- The next external action requires explicit approval of this exact WIF
  `attributeCondition` update. Only after that update is read-back verified can
  a fresh attestation and apply-ready SHA be generated.

## WIF correction and fresh package

- User approved the exact WIF condition update.
- Provider read-back is `ACTIVE` and `attributeCondition` now matches the
  remote workflow SHA `a627262f27e76de22fce5ee54315f4bda40e432c`; all other
  identity, mapping, issuer, branch, and principal fields remain unchanged.
- Fresh review package SHA-256:
  `bcb2a77590fc597dfa335ee26b3e19c51b8ade678d0436e2d4f4d4ad97e29f12`
- Fresh apply-ready package:
  `artifacts/actual-infrastructure-review/task4-apply-ready-2026-08-01-remote-fix/staging-infrastructure-apply-ready-package.json`
- Fresh apply-ready exact-byte SHA-256:
  `118d9548db513914f71ba43a273cbc3dddec94b36d3917b447591f1bd2f31690`
- Fresh attestation window: `2026-08-01T02:46:34Z`–`2026-08-01T03:01:37Z`.
- Package remains inert: `cloudMutationApproved=false`,
  `deploymentApproved=false`, `mutationCommands=[]`.
- A pending approval record was created under the same ignored directory; no
  workflow dispatch or Environment variable update has been made for this
  package.

## Incorrect main-branch dispatch

- The browser-created run `30681072981` used `main` at commit
  `881ad7414da2a233ed82e44a06c9b1db936557ec`, not the approved PR branch.
- Its `publish-approved-evidence` job failed immediately and `apply` was
  skipped; it is not evidence for the PR apply flow and must not be retried.
- No pending deployment, authentication, executor action, or cloud mutation
  occurred in that run.

## Feasibility assessment and stop decision

The current implementation is not operationally completable as designed. The
reason is a circular run-binding dependency:

1. `STAGING_APPROVED_APPLY_READY_PACKAGE_JSON` and
   `STAGING_APPROVED_MUTATION_APPROVAL_JSON` are Environment variables whose
   values are snapshotted when the protected job starts.
2. The approval record must contain the exact `approvedRunId` and attempt.
3. That run ID exists only after workflow dispatch.
4. GitHub may start the protected job as soon as the deployment is approved, so
   updating the Environment variables after dispatch is a race and does not
   affect the already-started job.
5. The 15-minute attestation TTL makes the race unavoidable in a manual UI
   flow. Runs `30679968730` and `30681110172` demonstrated stale/expired input
   consumption; both stopped before `apply`.

This is not a cloud permission or operator error. The fail-closed behavior is
working, but the current workflow contract cannot reliably reach the mutation
stage. Do not repeat dispatches or approve another SHA under this design.

The program can become implementable only after an architecture change, for
example: an unprotected non-mutating prepare job creates the run-bound record
and same-run artifact, followed by a protected apply job that consumes that
artifact; or an equivalent atomic run-scoped input mechanism. Environment
variables must not be the transport for run-bound JSON.

## Prepare/apply architecture redesign implementation plan

The recovery stop above is now converted into an implementation change. The
workflow will no longer use protected Environment variables for either the
apply-ready package or the run-bound approval record.

### Contract

1. A repository-level, non-secret base64 variable carries the exact approved
   apply-ready package bytes. A separate repository-level base64 variable carries
   a human-approved declaration that deliberately omits `approvedRunId` and
   `approvedRunAttempt`. Neither value is a protected Environment variable.
2. A non-protected `prepare` job runs first with `contents: read`, `actions: read`,
   and no `id-token` permission. After GitHub has assigned `github.run_id` and
   `github.run_attempt`, the job decodes the bytes, validates their exact-byte
   digest and inert flags, binds the declaration to the current run, and emits
   `staging-infrastructure-approved-evidence` from that same run.
3. The protected `apply` job has `needs: prepare`, enters
   `staging-infrastructure-apply`, and is the only job with `id-token: write`.
   It downloads only the same-run artifact, validates its run binding and
   immutable provenance, then authenticates and executes the approved actions.
   It never reads package or approval JSON from Environment variables.
4. The declaration is a review input, not execution authority. The prepare
   binder is the only code allowed to add the current run identity; the executor
   still requires the complete v3 approval record and exact package bytes.
5. Migration of the live Environment removes the two legacy package/approval
   variables after this source contract is reviewed. The existing immutable
   identity and cloud configuration variables remain Environment-scoped.

### Implementation sequence

- Add declaration validation and run-binding helpers to
  `scripts/staging_infrastructure_apply_approval.py`.
- Add a small prepare/binder CLI with strict base64 decoding, exact-byte
  preservation, bounded input sizes, and atomic JSON outputs.
- Update the review-policy transport and protected Environment specification to
  describe the two-job contract and exclude run-bound JSON variables.
- Rewrite `staging-infrastructure-apply.yml` as `prepare` then protected
  `apply`; keep cloud authentication and mutation after the protected gate.
- Update unit tests for declaration binding, same-run rejection, exact-byte
  mismatch, no-credential prepare permissions, and the new workflow contract.
- Run the focused apply tests and the full Python test suite plus static config
  validation. Do not push or dispatch until a separate user approval covers the
  changed workflow/WIF binding and the live Environment migration.

### Safety and stop conditions

- No cloud API, IAM, WIF, secret, resource, build, push, or deployment action is
  part of this local implementation.
- A missing repository variable, invalid base64, stale attestation, mismatched
  package SHA, wrong run ID/attempt, or failed pre-auth validation stops the
  workflow before authentication.
- Existing ignored local artifacts and the unrelated `.chatgpt2codex/` path are
  not added to Git.

## User delivery priority

The user explicitly requested that the workflow stop repeating known-failing
attempts and prioritize a fast, verifiable MVP path. From this point forward,
known stale-attestation/Environment-variable dispatches are not retried. Work
should favor small local implementation steps, focused tests, and a clear
browser-verifiable deployment handoff. Any external mutation or deployment gate
remains explicit and is reported with a direct link when it is actually ready.
