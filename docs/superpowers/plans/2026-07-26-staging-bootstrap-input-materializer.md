# Staging Bootstrap Input Materializer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely turn the repository staging manifest plus explicitly approved, non-secret operating values into a bootstrap-ready manifest, then generate the first pre-provisioning approval packet without creating or changing cloud resources.

**Architecture:** Add one standard-library Python materializer with strict input schema validation, deterministic derivation of staging service-account and Firebase naming fields, sensitive-key rejection, and atomic output. The existing static preflight and bootstrap approval generator consume the materialized manifest. GitHub Actions reads approved values from a `staging-bootstrap` protected environment through GitHub environment variables, never authenticates to GCP in the bootstrap job, and uploads the materialized manifest and approval packet as review artifacts.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, GitHub Actions YAML, existing `staging_preflight.py` and `staging_approval_packet.py`.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Keep PR #1 open and Draft; do not merge it.
- Write and observe failing tests before adding production implementation.
- Do not execute or add cloud resource mutation commands.
- Do not run live preflight, GCP authentication, Firebase authentication, image build/push, deployment, IAM mutation, billing mutation, Secret Manager mutation, Cloud Run mutation, Cloud Tasks mutation, or Firebase mutation.
- Do not create or modify the actual GitHub `staging-bootstrap` environment, reviewers, variables, or secrets; only add the repository workflow contract that references it.
- Do not store secret values, tokens, credentials, passwords, private keys, authorization headers, or service-account key files.
- Keep `operations.cloudMutationApproved=false` in the materialized manifest.
- Keep currency `KRW`; do not convert the approved monthly amount.
- The repository source manifest remains unchanged and placeholder-based.
- The materializer must use only Python standard-library modules and must not invoke subprocesses or cloud CLIs.

---

## File Structure

- Create `scripts/staging_bootstrap_materializer.py`: strict values loading, validation, deterministic manifest materialization, environment-variable adapter, CLI, and atomic output.
- Create `scripts/tests/test_staging_bootstrap_materializer.py`: RED/GREEN unit, CLI, integration, immutability, redaction-boundary, and workflow-contract tests.
- Create `deploy/staging/staging-bootstrap-values.example.json`: non-secret example input schema with documentation-safe values.
- Modify `scripts/staging_approval_packet.py`: permit Cloud Tasks target URLs to remain resource-derived during bootstrap approval.
- Modify `scripts/tests/test_staging_approval_packet_phases.py`: verify the two target URLs are deferred in bootstrap and blocked in deployment.
- Modify `.github/workflows/staging-config-validate.yml`: add protected `staging-bootstrap` environment integration and materializer execution before static preflight and packet generation.
- Modify `.gitignore`: ignore `deploy/staging/staging-bootstrap-values.local.json`.
- Create `docs/runbooks/staging-bootstrap-inputs.md`: operator contract, variable names, local use, workflow use, approval gates, and stop conditions.
- Modify `docs/runbooks/staging-approval-packet.md`: update deferred-path and materialized-manifest flow documentation.

## Values Schema

The materializer accepts exactly this shape:

```json
{
  "schemaVersion": "rhwp.staging-bootstrap-values/v1",
  "project": {
    "id": "rhwp-collaboration-staging-123",
    "billingAccount": "000000-111111-222222",
    "forbiddenProjectIds": ["rhwp-production"]
  },
  "firebase": {
    "storageBucket": "rhwp-collaboration-staging-123.firebasestorage.app"
  },
  "budget": {
    "amountKrw": 50000,
    "notificationChannels": ["billing-admins@example.com"]
  },
  "operations": {
    "dataRetentionDays": 14,
    "approvalReference": "approval-2026-07-26-001",
    "internalFlushSecurityDecision": "mvp-staging-internal-token"
  }
}
```

Unknown keys fail closed. Sensitive key names fail before values are rendered into an error. `cloudMutationApproved`, IAM role changes, runtime changes, queue retry changes, Firebase resource IDs, image digests, rollback revisions, and secret values are not accepted as input fields.

## Deterministic Derivations

For project ID `<project-id>`, the materializer writes:

