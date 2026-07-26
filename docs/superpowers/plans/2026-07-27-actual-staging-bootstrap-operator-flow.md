# Actual Staging Bootstrap Operator Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a fail-closed, non-mutating operator that evaluates the actual staging bootstrap lifecycle from operating-value readiness through bootstrap packet approval and reports the single next allowed action without creating GitHub environments, changing cloud resources, or inventing operational values.

**Architecture:** Add a standard-library Python lifecycle evaluator that composes the existing readiness validator, bootstrap packet validator, approval-record generator, and infrastructure planner approval validator. The operator accepts a local readiness input plus optional packet, packet-source evidence, human review declaration, and approval record; it emits deterministic JSON/Markdown status evidence and may create only a pending packet-review draft. Every stage remains evidence-driven, and absent or inconsistent evidence produces either a specific next action or a blocked state.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, SHA-256, existing `staging_bootstrap_readiness.py`, `staging_bootstrap_approval_record.py`, `staging_infrastructure_plan.py`, and GitHub Actions YAML.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Keep PR #1 open, Draft, and unmerged.
- Baseline head is `5d7318d118d799bbcd850e0860bee02483e02fd4`.
- Preserve the operating order: actual values → readiness → `staging-bootstrap` attestation → actual packet → human review → bootstrap approval record.
- Do not invent actual project IDs, billing accounts, production project IDs, budget amounts, notification recipients, approval references, workflow run IDs, approvers, or timestamps.
- Do not create or modify GitHub environments, environment variables, reviewers, secrets, branch restrictions, WIF identities, GCP/Firebase resources, IAM, billing, APIs, images, or deployments.
- Do not authenticate to GitHub, Google Cloud, or Firebase from the operator.
- Do not invoke subprocesses, cloud CLIs, workflow dispatch APIs, or mutation commands.
- Never write token values, credentials, passwords, private keys, Authorization headers, service-account keys, or Firebase API key values.
- Preserve `cloudMutationApproved=false`, `deploymentApproved=false`, and `mutationCommands=[]` in every report.
- Actual operating values remain in `deploy/staging/staging-bootstrap-readiness.local.json`, which is gitignored.
- A packet-review draft is always `decision=pending`, has no approver or approval timestamp, and has every acknowledgement set to `false`.
- All output files are atomic; failed evaluation leaves no final or temporary output.

---

## File Structure

- Create `scripts/staging_bootstrap_operator.py`: lifecycle state evaluation, evidence loading, safe composition of existing validators, pending review-draft generation, JSON/Markdown rendering, and atomic CLI writes.
- Create `scripts/tests/test_staging_bootstrap_operator.py`: RED/GREEN tests for each lifecycle stage, tamper detection, next-action accuracy, safety flags, review-draft behavior, CLI atomicity, and workflow integration.
- Create `docs/runbooks/staging-bootstrap-operator.md`: actual operator procedure and exact stop boundaries for stages 1–8.
- Modify `.github/workflows/staging-config-validate.yml`: include the new script in path filters and generate deterministic synthetic operator evidence in the PR-only static job.
- Modify `docs/approvals/records/README.md`: document operator status and pending review-draft artifacts as non-approval evidence.

## Lifecycle Status Contract

Report schema:

```text
rhwp.staging-bootstrap-operator-status/v1
```

The report has one of these statuses:

```text
blocked
collect-operating-values
configure-staging-bootstrap-environment
generate-actual-bootstrap-packet
review-actual-bootstrap-packet
generate-bootstrap-approval-record
ready-for-infrastructure-plan
```

The report always contains:

```json
{
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "mutationCommands": []
}
```

## CLI Contract

```bash
python3 scripts/staging_bootstrap_operator.py \
  --readiness-input deploy/staging/staging-bootstrap-readiness.local.json \
  --json-output artifacts/operator/staging-bootstrap-operator-status.json \
  --markdown-output artifacts/operator/staging-bootstrap-operator-status.md
```

Optional evidence:

```text
--packet <path>
--packet-workflow-run-id <positive integer>
--packet-commit-sha <40 lowercase hexadecimal characters>
--review <path>
--approval-record <path>
--review-draft-output <path>
```

Rules:

