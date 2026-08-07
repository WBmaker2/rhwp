# Staging Bootstrap Approval Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a reviewable, fail-closed staging lifecycle from operating-value decisions through bootstrap approval and infrastructure planning, while preventing cloud mutations until separate approvals and concrete staging values exist.

**Architecture:** Human decisions remain in Markdown and a strict non-secret values JSON. Existing materialization, static preflight, and bootstrap packet generation remain the source of truth. New approval-record and infrastructure-plan generators consume validated artifacts and produce deterministic JSON/Markdown evidence without executing cloud commands. GitHub Actions may generate review artifacts behind protected environments, but resource creation, live preflight, and deployment remain separately approved execution phases.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, GitHub Actions YAML, existing `staging_bootstrap_materializer.py`, `staging_preflight.py`, and `staging_approval_packet.py`.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Keep PR #1 open, Draft, and unmerged.
- Write failing tests and verify RED before adding each production implementation.
- Do not create or change GCP projects, billing links, enabled APIs, Firebase resources, IAM bindings, service accounts, Artifact Registry, Secret Manager, Cloud Tasks, budgets, Cloud Run services, Hosting, Rules, Indexes, or container images in this implementation unit.
- Do not run live preflight or staging deployment without a later, explicit approval bound to concrete artifacts.
- Do not create or modify the actual GitHub `staging-bootstrap`, `staging-infrastructure`, `staging-preflight`, or `staging-deployment` environments; only define repository contracts that reference them.
- Never store secret values, access tokens, credentials, passwords, private keys, Authorization headers, or service-account key files.
- Keep all monetary values in KRW without conversion.
- Preserve `operations.cloudMutationApproved=false` until a distinct infrastructure execution approval record is supplied.
- All generated records must include `mutationCommands=[]` and must not invoke subprocesses or cloud CLIs.

---

## File Structure

- Create `docs/approvals/staging-bootstrap-values-decision.md`: human decision draft with exact decision fields, recommended defaults, evidence requirements, and unresolved-state rules.
- Create `docs/approvals/staging-bootstrap-values-checklist.md`: operator checklist for confirming concrete values and GitHub protected-environment settings.
- Create `docs/approvals/staging-bootstrap-approval-record.example.json`: machine-readable bootstrap packet approval record example.
- Create `docs/approvals/staging-infrastructure-approval-record.example.json`: machine-readable infrastructure-plan approval record example.
- Create `docs/approvals/staging-deployment-approval-record.example.json`: machine-readable deployment approval record example.
- Create `scripts/staging_infrastructure_plan.py`: validate bootstrap packet and approval record, then generate deterministic infrastructure-plan JSON and Markdown without cloud commands.
- Create `scripts/tests/test_staging_infrastructure_plan.py`: RED/GREEN tests for evidence binding, project consistency, secret rejection, ordered resources, rollback, CLI output, and workflow contract.
- Create `docs/runbooks/staging-infrastructure-bootstrap.md`: review and execution boundary for lifecycle steps 5–12.
- Modify `.github/workflows/staging-config-validate.yml`: add a plan-only job that generates an infrastructure plan only when a committed approved bootstrap record is explicitly supplied.
- Modify `docs/runbooks/staging-bootstrap-inputs.md` and `docs/runbooks/staging-approval-packet.md`: link the decision and approval records and clarify stop conditions.

## Artifact Contracts

