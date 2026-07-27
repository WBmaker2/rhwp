# Staging Infrastructure Execution Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the fail-closed review package and readiness gate needed before a separately designed and approved staging cloud-mutation executor can exist.

**Architecture:** A strict infrastructure-approval validator binds the exact plan bytes, commit, project, billing account, budget, stage IDs, and rollback acknowledgement. A separate execution-manifest generator classifies the eleven known plan stages into observation-only, eligible mutation, irreversible/manual-decision, and deferred actions using a canonical table. A readiness gate emits only review evidence and the exact missing approvals; it never imports subprocess, authenticates to cloud services, or performs a mutation.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, existing staging plan and preflight modules.

---

## Scope and stop boundaries

- Work on `codex/staging-infrastructure-executor` in the isolated worktree.
- Keep PR #1 Draft, open, and unmerged.
- Do not use actual operating-value files in tests or tracked documentation.
- Do not execute `gcloud`, Firebase CLI, Cloud Billing, IAM, API enablement, build, push, deploy, or any other cloud mutation while implementing or testing.
- Never persist access tokens, ID tokens, Authorization headers, passwords, private keys, service-account keys, Firebase API key values, or internal flush token values.
- The current actual infrastructure approval has `cloudMutationApproved=false`; it is sufficient for plan review but not apply.
- No workflow dispatch, GitHub Environment mutation, secret/variable registration, push, PR mutation, or merge is part of implementation without separate user approval.
- No module in this implementation unit may import `subprocess` or serialize executable command/argv fields.
- Deployment remains independently blocked. This plan does not build images, push images, create deployment packets, or deploy Cloud Run services.

## File structure

- Create `scripts/staging_infrastructure_approval.py`: strict infrastructure-plan approval validation and review-result rendering.
- Create `scripts/tests/test_staging_infrastructure_approval.py`: TDD coverage for digest binding, exact schema, stage equality, budget, rollback, and cloud-mutation boundary.
- Create `scripts/staging_infrastructure_actions.py`: pure conversion from an approved plan to ordered, structured allowlisted actions.
- Create `scripts/tests/test_staging_infrastructure_actions.py`: TDD coverage for stage mapping, dependencies, production separation, redaction, and deterministic output.
- Create `scripts/staging_infrastructure_execution_gate.py`: non-mutating readiness evaluator for the reviewed execution manifest.
- Create `scripts/tests/test_staging_infrastructure_execution_gate.py`: TDD coverage proving no subprocess, fail-closed approvals, and exact next-approval reporting.
- Create `scripts/staging_infrastructure_action_io.py`: shared atomic paired-output publish and completion-marker handling.
- Create `scripts/staging_infrastructure_validation.py`: shared bounded raw-byte parser and single-file-descriptor regular-file reader (`MAX_JSON_BYTES + 1` read after `fstat`), strict JSON-domain validation, and canonical JSON helpers for untrusted evidence.
- Modify `scripts/staging_infrastructure_plan.py`: preserve the canonical safe `security.secretValuesIncluded=false` declaration after sensitive-data redaction so downstream validation has a non-secret, deterministic boundary marker.
- Modify `.gitignore`: ignore `/artifacts/` so actual operator-local plan/approval/execution metadata cannot be added to the tracked repository by this workflow.
- Modify `docs/runbooks/staging-infrastructure-bootstrap.md`: document validation, dry-run, apply approval, WIF, evidence, and rollback boundaries.
- Create `docs/superpowers/reports/2026-07-27-staging-infrastructure-execution-gates-result.md`: implementation and verification result.

## Artifact contracts

### Infrastructure approval record

The existing schema remains:

```json
{
  "schemaVersion": "rhwp.staging-infrastructure-approval/v1",
  "decision": "approved",
  "approvedAt": "UTC timestamp",
  "approvedBy": ["actual approver"],
  "commitSha": "40 lowercase hex",
  "planSha256": "64 lowercase hex",
  "projectId": "staging-only project",
  "billingAccount": "XXXXXX-XXXXXX-XXXXXX",
  "approvedStageIds": ["all plan stage IDs in exact order"],
  "maximumMonthlyBudgetKrw": 5000,
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "rollbackReviewed": true
}
```