```text
firebase.authDomain=<project-id>.firebaseapp.com
firebase.authorizedDomains=[<project-id>.firebaseapp.com, <project-id>.web.app]
firebase.hostingSite=<project-id>
cloudRun.collaboration.serviceAccount=rhwp-collaboration-staging@<project-id>.iam.gserviceaccount.com
cloudRun.documentApi.serviceAccount=rhwp-document-api-staging@<project-id>.iam.gserviceaccount.com
cloudRun.documentWorker.serviceAccount=rhwp-document-worker-staging@<project-id>.iam.gserviceaccount.com
tasks.callerServiceAccount=rhwp-tasks-staging@<project-id>.iam.gserviceaccount.com
```

The same values replace matching IAM principal and resource placeholders. `firebase.storageBucket` is supplied explicitly because existing and newly created Firebase projects may use different default bucket suffixes.

The following resource-derived placeholders remain deferred:

```text
project.number
firebase.webAppId
firebase.apiKeyReference
cloudRun.*.image
cloudRun.*.digest
tasks.parse.targetUrl
tasks.export.targetUrl
operations.rollbackRevisionIds[0..2]
```

### Task 1: RED tests for values validation and deterministic materialization

**Files:**
- Create: `scripts/tests/test_staging_bootstrap_materializer.py`
- Read: `deploy/staging/staging-manifest.json`

**Interfaces:**
- Produces required functions:
  - `load_json_object(path: Path, label: str) -> dict[str, Any]`
  - `load_values_from_environment(environ: Mapping[str, str]) -> dict[str, Any]`
  - `validate_bootstrap_values(values: dict[str, Any]) -> None`
  - `materialize_bootstrap_manifest(manifest: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]`
  - `main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int`

- [ ] **Step 1: Add a valid values fixture**

Use the exact schema shown above with a staging-only project ID, explicit storage bucket, positive KRW integer, non-empty notification channels, positive retention days, approval reference, and `mvp-staging-internal-token` decision.

- [ ] **Step 2: Add failing materialization tests**

Assert the output:

```python
self.assertEqual(result["project"]["id"], "rhwp-collaboration-staging-123")
self.assertEqual(result["project"]["billingAccount"], "000000-111111-222222")
self.assertEqual(result["firebase"]["authDomain"], "rhwp-collaboration-staging-123.firebaseapp.com")
self.assertEqual(result["firebase"]["storageBucket"], "rhwp-collaboration-staging-123.firebasestorage.app")
self.assertEqual(result["budget"]["currency"], "KRW")
self.assertEqual(result["budget"]["amount"], 50000)
self.assertFalse(result["operations"]["cloudMutationApproved"])
```

Assert the four service-account emails, IAM placeholder replacement, and default hosting domain derivation.

- [ ] **Step 3: Add failing strict-schema and safety tests**

Tests must reject:

```text
unknown top-level or nested keys
project IDs containing production or prod
project ID equal to a forbidden project ID
invalid billing-account format
empty forbidden project IDs
storage bucket not belonging to the project
zero, negative, boolean, or string KRW amount
empty notification channels
non-positive or boolean retention days
unsupported internal flush decision
cloudMutationApproved override
keys containing token, credential, password, privateKey, authorization, or secretValue
```

Error messages may contain field paths but must not contain rejected sensitive values.

- [ ] **Step 4: Add failing immutability and deferred-value tests**

Assert the input manifest and values objects are unchanged. Assert only the approved resource-derived placeholders remain, including both Cloud Tasks target URLs.

- [ ] **Step 5: Run tests and verify RED**

Run:

```bash
python3 -m unittest scripts.tests.test_staging_bootstrap_materializer -v
```

Expected: import failure because `scripts.staging_bootstrap_materializer` does not exist.

### Task 2: GREEN materializer implementation

**Files:**
- Create: `scripts/staging_bootstrap_materializer.py`
- Test: `scripts/tests/test_staging_bootstrap_materializer.py`

**Interfaces:**
- Consumes the repository manifest and `rhwp.staging-bootstrap-values/v1` values.
- Produces a new `rhwp.staging/v1` dictionary without modifying either input.

- [ ] **Step 1: Implement strict schema helpers**