### Bootstrap approval record

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-approval/v1",
  "decision": "approved",
  "approvedAt": "2026-07-26T00:00:00Z",
  "approvedBy": ["repository-owner"],
  "commitSha": "40 lowercase hexadecimal characters",
  "workflowRunId": 1,
  "packetSha256": "64 lowercase hexadecimal characters",
  "projectId": "concrete staging project ID",
  "billingAccount": "XXXXXX-XXXXXX-XXXXXX",
  "acceptedDeferredPaths": ["manifest.project.number"],
  "securityExceptions": ["mvp-staging-internal-token"],
  "deploymentApproved": false,
  "cloudMutationApproved": false
}
```

The planner rejects pending or rejected decisions, project mismatches, packet digest mismatches, unknown keys, secret-like keys, production-like project IDs, `deploymentApproved=true`, and `cloudMutationApproved=true`.

### Infrastructure plan

```json
{
  "schemaVersion": "rhwp.staging-infrastructure-plan/v1",
  "status": "ready-for-infrastructure-approval",
  "projectId": "concrete staging project ID",
  "billingAccount": "XXXXXX-XXXXXX-XXXXXX",
  "sourceEvidence": {},
  "stages": [],
  "postBootstrapRequiredValues": [],
  "rollback": [],
  "security": {
    "readOnlyGenerator": true,
    "containsCloudMutationCommands": false,
    "mutationCommands": []
  }
}
```

The plan lists intended operations as structured resource actions, dependencies, least-privilege boundaries, acceptance evidence, and rollback descriptions. It never emits shell commands.

---

### Task 1: Decision and checklist documents

**Files:**
- Create: `docs/approvals/staging-bootstrap-values-decision.md`
- Create: `docs/approvals/staging-bootstrap-values-checklist.md`

**Interfaces:**
- Consumes: existing `rhwp.staging-bootstrap-values/v1` schema and `staging-bootstrap` workflow variable names.
- Produces: a human review surface that can be copied into `staging-bootstrap-values.local.json` or protected-environment variables.

- [ ] **Step 1:** Write the decision document with nine required values, recommended defaults, validation rules, production separation, KRW budget rules, retention, and internal-flush decision.
- [ ] **Step 2:** Write the checklist with repository, GCP, Firebase, billing, security, and evidence checks.
- [ ] **Step 3:** Verify every required environment variable appears exactly once in the checklist.
- [ ] **Step 4:** Commit the documentation before implementation code.

### Task 2: Approval record examples and validation tests

**Files:**
- Create: `docs/approvals/staging-bootstrap-approval-record.example.json`
- Create: `docs/approvals/staging-infrastructure-approval-record.example.json`
- Create: `docs/approvals/staging-deployment-approval-record.example.json`
- Create: `scripts/tests/test_staging_infrastructure_plan.py`

**Interfaces:**
- Consumes: bootstrap packet JSON and SHA-256 digest.
- Produces: failing tests for `validate_bootstrap_approval_record`, `build_infrastructure_plan`, `render_markdown`, and `main`.

- [ ] **Step 1:** Add examples with documentation-safe IDs and `cloudMutationApproved=false`.
- [ ] **Step 2:** Write tests that require exact schema keys, approved decision, artifact digest binding, project/billing consistency, allowed deferred paths, and no secrets.
- [ ] **Step 3:** Write tests for deterministic ordered infrastructure stages and `mutationCommands=[]`.
- [ ] **Step 4:** Write CLI and workflow-contract tests.
- [ ] **Step 5:** Run the new test module and verify RED because `scripts.staging_infrastructure_plan` does not exist.
- [ ] **Step 6:** Commit tests only.

### Task 3: Infrastructure plan generator

**Files:**
- Create: `scripts/staging_infrastructure_plan.py`

**Interfaces:**
- `validate_bootstrap_approval_record(record: dict[str, Any], packet: dict[str, Any], packet_sha256: str) -> None`
- `build_infrastructure_plan(manifest: dict[str, Any], packet: dict[str, Any], approval: dict[str, Any], packet_sha256: str) -> dict[str, Any]`
- `render_markdown(plan: dict[str, Any]) -> str`
- `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1:** Implement strict JSON loading, exact-key validation, sensitive-key rejection, digest validation, and staging project checks.
- [ ] **Step 2:** Build ordered stages for project/billing, APIs, Firebase, service accounts, Artifact Registry, Secret metadata, IAM, budget, Cloud Run prerequisites, Cloud Tasks prerequisites, and post-bootstrap evidence collection.
- [ ] **Step 3:** Add dependencies, acceptance evidence, rollback descriptions, and required post-bootstrap identifiers.
- [ ] **Step 4:** Implement sanitized Markdown rendering and atomic JSON/Markdown output.
- [ ] **Step 5:** Run the focused tests and verify GREEN.
- [ ] **Step 6:** Run the complete Python test suite and existing staging validator.
- [ ] **Step 7:** Commit the implementation.

### Task 4: Protected plan-only workflow

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_infrastructure_plan.py`

**Interfaces:**
- Consumes: repository-relative materialized manifest, bootstrap packet, and approved bootstrap record paths supplied by manual dispatch.
- Produces: `staging-infrastructure-bootstrap-plan` artifact.

- [ ] **Step 1:** Add manual inputs for `infrastructure_plan`, manifest path, packet path, and approval-record path.
- [ ] **Step 2:** Add a `staging-infrastructure` protected-environment job with `contents: read` only.
- [ ] **Step 3:** Run the planner without GCP authentication, cloud CLI installation, or mutation commands.
- [ ] **Step 4:** Upload JSON and Markdown plan artifacts.
- [ ] **Step 5:** Verify PR-triggered runs skip the protected job.
- [ ] **Step 6:** Run workflow contract tests and commit.

### Task 5: Runbook and later-phase gates

**Files:**
- Create: `docs/runbooks/staging-infrastructure-bootstrap.md`
- Modify: `docs/runbooks/staging-bootstrap-inputs.md`
- Modify: `docs/runbooks/staging-approval-packet.md`

**Interfaces:**
- Consumes: the decision, packet, approval, and infrastructure-plan artifacts.
- Produces: explicit stop/go rules for lifecycle steps 1–12.

- [ ] **Step 1:** Document steps 1–6 as non-mutating preparation and review.
- [ ] **Step 2:** Document step 7 as a separate executor implementation and approval unit; no executor is introduced in this plan.
- [ ] **Step 3:** Define the post-bootstrap identifiers required before live preflight.
- [ ] **Step 4:** Define deployment packet and deployment approval requirements.
- [ ] **Step 5:** State that the approval record does not authorize resource creation or deployment unless its dedicated schema and decision explicitly do so.
- [ ] **Step 6:** Commit runbook changes.

### Task 6: Fresh verification

- [ ] **Step 1:** Run `python3 -m py_compile scripts/staging_infrastructure_plan.py scripts/tests/test_staging_infrastructure_plan.py`.
- [ ] **Step 2:** Run `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`.
- [ ] **Step 3:** Run `python3 scripts/validate_staging_config.py`.
- [ ] **Step 4:** Verify the plan generator with documentation-safe example artifacts and inspect JSON/Markdown outputs.
- [ ] **Step 5:** Confirm generated files contain no token, credential, private key, secret value, shell mutation command, or production project ID.
- [ ] **Step 6:** Verify all PR workflows, including CI, CodeQL, Staging configuration, Render Diff, browser visual, and Emulator E2E.
- [ ] **Step 7:** Confirm PR #1 remains Draft and unmerged.

## Deliberate Stop Boundary

This plan does not implement or execute lifecycle step 7, staging resource creation. Step 7 requires all of the following in a separate user-approved implementation unit:

1. Concrete actual staging values.
2. An actual bootstrap packet generated from those values.
3. A reviewed bootstrap approval record bound to the packet digest and commit SHA.
4. A reviewed infrastructure plan.
5. A separate infrastructure approval record that explicitly permits cloud mutations.
6. Confirmed billing ownership, protected environments, WIF identities, least-privilege roles, and rollback procedures.

Steps 8–12 remain blocked until step 7 completes and actual resource identifiers are captured.