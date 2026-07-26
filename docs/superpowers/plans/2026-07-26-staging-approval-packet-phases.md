# Staging Approval Packet Bootstrap and Deployment Phases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Staging Approval Packet Generator into a pre-provisioning `bootstrap` phase and a pre-deployment `deployment` phase so each approval packet requires only values that can exist at that point in the staging lifecycle.

**Architecture:** Keep one standard-library Python CLI and one packet schema, adding a required `phase` discriminator. Bootstrap validation permits only an exact allowlist of deferred resource-derived values while requiring project identity, billing, region, budget, IAM principals, service-account names, queue contracts, retention, and security decisions to be concrete. Deployment validation requires a live read-only preflight report and rejects every unresolved placeholder. GitHub Actions exposes explicit phase selection and never executes cloud mutation commands.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, Markdown, GitHub Actions YAML.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Do not recreate the existing staging manifest, static/live preflight implementation, or approval packet generator from scratch.
- Use RED → GREEN → REFACTOR and observe the new phase tests fail before changing production code.
- Do not execute or add `gcloud`, `firebase`, deployment, IAM, billing, Secret Manager, Cloud Run, Cloud Tasks, image push, or other cloud mutation commands.
- Keep `operations.cloudMutationApproved=false` in both phases.
- Keep PR #1 open and Draft; do not merge it.
- Preserve JSON and Markdown redaction for secret values, tokens, credentials, authorization data, private keys, refresh tokens, passwords, and equivalent fields.
- Preserve the packet schema version `rhwp.staging-approval-packet/v1` and add a top-level `phase` field.
- `bootstrap` may defer only the exact paths defined in `BOOTSTRAP_DEFERRED_PATH_PATTERNS`.
- `deployment` requires a live report and rejects every unresolved placeholder.

---

## File Structure

- Modify `scripts/staging_approval_packet.py`: phase constants, phase-aware validation, deferred-path reporting, phase-aware status, CLI `--phase`, and Markdown headings.
- Modify `scripts/tests/test_staging_approval_packet.py`: bootstrap/deployment validation, packet, CLI, redaction, and workflow contracts.
- Modify `.github/workflows/staging-config-validate.yml`: explicit `approval_phase` input, non-cloud bootstrap job, deployment-only live job, and phase-specific artifacts.
- Modify `docs/runbooks/staging-approval-packet.md`: phase matrix, deferred value policy, commands, workflow usage, and stop conditions.

### Task 1: RED tests for phase input contracts

**Files:**
- Modify: `scripts/tests/test_staging_approval_packet.py`

**Interfaces:**
- Consumes: existing `build_approval_packet`, `main`, `render_markdown`.
- Produces: required API `build_approval_packet(..., phase="bootstrap" | "deployment")` and CLI `--phase` contract.

- [ ] **Step 1: Add a bootstrap fixture with only approved deferred values**

Create `bootstrap_manifest()` from `concrete_manifest()` and replace only these values with placeholders:

```python
manifest["project"]["number"] = "${GCP_PROJECT_NUMBER}"
manifest["firebase"]["webAppId"] = "${FIREBASE_WEB_APP_ID}"
manifest["firebase"]["apiKeyReference"] = "${FIREBASE_WEB_API_KEY_REFERENCE}"
manifest["firebase"]["storageBucket"] = "${FIREBASE_STORAGE_BUCKET}"
manifest["firebase"]["hostingSite"] = "${FIREBASE_HOSTING_SITE}"
for service in manifest["cloudRun"].values():
    service["image"] = "${SERVICE_IMAGE}"
    service["digest"] = "${SERVICE_IMAGE_DIGEST}"
manifest["operations"]["rollbackRevisionIds"] = [
    "${COLLABORATION_ROLLBACK_REVISION}",
    "${DOCUMENT_API_ROLLBACK_REVISION}",
    "${DOCUMENT_WORKER_ROLLBACK_REVISION}",
]
```

- [ ] **Step 2: Add failing bootstrap tests**

Tests must assert:

```python
packet = build_approval_packet(
    manifest,
    static_report(manifest),
    phase="bootstrap",
)
self.assertEqual(packet["phase"], "bootstrap")
self.assertEqual(packet["status"], "ready-for-bootstrap-approval")
self.assertGreater(len(packet["deferredValues"]), 0)
```

Also assert bootstrap rejects placeholders in `project.id`, `project.billingAccount`, `budget.amount`, `budget.notificationChannels`, `operations.approvalReference`, and IAM principal/resource fields. Assert bootstrap rejects a supplied live report because live evidence belongs to deployment review.

- [ ] **Step 3: Add failing deployment tests**

Tests must assert deployment rejects any unresolved placeholder, requires a live report, and produces:

```python
self.assertEqual(packet["phase"], "deployment")
self.assertEqual(packet["status"], "ready-for-deployment-approval")
self.assertEqual(packet["deferredValues"], [])
```

- [ ] **Step 4: Add failing CLI and Markdown tests**

Require `--phase bootstrap|deployment`, verify the phase is printed in CLI JSON, and verify Markdown includes the phase and a deferred-values section only for bootstrap.

- [ ] **Step 5: Run tests and verify RED**

Run:

```bash
python3 -m unittest scripts.tests.test_staging_approval_packet -v
```

Expected: failures because `build_approval_packet` does not accept `phase`, the CLI has no `--phase`, and packets have no `phase` or `deferredValues` fields.