The validator accepts `cloudMutationApproved=false` as a reviewed plan and reports `awaiting-cloud-mutation-approval`. Apply mode requires a separately reviewed record with the same evidence and `cloudMutationApproved=true`. `deploymentApproved` must always remain `false`.

### Execution manifest

```json
{
  "schemaVersion": "rhwp.staging-infrastructure-execution/v1",
  "status": "awaiting-cloud-mutation-approval",
  "projectId": "staging-only project",
  "billingAccount": "XXXXXX-XXXXXX-XXXXXX",
  "sourceEvidence": {
    "commitSha": "40 lowercase hex",
    "planSha256": "64 lowercase hex"
  },
  "actions": [],
  "security": {
    "secretValuesIncluded": false,
    "productionResourcesAllowed": false,
    "deploymentAuthorized": false
  }
}
```

Each action has only `id`, `stageId`, `classification`, `kind`, `resource`, `dependencies`, `desiredState`, `rollbackBoundary`, and `evidenceQuery`. No shell string, argv, credential, secret value, or mutable free-form command is serialized.
The empty `actions` array above is illustrative only; a valid generated manifest must contain the canonical actions derived from all eleven approved stages.

## Canonical stage-to-action contract

The implementation must use this exact table. It must not infer extra mutations from free-form plan text.

| Stage | Classification | Allowed structured action kinds | Required plan fields | Read-before-write evidence | Apply disposition |
|---|---|---|---|---|---|
| `project-billing` | observation-only | `verify-project`, `verify-billing-link`, `verify-production-separation` | project ID, billing account, region, forbidden IDs | project identity and billing-link descriptions | Never mutate. The actual project and billing link already exist; project creation/deletion and billing relink require a different approval unit. |
| `api-baseline` | eligible-mutation | one `ensure-api-enabled` per exact API string in the approved allowlist | ordered API list | enabled-service list for the approved project | May be implemented later as idempotent enable-only. Never disable APIs automatically. |
| `firebase-foundation` | irreversible-manual-decision | `verify-firebase-project`, `verify-firestore-location`, `verify-storage-bucket`, `verify-hosting-site` | project, locations, planned bucket/site | Firebase project and resource descriptions | Observation only in this unit. Firestore/Storage location creation is irreversible and needs a dedicated console/API decision. |
| `service-accounts` | eligible-mutation | one `ensure-service-account` for each of the four exact workload identities | four service-account emails | service-account descriptions | May be implemented later as create-if-missing; never create keys. |
| `artifact-registry` | eligible-mutation | `ensure-artifact-repository` | repository and location | repository description | May be implemented later as create-if-missing; never delete. |
| `secret-metadata` | eligible-mutation | `ensure-secret-container` | secret name and `valueIncluded=false` | secret metadata description | May create an empty secret container later; never add/read/print a secret version. |
| `iam-bindings` | deferred-resource-specific | one `review-iam-binding` per exact principal/role/resource tuple | exact manifest bindings | project and resource IAM policies | No mutation until every referenced bucket, queue, secret, service account, and Cloud Run service exists and an exact before/after diff is approved. |
| `budget-guardrails` | irreversible-manual-decision | `verify-budget`, `verify-notification-channel` | KRW amount, thresholds, recipients | billing-budget and notification-channel descriptions | Observation only until the concrete billing budget resource and channel identifiers are separately approved. |
| `cloud-run-prerequisites` | blocked-deferred | `record-cloud-run-prerequisite` | service names/runtime plus `state=blocked-pending-image-digest` | none | Never mutate before immutable image digests and deployment approval. |
| `cloud-tasks-prerequisites` | blocked-deferred | `record-cloud-tasks-prerequisite` | queue settings plus `state=blocked-pending-worker-url` | none | Never mutate before approved worker URL and queue/IAM diff. |
| `post-bootstrap-evidence` | observation-only | one `collect-resource-evidence` per required value path | path, resolution phase, reason | read-only resource descriptions | Read-only only; discrepancies stop the lifecycle. |

Unknown stages, missing required fields, a stage/action classification mismatch, or an action that contradicts the disposition must fail closed.

## Task 1: Infrastructure approval validator

**Files:**
- Create: `scripts/tests/test_staging_infrastructure_approval.py`
- Create: `scripts/staging_infrastructure_approval.py`