Implement exact-key checks, non-empty string/list checks, positive integer checks that reject booleans, project and billing format checks, recursive sensitive-key detection, and field-path-only errors.

- [ ] **Step 2: Implement deterministic derivations**

Deep-copy the manifest. Replace project, Firebase planning, service-account, IAM principal/resource, budget, retention, approval reference, and internal-flush values. Preserve all runtime, queue, role, secret metadata, image, Firebase resource, task target URL, and rollback contracts from the source manifest.

- [ ] **Step 3: Validate the materialized result**

Call the existing `scripts.staging_preflight.validate_manifest` after replacement. Reject any non-approved remaining placeholder path. Verify `operations.cloudMutationApproved` remains exactly `false`.

- [ ] **Step 4: Implement atomic CLI output**

Support exactly one source of values:

```text
--values <path>
--from-environment
```

Required common arguments:

```text
--manifest <path>
--output <path>
```

Write to `<output>.tmp` and replace atomically only after all validation succeeds. Print a JSON summary containing project ID, output path, deferred paths, and `mutationCommands=[]`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
python3 -m unittest scripts.tests.test_staging_bootstrap_materializer -v
```

Expected: all materializer tests pass.

### Task 3: RED/GREEN bootstrap generator integration

**Files:**
- Modify: `scripts/staging_approval_packet.py`
- Modify: `scripts/tests/test_staging_approval_packet_phases.py`
- Test: `scripts/tests/test_staging_bootstrap_materializer.py`

**Interfaces:**
- The approval generator continues to use `build_approval_packet(..., phase="bootstrap")`.
- Bootstrap deferred allowlist gains:
  - `manifest.tasks.parse.targetUrl`
  - `manifest.tasks.export.targetUrl`

- [ ] **Step 1: Add failing target-URL phase tests**

Assert bootstrap includes both task target URLs in `deferredValues`. Assert deployment rejects the same placeholders.

- [ ] **Step 2: Add failing end-to-end standard-library integration test**

Materialize the repository manifest into a temporary file, generate a real static preflight report with `build_preflight_report`, then build a bootstrap packet. Assert:

```python
self.assertEqual(packet["phase"], "bootstrap")
self.assertEqual(packet["status"], "ready-for-bootstrap-approval")
self.assertEqual(packet["project"]["id"], values["project"]["id"])
self.assertEqual(packet["budget"]["currency"], "KRW")
self.assertEqual(packet["budget"]["amount"], values["budget"]["amountKrw"])
self.assertEqual(packet["security"]["mutationCommands"], [])
```

- [ ] **Step 3: Implement the two deferred paths and reasons**

Classify task target URLs as values resolved after the first private worker endpoint exists. Do not broaden the allowlist to arbitrary task or IAM paths.

- [ ] **Step 4: Run all staging Python tests**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

Expected: all staging tests pass.

### Task 4: RED/GREEN CLI environment adapter and example values

**Files:**
- Create: `deploy/staging/staging-bootstrap-values.example.json`
- Modify: `.gitignore`
- Test: `scripts/tests/test_staging_bootstrap_materializer.py`

**Interfaces:**
- Environment keys:
  - `STAGING_PROJECT_ID`
  - `STAGING_BILLING_ACCOUNT`
  - `STAGING_FORBIDDEN_PROJECT_IDS_JSON`
  - `STAGING_STORAGE_BUCKET`
  - `STAGING_MONTHLY_BUDGET_KRW`
  - `STAGING_BUDGET_NOTIFICATION_CHANNELS_JSON`
  - `STAGING_DATA_RETENTION_DAYS`
  - `STAGING_APPROVAL_REFERENCE`
  - `STAGING_INTERNAL_FLUSH_DECISION`

- [ ] **Step 1: Add failing environment parsing tests**

Assert valid strings produce the values schema. Assert missing variables, malformed JSON arrays, non-integer KRW/retention values, and extra sensitive variables referenced by the adapter fail without writing an output file.

- [ ] **Step 2: Implement environment parsing**

Parse list fields with `json.loads`; require arrays of non-empty strings. Parse amount and retention with strict decimal integer conversion. Never enumerate or serialize the entire environment.

- [ ] **Step 3: Add example and ignore rule**

Commit only documentation-safe example values. Add this exact ignore rule:

```text
/deploy/staging/staging-bootstrap-values.local.json
```

- [ ] **Step 4: Verify CLI file and environment modes**

Run tests that create outputs in temporary directories and verify failed validation leaves no final or temporary file.

### Task 5: Protected environment workflow integration

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`
- Test: `scripts/tests/test_staging_bootstrap_materializer.py`

