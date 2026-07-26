# Actual Bootstrap Packet Review and Approval Record Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a fail-closed, non-mutating generator that reviews an actual bootstrap approval packet, computes its exact SHA-256 digest, binds human approval metadata to the packet and source workflow, and emits an infrastructure-planner-compatible bootstrap approval record.

**Architecture:** A strict review declaration contains only human-entered approval metadata and explicit acknowledgements. The generator derives project ID, billing account, deferred paths, security exceptions, and packet digest directly from the packet rather than accepting duplicated operator input. It validates packet safety and review intent, produces deterministic JSON/Markdown review evidence, then emits the existing `rhwp.staging-bootstrap-approval/v1` record accepted by `scripts/staging_infrastructure_plan.py`.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, SHA-256, GitHub Actions YAML, existing `staging_approval_packet.py` and `staging_infrastructure_plan.py` contracts.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Keep PR #1 open, Draft, and unmerged.
- The current baseline head is `107021bc3a02c3a4f389f90c9b8a26f798ef1784`.
- Baseline workflow evidence is `CI #416`, `CodeQL #415`, `Render Diff #298`, and `Staging configuration #241`, all completed successfully on the same baseline head.
- Write failing tests and observe RED before adding production implementation.
- Do not invent actual project IDs, billing accounts, approval references, workflow run IDs, approvers, or approval timestamps.
- Do not create an actual approved record from documentation-safe fixtures.
- Do not create or modify GitHub protected environments, reviewers, variables, secrets, branch restrictions, or cloud identities.
- Do not authenticate to GCP/Firebase, query cloud state, create resources, enable APIs, change IAM, build images, run live preflight, or deploy.
- Never store secret values, tokens, credentials, passwords, private keys, Authorization headers, service-account keys, or Firebase API key values.
- Keep all budget amounts in `KRW`; do not convert currency.
- Preserve `cloudMutationApproved=false`, `deploymentApproved=false`, and `mutationCommands=[]`.
- Approval record generation must fail if the packet bytes, packet status, project, billing account, deferred paths, approval reference, or security acknowledgements are invalid.
- All output files must be written atomically; failed generation must leave no final or temporary output.

---

## File Structure

- Create `scripts/staging_bootstrap_approval_record.py`: packet validation, review declaration validation, exact-byte SHA-256 calculation, derived approval record, review result JSON, Markdown rendering, atomic CLI output.
- Create `scripts/tests/test_staging_bootstrap_approval_record.py`: RED/GREEN tests for digest binding, packet safety, review acknowledgements, derived fields, tampering, sensitive keys, planner compatibility, CLI atomicity, and workflow contract.
- Create `docs/approvals/staging-bootstrap-packet-review.example.json`: intentionally pending documentation-safe review declaration template.
- Create `docs/runbooks/staging-bootstrap-packet-review.md`: operator review procedure, actual artifact handling, approval record generation, digest verification, storage rules, and stop conditions.
- Modify `.github/workflows/staging-config-validate.yml`: add a non-mutating `bootstrap-review` manual phase and deterministic synthetic test evidence; protected jobs remain skipped on pull requests.
- Modify `docs/approvals/records/README.md`: add review declaration/result artifacts and distinguish packet review from infrastructure mutation approval.
- Modify `docs/runbooks/staging-infrastructure-bootstrap.md`: connect lifecycle step 4 to the new generator and retain the step 7 mutation boundary.

## Review Declaration Contract

Schema:

```text
rhwp.staging-bootstrap-packet-review/v1
```