**Required API:**

```python
def validate_infrastructure_approval(
    plan: dict[str, Any],
    plan_bytes: bytes,
    approval: dict[str, Any],
    *,
    require_cloud_mutation: bool,
) -> dict[str, Any]:
    ...
```

- [x] **Step 1: Write failing schema and digest tests.**
  Require exact approval keys, approved decision, UTC timestamp, non-empty unique approvers, 40-character commit SHA, 64-character exact-byte plan digest, staging-only project ID, billing format, positive integer KRW budget, and no sensitive key paths.
- [x] **Step 2: Run the focused module and verify RED.**
  Run `python3 -m unittest scripts.tests.test_staging_infrastructure_approval -v`.
  Expected: import failure because the production module does not exist.
- [x] **Step 3: Implement strict loading and validation.**
  Return a sanitized result with `status=awaiting-cloud-mutation-approval` when the reviewed record is valid but mutation is false. When `require_cloud_mutation=True`, reject unless it is exactly `true`.
- [x] **Step 4: Add failing evidence-binding tests.**
  Require approval commit/project/billing/stage IDs to equal the plan, require every stage exactly once and in order, require `rollbackReviewed=true`, reject `deploymentApproved=true`, and reject production-like IDs.
- [x] **Step 5: Implement evidence binding and sanitized Markdown rendering.**
  Error messages may include field paths but never rejected values.
- [x] **Step 6: Verify GREEN and commit.**
  Run the focused tests, then `python3 -m py_compile` for both files.
  Commit message: `feat: validate staging infrastructure approvals`.

## Task 2: Deterministic infrastructure action manifest

**Files:**
- Create: `scripts/tests/test_staging_infrastructure_actions.py`
- Create: `scripts/staging_infrastructure_actions.py`

**Required API:**

```python
def build_execution_manifest(
    plan: dict[str, Any],
    approval_result: dict[str, Any],
    *,
    plan_bytes: bytes,
) -> dict[str, Any]:
    ...
```

- [x] **Step 1: Write failing ordered-action tests.**
  Cover all eleven exact stage IDs:
  `project-billing`, `api-baseline`, `firebase-foundation`, `service-accounts`,
  `artifact-registry`, `secret-metadata`, `iam-bindings`, `budget-guardrails`,
  `cloud-run-prerequisites`, `cloud-tasks-prerequisites`,
  `post-bootstrap-evidence`.
- [x] **Step 2: Verify RED.**
  Run `python3 -m unittest scripts.tests.test_staging_infrastructure_actions -v`.
- [x] **Step 3: Implement pure stage adapters.**
  Convert only structured plan fields into deterministic actions. Reject unknown stages, duplicate action IDs, unknown resource kinds, production-like resources, secret values, inline command strings, and dependencies that reference later/missing actions.
- [x] **Step 4: Add failing security tests.**
  Assert serialized output has no `command`, `argv`, token, credential, private-key, password, secret-value, Firebase API key value, or internal flush token value.
- [x] **Step 5: Implement JSON/Markdown rendering and atomic CLI output.**
  CLI inputs: `--plan`, `--approval`, `--json-output`, `--markdown-output`.
  The CLI only generates review evidence; it never imports `subprocess`.
- [x] **Step 6: Verify GREEN and commit.**
  Commit message: `feat: generate staging infrastructure actions`.

## Task 3: Non-mutating execution readiness gate

**Files:**
- Create: `scripts/tests/test_staging_infrastructure_execution_gate.py`
- Create: `scripts/staging_infrastructure_execution_gate.py`

**Required API:**

```python
def evaluate_execution_readiness(
    manifest: dict[str, Any],
    approval_result: dict[str, Any],
    *,
    plan_bytes: bytes,
) -> dict[str, Any]:
    ...
```

두 API 모두 exact raw plan bytes가 필수다. dict만 전달하는 two-argument 호출은 유효한 provenance 검증이 아니며 허용하지 않는다. exact raw-byte SHA-256과 key-sorted canonical object SHA-256은 서로 다른 증거로 함께 검증한다.

- [x] **Step 1: Write failing readiness and fail-closed tests.**
  A valid reviewed plan with `cloudMutationApproved=false` must return `awaiting-cloud-mutation-approval`. Evidence mismatch, production-like IDs, deployment approval, unknown actions, or missing rollback review must return `blocked`.