**Interfaces:**
- Bootstrap job uses `environment: staging-bootstrap`.
- Bootstrap job reads only GitHub environment `vars.*`; it does not request `id-token: write` and does not use repository/environment secrets.

- [ ] **Step 1: Add failing workflow contract test**

Require these markers:

```text
environment: staging-bootstrap
STAGING_PROJECT_ID: ${{ vars.STAGING_PROJECT_ID }}
STAGING_BILLING_ACCOUNT: ${{ vars.STAGING_BILLING_ACCOUNT }}
python3 scripts/staging_bootstrap_materializer.py
--from-environment
--output artifacts/staging-manifest-bootstrap.json
--manifest artifacts/staging-manifest-bootstrap.json
staging-approval-packet-bootstrap
```

Assert the bootstrap job section contains no `id-token: write`, `google-github-actions/auth`, `setup-gcloud`, `firebase-tools`, direct `gcloud`, direct `firebase`, or mutation verbs.

- [ ] **Step 2: Materialize before static preflight**

The bootstrap job sequence must be:

```text
checkout
materialize bootstrap manifest from environment vars
static preflight on materialized manifest
generate bootstrap approval packet
upload materialized manifest, static report, JSON packet, Markdown packet
```

- [ ] **Step 3: Preserve deployment job isolation**

Keep the existing `staging-preflight` protected environment and WIF read-only live job unchanged except for consuming its existing concrete deployment manifest input.

- [ ] **Step 4: Run workflow contract and full staging tests**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

### Task 6: Runbooks and first packet readiness

**Files:**
- Create: `docs/runbooks/staging-bootstrap-inputs.md`
- Modify: `docs/runbooks/staging-approval-packet.md`

**Interfaces:**
- Documents local values file mode and protected-environment mode.

- [ ] **Step 1: Document operator decisions**

Explain each required value, validation rule, KRW handling, and the fact that values are approval metadata rather than cloud credentials.

- [ ] **Step 2: Document GitHub environment configuration without performing it**

List the required environment name, reviewer protection recommendation, and exact GitHub variables. State that environment creation and value entry are manual external changes requiring explicit operator action.

- [ ] **Step 3: Document first packet command and stop condition**

The first real packet cannot be generated until all nine actual environment values are supplied. Do not substitute guessed project, billing, budget, production project, notification, or approval values.

- [ ] **Step 4: Generate a deterministic test packet only**

Use the test fixture/example values to verify the complete local pipeline. Label it test evidence, not an actual staging approval packet.

### Task 7: Final regression and safety verification

**Files:**
- No new production files.

- [ ] **Step 1: Run Python verification**

```bash
python3 -m py_compile \
  scripts/staging_bootstrap_materializer.py \
  scripts/staging_approval_packet.py \
  scripts/tests/test_staging_bootstrap_materializer.py \
  scripts/tests/test_staging_approval_packet_phases.py

python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

- [ ] **Step 2: Verify GitHub Actions on the final head**

Confirm Staging configuration, CI, CodeQL, Render Diff, Document API, Collaboration server, Firebase rules, Document worker, Collaboration recovery E2E, Collaboration Emulator E2E, Collaboration browser visual, Collaboration WASM bridge, Nested collaboration objects, rhwp-studio collaboration, and rhwp-studio full tests.

- [ ] **Step 3: Verify safety boundary**

Confirm no actual GitHub environment, GitHub variable, WIF, IAM, billing, Secret, Cloud Run, Cloud Tasks, Firebase, or GCP resource was created or changed. Confirm no live preflight or deployment occurred.

- [ ] **Step 4: Verify PR state**

Confirm PR #1 remains open, Draft, unmerged, and targets `devel`.