### Task 2: GREEN phase-aware validator and packet model

**Files:**
- Modify: `scripts/staging_approval_packet.py`
- Test: `scripts/tests/test_staging_approval_packet.py`

**Interfaces:**
- Produces:
  - `ApprovalPhase = Literal["bootstrap", "deployment"]`
  - `validate_approval_inputs(manifest, static_report, live_report=None, *, phase)`
  - `build_approval_packet(manifest, static_report, live_report=None, *, phase)`
  - `_classify_placeholders(manifest, phase) -> tuple[list[str], list[str]]`

- [ ] **Step 1: Add phase constants and exact deferred path patterns**

The bootstrap allowlist must cover only:

```text
manifest.project.number
manifest.firebase.webAppId
manifest.firebase.apiKeyReference
manifest.firebase.storageBucket
manifest.firebase.hostingSite
manifest.cloudRun.collaboration.image
manifest.cloudRun.collaboration.digest
manifest.cloudRun.documentApi.image
manifest.cloudRun.documentApi.digest
manifest.cloudRun.documentWorker.image
manifest.cloudRun.documentWorker.digest
manifest.operations.rollbackRevisionIds[0]
manifest.operations.rollbackRevisionIds[1]
manifest.operations.rollbackRevisionIds[2]
```

All other placeholder paths are blocking in both phases.

- [ ] **Step 2: Implement phase validation**

Bootstrap rules:

```text
static report required and passing
static cloudQueries must be empty
live report must be absent
only allowlisted deferred placeholders permitted
```

Deployment rules:

```text
static report required and passing
live report required with status pass or review
all placeholders forbidden
```

Both phases require matching project IDs and `mutationCommands=[]` in every report.

- [ ] **Step 3: Add phase-aware packet fields**

Add:

```json
{
  "phase": "bootstrap",
  "status": "ready-for-bootstrap-approval",
  "deferredValues": [
    {"path": "manifest.firebase.webAppId", "reason": "resolved after Firebase resource creation"}
  ]
}
```

Deployment uses `ready-for-deployment-approval` when live status is `pass`, otherwise `review-required`, and always has an empty `deferredValues` array.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python3 -m unittest scripts.tests.test_staging_approval_packet -v
```

Expected: all approval packet tests pass.

### Task 3: GREEN CLI, Markdown, and workflow phase routing

**Files:**
- Modify: `scripts/staging_approval_packet.py`
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_approval_packet.py`

**Interfaces:**
- CLI: `--phase bootstrap|deployment` is required.
- Workflow input: `approval_phase` choices `none`, `bootstrap`, `deployment`.

- [ ] **Step 1: Add CLI phase argument**

Pass `args.phase` into packet generation and include `phase` in the success JSON printed to stdout.

- [ ] **Step 2: Render phase-aware Markdown**

Use `# rhwp Staging Bootstrap Approval Packet` or `# rhwp Staging Deployment Approval Packet`. Include `- Phase: ...` in metadata. For bootstrap, render `## Deferred values`; for deployment, omit that section.

- [ ] **Step 3: Add workflow dispatch phase selection**

Add `approval_phase` as a choice input with `none`, `bootstrap`, and `deployment`. Validate combinations:

```text
bootstrap requires live_check=false
deployment requires live_check=true
none requires live_check=false
```

Add a `Bootstrap approval packet` job that runs only repository checkout, static preflight, `--phase bootstrap`, and artifact upload. It must not authenticate to GCP or install cloud CLIs.

Keep the existing protected live job for deployment, change its condition to deployment phase plus `live_check=true`, call `--phase deployment`, and upload `staging-approval-packet-deployment`.

- [ ] **Step 4: Run workflow contract tests**

```bash
python3 -m unittest scripts.tests.test_staging_approval_packet -v
```

Expected: phase CLI and workflow markers pass; no mutation command pattern is present.

### Task 4: Runbook and full regression verification

**Files:**
- Modify: `docs/runbooks/staging-approval-packet.md`

**Interfaces:**
- Documents exact input gates and artifact names for both phases.

- [ ] **Step 1: Document phase matrix**

Document bootstrap as pre-provisioning and deployment as post-live-preflight/pre-deployment. List the exact bootstrap deferred paths and state that additional placeholders fail closed.

- [ ] **Step 2: Document commands and artifacts**

Commands:

```bash
python3 scripts/staging_approval_packet.py --phase bootstrap ...
python3 scripts/staging_approval_packet.py --phase deployment --live-report ...
```

Artifacts:

```text
staging-approval-packet-bootstrap
staging-approval-packet-deployment
```

- [ ] **Step 3: Run local standard-library checks**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 -m py_compile scripts/staging_approval_packet.py scripts/tests/test_staging_approval_packet.py
python3 scripts/validate_staging_config.py
```

- [ ] **Step 4: Verify pull-request workflows**

Confirm the current head succeeds for Staging configuration, CI, CodeQL, Document API, Collaboration server, Firebase rules, Document worker, Collaboration recovery E2E, Collaboration Emulator E2E, Collaboration browser visual, Render Diff, Collaboration WASM bridge, Nested collaboration objects, rhwp-studio collaboration, and rhwp-studio full tests.

- [ ] **Step 5: Verify safety boundary**

Confirm PR #1 remains Draft and unmerged. Confirm no live preflight, cloud authentication, cloud resource mutation, image build/push, or staging deployment was performed as part of this implementation.