- [x] **Step 2: Verify RED.**
  Run `python3 -m unittest scripts.tests.test_staging_infrastructure_execution_gate -v`.
- [x] **Step 3: Implement readiness evaluation and exact missing-approval output.**
  Output `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`, and a `requiredApprovals` list covering mutation architecture, evidence transport, WIF identity, protected environment, least-privilege role diff, cloud-mutation record, and apply dispatch.
- [x] **Step 4: Add failing no-execution tests.**
  Assert the module source has no `subprocess`, `os.system`, shell string, `gcloud`, Firebase CLI invocation, authentication step, credential field, or workflow mutation.
- [x] **Step 5: Implement atomic JSON/Markdown CLI output.**
  CLI inputs: `--plan`, `--execution-manifest`, `--approval-result`, `--json-output`, `--markdown-output`.
- [x] **Step 6: Verify GREEN and commit.**
  Commit message: `feat: report staging execution readiness`.

## Task 4: Runbook, result report, and fresh verification

**Files:**
- Modify: `docs/runbooks/staging-infrastructure-bootstrap.md`
- Create: `docs/superpowers/reports/2026-07-27-staging-infrastructure-execution-gates-result.md`

- [x] **Step 1: Document the three distinct approvals.**
  Separate plan review, cloud mutation approval, and deployment approval. State that the current actual record with `cloudMutationApproved=false` cannot be used for apply.
- [x] **Step 2: Document the unresolved executor trust design.**
  Before an apply workflow can be implemented, choose an approved evidence-transport mechanism for the untracked actual plan/approval package. The later workflow must use the GitHub protected environment as the approval event, pin executor code to an immutable reviewed commit, bind the exact plan/approval/manifest digests before authentication, and never trust a caller-provided attestation boolean.
- [x] **Step 3: Document dry-run, apply, stop, and rollback procedures.**
  Label dry-run and apply procedures as future executor requirements, not currently available commands. No automatic delete rollback. A future executor must stop after the first failed action and preserve evidence.
- [x] **Step 4: Write the implementation result report.**
  Include commits, tests, changed files, security boundaries, known blockers, and the exact approvals still required.
- [x] **Step 5: Run complete fresh verification.**
  Run:
  `python3 -m py_compile` for all new scripts/tests;
  `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`;
  `python3 scripts/validate_staging_config.py`;
  `git diff --check`.
- [x] **Step 6: Confirm no real mutation occurred.**
  Verify no actual operating-value file, credential, token, private key, API key value, secret value, execution evidence, or cloud CLI output is tracked.
- [x] **Step 7: Commit documentation.**
  Commit message: `docs: document staging infrastructure execution gates`.

## Final review and continuation

- [ ] Dispatch a final reviewer over the full implementation range.
- [ ] Fix every Critical or Important issue and re-review.
- [ ] Confirm PR #1 remains Draft/open/unmerged and its remote head was not changed.
- [ ] Use `superpowers:finishing-a-development-branch` and ask before push/PR creation.
- [ ] Before any actual apply, request separate approval for:
  1. `mutation-architecture`
  2. `actual-evidence-transport`
  3. `canonical-mutation-subset`
  4. `staging-infrastructure-apply-environment`
  5. `wif-identity-and-least-privilege-iam-diff`
  6. `cloud-mutation-approval-record`
  7. `apply-workflow-dispatch`

`implementation branch publish`는 위 apply 승인들을 대체하지 않는 별도 integration approval이다.

Operator-local artifacts use `artifacts/actual-infrastructure-review/` and remain untracked. `docs/approvals/records/` remains a compatibility/archive location only; using it requires separate user approval and a redaction policy.

## Later lifecycle

The actual apply executor is intentionally not implemented until the user approves the exact mutation subset and evidence-transport design. After a separately approved apply succeeds, a new plan must consume the captured actual resource identifiers for lifecycle steps 8–12: manifest observation update, live read-only preflight, immutable image build/push evidence, deployment packet, separate deployment approval, deployment executor, acceptance tests, and rollback evidence. Those tasks cannot be implemented against invented resource identifiers and are intentionally blocked until step 7 produces actual evidence.