1. If readiness input is missing or structurally incomplete, status is `collect-operating-values` when the absence represents unconfirmed values; malformed or unsafe input is `blocked`.
2. If readiness evaluates to `ready-for-protected-environment`, status is `configure-staging-bootstrap-environment`.
3. If readiness evaluates to `ready-for-bootstrap-packet` and no packet is supplied, status is `generate-actual-bootstrap-packet`.
4. If packet is supplied, packet workflow run ID and packet commit SHA are mandatory and the commit must match the readiness repository commit.
5. A valid packet without review evidence produces `review-actual-bootstrap-packet` and may generate only a pending review draft bound to exact packet bytes.
6. An approved valid review without an approval record produces `generate-bootstrap-approval-record`.
7. A valid approval record bound to the exact packet bytes produces `ready-for-infrastructure-plan`.
8. Any packet tampering, digest mismatch, wrong commit, invalid workflow run ID, unsafe packet, invalid review, or invalid approval record produces `blocked`.

### Task 1: RED lifecycle tests

**Files:**
- Create: `scripts/tests/test_staging_bootstrap_operator.py`

**Interfaces:**
- Consumes: `evaluate_readiness`, `validate_packet_for_approval`, `validate_review_declaration`, `build_approval_record`, `validate_bootstrap_approval_record`.
- Produces failing tests for `evaluate_operator_status`, `build_pending_review_draft`, `render_markdown`, and `main`.

- [ ] **Step 1:** Create deterministic valid readiness, packet, review, and approval-record fixtures using existing public helpers.
- [ ] **Step 2:** Test missing readiness input maps to `collect-operating-values` without outputting invented values.
- [ ] **Step 3:** Test readiness `ready-for-protected-environment` maps to `configure-staging-bootstrap-environment`.
- [ ] **Step 4:** Test readiness `ready-for-bootstrap-packet` without packet maps to `generate-actual-bootstrap-packet`.
- [ ] **Step 5:** Test a valid packet plus matching source commit/run maps to `review-actual-bootstrap-packet` and produces a pending draft with the exact SHA-256.
- [ ] **Step 6:** Test a valid approved review without a record maps to `generate-bootstrap-approval-record`.
- [ ] **Step 7:** Test a valid planner-compatible record maps to `ready-for-infrastructure-plan`.
- [ ] **Step 8:** Test packet tampering, source commit mismatch, zero run ID, sensitive keys, review digest mismatch, and approval-record mismatch produce `blocked`.
- [ ] **Step 9:** Test all status outputs preserve false approval flags and empty mutation commands.
- [ ] **Step 10:** Test CLI atomic writes and no partial output after failure.
- [ ] **Step 11:** Run `python3 -m unittest scripts.tests.test_staging_bootstrap_operator -v` and verify RED because `scripts.staging_bootstrap_operator` does not exist.
- [ ] **Step 12:** Commit tests only.

### Task 2: Lifecycle evaluator and pending review draft

**Files:**
- Create: `scripts/staging_bootstrap_operator.py`

**Interfaces:**
- `evaluate_operator_status(readiness: dict[str, Any], *, packet: dict[str, Any] | None, packet_bytes: bytes | None, packet_workflow_run_id: int | None, packet_commit_sha: str | None, review: dict[str, Any] | None, approval_record: dict[str, Any] | None) -> dict[str, Any]`
- `build_pending_review_draft(packet: dict[str, Any], packet_bytes: bytes, *, commit_sha: str, workflow_run_id: int) -> dict[str, Any]`
- `render_markdown(report: dict[str, Any]) -> str`
- `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1:** Implement strict JSON loaders that preserve packet bytes and never invoke external commands.
- [ ] **Step 2:** Compose `evaluate_readiness` and map its three statuses to operator statuses.
- [ ] **Step 3:** Validate packet source evidence and exact commit binding before packet review.
- [ ] **Step 4:** Validate packet safety and compute the exact-byte SHA-256 digest.
- [ ] **Step 5:** Build a pending review draft containing the expected digest, packet reference, packet source commit/run, no approver, no timestamp, and all acknowledgements false.
- [ ] **Step 6:** Validate an approved review and compare its expected digest against packet bytes.
- [ ] **Step 7:** Validate an existing approval record with `validate_bootstrap_approval_record`.
- [ ] **Step 8:** Produce deterministic JSON and Markdown status evidence with masked billing metadata only.
- [ ] **Step 9:** Implement atomic writes for status JSON, Markdown, and optional pending review draft.
- [ ] **Step 10:** Run focused and complete staging tests and verify GREEN.
- [ ] **Step 11:** Commit implementation.

### Task 3: Operator runbook and records policy

**Files:**
- Create: `docs/runbooks/staging-bootstrap-operator.md`
- Modify: `docs/approvals/records/README.md`

**Interfaces:**
- Consumes: local readiness input, actual bootstrap packet artifact, packet source workflow evidence, optional review declaration, optional approval record.
- Produces: a repeatable operator procedure and clear artifact classification.

- [ ] **Step 1:** Document actual-value collection and the gitignored readiness path.
- [ ] **Step 2:** Document the first readiness result and `staging-bootstrap` Environment UI attestation requirements.
- [ ] **Step 3:** Document actual packet generation with `approval_phase=bootstrap` and `live_check=false`.
- [ ] **Step 4:** Document packet download without reformatting, exact-byte digest preservation, and packet source run/commit evidence.
- [ ] **Step 5:** Document pending review-draft generation and the human-only fields that must be completed after review.
- [ ] **Step 6:** Document approval-record generation using the existing protected `bootstrap-review` workflow.
- [ ] **Step 7:** Document that `ready-for-infrastructure-plan` authorizes planning only, not resource mutation.
- [ ] **Step 8:** Add operator status and pending review draft to the allowed non-approval evidence list.
- [ ] **Step 9:** Commit documentation.

### Task 4: Deterministic PR workflow evidence

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_bootstrap_operator.py`

