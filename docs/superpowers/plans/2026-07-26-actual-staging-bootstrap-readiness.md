# Actual Staging Bootstrap Readiness Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, non-mutating readiness gate that binds reviewed staging operating values, required GitHub workflow results, protected-environment evidence, and planned/observed Firebase resource identities before the first actual bootstrap approval packet can be generated.

**Architecture:** Introduce a reviewed readiness declaration (`rhwp.staging-bootstrap-readiness-input/v1`) as the single machine-readable handoff between human decisions and the existing materializer. The declaration separates planned and observed Firebase Storage bucket names, records required workflow outcomes and protected-environment attestations, and is normalized into the existing `rhwp.staging-bootstrap-values/v1` contract only after every gate passes. A standard-library Python validator produces deterministic JSON/Markdown readiness evidence and normalized materializer values without network calls, subprocesses, cloud authentication, GitHub mutations, or cloud mutations.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, GitHub Actions YAML, existing `staging_bootstrap_materializer.py`, `staging_preflight.py`, and `staging_approval_packet.py`.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Keep PR #1 open, Draft, and unmerged.
- Verify CI run #403 status before implementation and record its actual status; do not claim success while it is incomplete.
- Write failing tests and observe RED before adding production implementation.
- Do not create or modify GitHub protected environments, reviewers, variables, secrets, branch restrictions, or Actions permissions outside repository files.
- Do not create or modify GCP/Firebase projects, billing links, APIs, IAM, service accounts, Storage, Firestore, Hosting, Cloud Run, Cloud Tasks, Artifact Registry, Secret Manager, budgets, images, or deployments.
- Do not run live preflight, cloud authentication, image build/push, resource creation, or staging deployment.
- Never store token values, credentials, passwords, private keys, Authorization headers, service-account keys, or Firebase API key values.
- Keep monetary values in KRW without conversion.
- Preserve `operations.cloudMutationApproved=false`, `mutationCommands=[]`, and `deploymentApproved=false`.
- A planned resource name is intent, not observed cloud state. A missing observed value must be represented as `null`, never copied or relabeled as observed.

---

## File Structure

- Create `scripts/staging_bootstrap_readiness.py`: strict readiness-input validation, planned/observed resource selection, workflow and protected-environment checks, normalized materializer values, deterministic JSON/Markdown output, and atomic CLI writes.
- Create `scripts/tests/test_staging_bootstrap_readiness.py`: RED/GREEN tests for workflow gates, governance confirmations, environment evidence, planned/observed Storage behavior, redaction, normalization, CLI atomicity, and existing materializer/packet integration.
- Create `deploy/staging/staging-bootstrap-readiness.example.json`: documentation-safe pending input showing the complete schema and `observed=null` resource state.
- Create `docs/runbooks/staging-bootstrap-readiness.md`: operator flow, status meanings, actual value confirmation, environment evidence, packet generation boundary, and stop conditions.
- Modify `docs/approvals/staging-bootstrap-values-decision.md`: replace the ambiguous Storage bucket “actual value” language with planned/observed terminology.
- Modify `docs/approvals/staging-bootstrap-values-checklist.md`: add separate planned and observed checks and readiness evidence requirements.
- Modify `docs/runbooks/staging-bootstrap-inputs.md`: describe readiness normalization into the legacy materializer values contract.
- Modify `.github/workflows/staging-config-validate.yml`: include the new script in path filters and generate deterministic readiness test evidence only; do not trigger protected jobs or cloud authentication.