Exact structure:

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-packet-review/v1",
  "decision": "approved",
  "approvedAt": "2026-07-27T00:00:00Z",
  "approvedBy": ["repository-owner"],
  "commitSha": "40 lowercase hexadecimal characters",
  "workflowRunId": 1,
  "artifactName": "staging-approval-packet-bootstrap",
  "expectedApprovalReference": "staging-bootstrap-approval-YYYY-MM-DD-NNN",
  "acknowledgements": {
    "packetReviewed": true,
    "deferredPathsAccepted": true,
    "billingAndBudgetReviewed": true,
    "internalFlushExceptionAccepted": true,
    "cloudMutationNotApproved": true,
    "deploymentNotApproved": true
  },
  "notes": []
}
```

The generator rejects `pending` or `rejected` decisions, null approval metadata, malformed commit SHA, non-positive run ID, unexpected artifact name, approval-reference mismatch, any false acknowledgement, unknown keys, duplicate approvers, and sensitive-like keys.

## Derived Approval Record Contract

The generator emits the existing exact schema:

```text
rhwp.staging-bootstrap-approval/v1
```

Derived fields:

- `packetSha256`: SHA-256 of the exact packet JSON file bytes, not reserialized JSON.
- `projectId`: `packet.project.id`.
- `billingAccount`: `packet.project.billingAccount`.
- `acceptedDeferredPaths`: sorted unique `packet.deferredValues[*].path`.
- `securityExceptions`: `mvp-staging-internal-token` only when required by `packet.internalFlush.decision`.
- `decision`, `approvedAt`, `approvedBy`, `commitSha`, and `workflowRunId`: validated review declaration values.
- `deploymentApproved=false`.
- `cloudMutationApproved=false`.

The completed record must pass `scripts.staging_infrastructure_plan.validate_bootstrap_approval_record` without adaptation.

## Review Result Contract

Schema:

```text
rhwp.staging-bootstrap-packet-review-result/v1
```

Required safety properties:

```json
{
  "status": "approved-record-generated",
  "packetSha256": "64 lowercase hexadecimal characters",
  "cloudMutationApproved": false,
  "deploymentApproved": false,
  "mutationCommands": []
}
```

The result also records approval reference, packet phase/status, project ID, masked billing account, commit SHA, workflow run ID, artifact name, approvers, accepted deferred paths, acknowledged security exceptions, and output record schema.

---

### Task 1: RED tests for packet review and approval record

**Files:**
- Create: `scripts/tests/test_staging_bootstrap_approval_record.py`

**Interfaces:**
- Consumes: synthetic bootstrap packet built with existing materializer, static preflight, and packet generator.
- Produces failing tests for `validate_packet_for_approval`, `validate_review_declaration`, `build_approval_record`, `build_review_result`, `render_markdown`, and `main`.

- [ ] **Step 1:** Build a deterministic bootstrap packet fixture and exact serialized bytes fixture.
- [ ] **Step 2:** Test exact-byte digest generation and verify that whitespace-only packet changes produce a different digest.
- [ ] **Step 3:** Test packet requirements: schema, `phase=bootstrap`, `status=ready-for-bootstrap-approval`, static-only preflight, `cloudMutationApproved=false`, `packetIsDeploymentApproval=false`, `containsCloudMutationCommands=false`, and `mutationCommands=[]`.
- [ ] **Step 4:** Test review exact keys, approved decision, UTC timestamp, non-empty unique approvers, commit SHA, positive run ID, artifact name, approval reference, and all acknowledgements.
- [ ] **Step 5:** Test derived project, billing, deferred paths, and internal-flush security exception.
- [ ] **Step 6:** Test sensitive-key rejection without leaking sensitive values.
- [ ] **Step 7:** Test output compatibility with `validate_bootstrap_approval_record`.
- [ ] **Step 8:** Test CLI atomic JSON/Markdown/record outputs and no partial output on failure.
- [ ] **Step 9:** Run focused tests and verify RED because `scripts.staging_bootstrap_approval_record` does not exist.
- [ ] **Step 10:** Commit tests only.

### Task 2: Approval record generator

**Files:**
- Create: `scripts/staging_bootstrap_approval_record.py`

**Interfaces:**
- `packet_sha256(packet_bytes: bytes) -> str`
- `validate_packet_for_approval(packet: dict[str, Any]) -> None`
- `validate_review_declaration(review: dict[str, Any], packet: dict[str, Any]) -> None`
- `build_approval_record(packet: dict[str, Any], review: dict[str, Any], digest: str) -> dict[str, Any]`
- `build_review_result(packet: dict[str, Any], review: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]`
- `render_markdown(result: dict[str, Any]) -> str`
- `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1:** Implement exact JSON loading while retaining raw packet bytes for digest calculation.
- [ ] **Step 2:** Implement strict packet, review, sensitive-key, project, billing, deferred-path, and safety-boundary validation.
- [ ] **Step 3:** Derive the exact existing approval record schema from packet and review inputs.
- [ ] **Step 4:** Validate generated records with the infrastructure planner validator.
- [ ] **Step 5:** Build sanitized review result JSON and Markdown.
- [ ] **Step 6:** Implement atomic writes for review JSON, review Markdown, and approval record JSON.
- [ ] **Step 7:** Run focused and complete staging tests and verify GREEN.
- [ ] **Step 8:** Commit implementation.