**Interfaces:**
- Consumes: documentation-safe synthetic readiness and bootstrap packet fixtures.
- Produces: artifact `staging-bootstrap-operator-test-evidence`.

- [ ] **Step 1:** Add `scripts/staging_bootstrap_operator.py` and `docs/runbooks/staging-bootstrap-operator.md` to PR path filters.
- [ ] **Step 2:** Add a static-job step that creates synthetic ready-for-packet evidence and a synthetic packet source run ID that cannot be confused with an actual run.
- [ ] **Step 3:** Run the operator without review evidence and generate a pending synthetic review draft.
- [ ] **Step 4:** Upload only test-labelled operator status JSON/Markdown and pending review draft.
- [ ] **Step 5:** Verify the static job requests `contents: read` only and uses no cloud authentication or mutation command.
- [ ] **Step 6:** Verify all protected operational jobs remain skipped on pull-request events.
- [ ] **Step 7:** Commit workflow changes.

### Task 5: Fresh verification

- [ ] **Step 1:** Run Python compilation for the new script and tests.
- [ ] **Step 2:** Run `python3 -m unittest scripts.tests.test_staging_bootstrap_operator -v`.
- [ ] **Step 3:** Run `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`.
- [ ] **Step 4:** Run `python3 scripts/validate_staging_config.py`.
- [ ] **Step 5:** Inspect synthetic operator artifact for exact packet digest, pending review state, masked billing data, and safety flags.
- [ ] **Step 6:** Scan generated files for access tokens, ID tokens, Authorization data, credentials, passwords, private keys, secret values, Bearer data, mutation commands, and actual operational identifiers.
- [ ] **Step 7:** Verify the final `Staging configuration` run succeeds and protected bootstrap, bootstrap-review, infrastructure, and live jobs remain skipped on the PR event.
- [ ] **Step 8:** Verify final-head CI, CodeQL, Render Diff, browser, Emulator, Studio, and service workflows.
- [ ] **Step 9:** Confirm PR #1 remains Draft and unmerged.

## Deliberate Stop Boundary

This implementation does not complete real operational steps by itself. It does not create or modify GitHub Environments, collect credentials, dispatch workflows, download actual artifacts, approve packets, create actual approval records, create infrastructure, perform live preflight, build images, or deploy.

The operator may report `ready-for-infrastructure-plan` only after all of the following real evidence exists and validates:

1. Concrete staging operating values and forbidden production IDs.
2. Successful workflow evidence for the same current commit.
3. Approved governance decisions and checklist.
4. Attested `staging-bootstrap` protected environment.
5. An actual bootstrap packet generated by the protected workflow.
6. Exact packet source commit and workflow run ID.
7. Human approval of the exact packet bytes.
8. A planner-compatible bootstrap approval record bound to the packet SHA-256.

Even `ready-for-infrastructure-plan` does not authorize project creation, billing linkage, API activation, IAM changes, resource mutation, live preflight, image publication, or deployment.