## Readiness Input Contract

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-readiness-input/v1",
  "repository": {
    "fullName": "WBmaker2/rhwp",
    "branch": "feat/firebase-collaboration-mvp-v1",
    "prNumber": 1,
    "commitSha": "40 lowercase hexadecimal characters"
  },
  "workflows": [
    {
      "name": "CI",
      "runNumber": 403,
      "status": "completed",
      "conclusion": "success"
    }
  ],
  "governance": {
    "decisionStatus": "approved",
    "checklistComplete": true,
    "billingOwnerConfirmed": true,
    "budgetApprovedKrw": true,
    "notificationRecipientsConfirmed": true,
    "privacyRetentionReviewed": true,
    "internalFlushExceptionAccepted": true
  },
  "protectedEnvironment": {
    "name": "staging-bootstrap",
    "configured": true,
    "requiredReviewerCount": 1,
    "branchRestricted": true,
    "secretNames": [],
    "cloudCredentialsPresent": false,
    "idTokenWrite": false,
    "variableNames": []
  },
  "values": {
    "schemaVersion": "rhwp.staging-bootstrap-values/v1",
    "project": {},
    "firebase": {
      "storageBucket": {
        "planned": "<project-id>.firebasestorage.app",
        "observed": null
      }
    },
    "budget": {},
    "operations": {}
  }
}
```

Required workflow names are `CI`, `CodeQL`, `Render Diff`, and `Staging configuration`; each must be `completed/success`, refer to the target commit, and use a positive run number. The protected-environment variable allowlist remains the nine existing materializer variables. The readiness declaration records their names only, never their values outside the nested reviewed values object.

## Status Contract

- `blocked`: any workflow, governance, environment, value, or security check fails.
- `ready-for-protected-environment`: values, workflows, and governance pass, but protected-environment evidence is not yet complete.
- `ready-for-bootstrap-packet`: every check passes; normalized materializer values may be emitted.

The CLI exits non-zero for `blocked`. It may emit a report for `ready-for-protected-environment`, but must not emit normalized materializer values. Only `ready-for-bootstrap-packet` emits normalized values.

---

### Task 1: Record CI #403 gate state

**Files:**
- No repository changes beyond this plan.

- [ ] **Step 1:** Query PR head `7358871e65da712ebdd8c932b1076e6ae72200b9` workflow runs.
- [ ] **Step 2:** Record CI #403 as success only if GitHub reports `status=completed` and `conclusion=success`.
- [ ] **Step 3:** Continue implementation while preserving CI as a required readiness gate; do not generate an actual packet while it is incomplete.

### Task 2: RED readiness tests

**Files:**
- Create: `scripts/tests/test_staging_bootstrap_readiness.py`

- [ ] **Step 1:** Add tests requiring exact schema keys, the four required successful workflows, target repository/branch/PR/commit, and no duplicate workflow names.
- [ ] **Step 2:** Add tests for `blocked`, `ready-for-protected-environment`, and `ready-for-bootstrap-packet` statuses.
- [ ] **Step 3:** Add tests that preserve `planned` and `observed` separately, select observed when present, select planned when observed is null, and never manufacture an observed value.
- [ ] **Step 4:** Add tests for exact protected-environment variable names, no secrets, no cloud credentials, no `id-token: write`, reviewer count, and branch restriction.
- [ ] **Step 5:** Add CLI tests for atomic report/Markdown/normalized-values writes and no partial output on failure.
- [ ] **Step 6:** Add integration tests passing normalized values through the existing materializer, static preflight, and bootstrap packet generator.
- [ ] **Step 7:** Run the test module and verify RED because `scripts.staging_bootstrap_readiness` does not exist.
- [ ] **Step 8:** Commit tests only.

### Task 3: Readiness validator and normalizer

**Files:**
- Create: `scripts/staging_bootstrap_readiness.py`

**Interfaces:**
- `evaluate_readiness(payload: dict[str, Any]) -> dict[str, Any]`
- `normalize_materializer_values(payload: dict[str, Any]) -> dict[str, Any]`
- `render_markdown(report: dict[str, Any]) -> str`
- `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1:** Implement exact-key, type, staging-project, KRW, retention, approval-reference, and sensitive-key validation.
- [ ] **Step 2:** Implement workflow checks bound to repository, branch, PR, commit, and the four required successful run names.
- [ ] **Step 3:** Implement governance and protected-environment checks with explicit blocked reasons.
- [ ] **Step 4:** Implement planned/observed Storage selection and provenance without rewriting `observed=null`.
- [ ] **Step 5:** Reuse `validate_bootstrap_values` on normalized values before reporting packet readiness.
- [ ] **Step 6:** Implement deterministic sanitized JSON/Markdown and atomic output.
- [ ] **Step 7:** Run focused tests and verify GREEN.
- [ ] **Step 8:** Run all Python tests and the existing staging validator.

### Task 4: Example input and documentation

**Files:**
- Create: `deploy/staging/staging-bootstrap-readiness.example.json`
- Create: `docs/runbooks/staging-bootstrap-readiness.md`
- Modify: `docs/approvals/staging-bootstrap-values-decision.md`
- Modify: `docs/approvals/staging-bootstrap-values-checklist.md`
- Modify: `docs/runbooks/staging-bootstrap-inputs.md`

- [ ] **Step 1:** Add a pending example with documentation-safe identifiers, CI #403 represented according to its verified status, environment evidence incomplete, and observed Storage null.
- [ ] **Step 2:** Document that planned Storage is approved intent and observed Storage is post-creation evidence.
- [ ] **Step 3:** Document the exact actual-value fields the user must confirm and the exact evidence that the repository cannot infer.
- [ ] **Step 4:** Document that protected-environment evidence is an operator attestation and does not create or inspect the GitHub environment.
- [ ] **Step 5:** Document commands that produce readiness artifacts and, only after packet readiness, normalized values and the first bootstrap packet.

### Task 5: Static workflow evidence

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_bootstrap_readiness.py`

- [ ] **Step 1:** Add the readiness script and runbook paths to the PR trigger.
- [ ] **Step 2:** Generate deterministic readiness test evidence from a temporary test fixture, not from actual operating values.
- [ ] **Step 3:** Upload `staging-bootstrap-readiness-test-evidence` containing report JSON, Markdown, and normalized values.
- [ ] **Step 4:** Verify the static job contains no GCP/Firebase authentication, no GitHub environment mutation, and no cloud mutation command.

### Task 6: Fresh verification and stop boundary

- [ ] **Step 1:** Run `python3 -m py_compile scripts/staging_bootstrap_readiness.py scripts/tests/test_staging_bootstrap_readiness.py`.
- [ ] **Step 2:** Run `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`.
- [ ] **Step 3:** Run `python3 scripts/validate_staging_config.py`.
- [ ] **Step 4:** Verify the readiness integration produces `mutationCommands=[]`, `cloudMutationApproved=false`, and no secret values.
- [ ] **Step 5:** Verify all final-head PR workflows and PR Draft/unmerged state.
- [ ] **Step 6:** Stop before actual values, GitHub Environment configuration, or actual packet generation unless concrete values and explicit approvals are supplied.

## Deliberate Stop Boundary

This implementation does not invent or finalize the staging project ID, billing account, production project IDs, planned Storage bucket, monthly KRW budget, notification recipients, or approval reference. It does not create the `staging-bootstrap` environment or generate an actual bootstrap packet. Those actions require reviewed concrete input and, for GitHub settings, an explicit repository mutation approval. The completed validator must instead report exactly which evidence is still missing.