### Task 3: Documentation-safe pending review template and runbook

**Files:**
- Create: `docs/approvals/staging-bootstrap-packet-review.example.json`
- Create: `docs/runbooks/staging-bootstrap-packet-review.md`
- Modify: `docs/approvals/records/README.md`
- Modify: `docs/runbooks/staging-infrastructure-bootstrap.md`

**Interfaces:**
- Consumes: actual packet artifact downloaded from `staging-approval-packet-bootstrap` and human review metadata.
- Produces: a repeatable operator procedure without creating an actual approval.

- [ ] **Step 1:** Add a pending example with null timestamp, empty approvers, zero run ID, and all acknowledgements false.
- [ ] **Step 2:** Document exact packet-byte preservation and SHA-256 behavior.
- [ ] **Step 3:** Document reviewer checks for project, billing, KRW budget, notification channels, deferred paths, internal-flush exception, and safety flags.
- [ ] **Step 4:** Document output storage under `docs/approvals/records/<approval-reference>/` only after actual review.
- [ ] **Step 5:** State that bootstrap approval does not authorize infrastructure mutation or deployment.
- [ ] **Step 6:** Commit documentation.

### Task 4: Protected review workflow contract

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_bootstrap_approval_record.py`

**Interfaces:**
- Consumes repository-relative actual packet and review declaration paths supplied by manual dispatch.
- Produces artifact `staging-bootstrap-approval-review` containing review JSON/Markdown and approval record JSON.

- [ ] **Step 1:** Add `bootstrap-review` to the manual `approval_phase` choices.
- [ ] **Step 2:** Add `bootstrap_review_path` input and retain the existing `bootstrap_packet_path` input.
- [ ] **Step 3:** Add `bootstrap_review` job behind protected environment `staging-bootstrap-approval` with `contents: read` only.
- [ ] **Step 4:** Ensure the job installs no cloud CLI, requests no `id-token: write`, authenticates to no external system, and runs no mutation command.
- [ ] **Step 5:** Upload only generated review and record artifacts.
- [ ] **Step 6:** Add deterministic synthetic test evidence to the static job without producing or labelling it as an actual approval.
- [ ] **Step 7:** Verify PR-triggered protected jobs remain skipped.
- [ ] **Step 8:** Commit workflow changes.

### Task 5: Fresh verification

- [ ] **Step 1:** Run Python compilation for the new script and tests.
- [ ] **Step 2:** Run the focused approval-record test module.
- [ ] **Step 3:** Run all `scripts/tests/test_*.py` tests.
- [ ] **Step 4:** Run `python3 scripts/validate_staging_config.py`.
- [ ] **Step 5:** Generate deterministic synthetic review evidence and inspect exact-byte digest, derived deferred paths, planner compatibility, and safety flags.
- [ ] **Step 6:** Scan generated outputs for token, credential, password, private key, secret value, Bearer data, mutation commands, and actual operational identifiers.
- [ ] **Step 7:** Verify `Staging configuration`, `CI`, `CodeQL`, `Render Diff`, browser visual, Emulator E2E, and service workflows on the final head.
- [ ] **Step 8:** Confirm PR #1 remains Draft and unmerged.

## Deliberate Stop Boundary

This implementation does not perform lifecycle steps 2–8 with real operational values. It does not create a real `staging-bootstrap` or `staging-bootstrap-approval` environment, generate a real bootstrap packet, name a real approver, or create an actual approved record. The actual record may be generated only after:

1. Concrete staging operating values are confirmed.
2. The local readiness input passes on the then-current commit.
3. `staging-bootstrap` is configured and attested.
4. The actual bootstrap packet is generated from protected environment variables.
5. A human reviews the exact packet artifact and writes an approved review declaration.
6. The generator succeeds and the resulting record is independently verified against the exact packet bytes.

Even an approved bootstrap record authorizes only infrastructure planning. It does not authorize project creation, billing linkage, API activation, IAM changes, resource mutation, live preflight, image publication, or deployment.
