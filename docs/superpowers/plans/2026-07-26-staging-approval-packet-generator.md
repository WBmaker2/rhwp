# Staging Approval Packet Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate deterministic JSON and Markdown approval packets from the concrete staging manifest plus static and optional live read-only preflight reports, without executing cloud commands or mutating any cloud resource.

**Architecture:** Add a standalone Python standard-library CLI that loads and validates repository-owned JSON inputs, rejects every unresolved `${PLACEHOLDER}`, derives a review-focused packet, recursively redacts sensitive values, and renders Markdown only from the sanitized packet. Keep the existing preflight validator unchanged. Run packet generation only in the manually approved live preflight job, where both static and live reports can be generated in the same job without passing mutable state between jobs.

**Tech Stack:** Python 3 standard library, `unittest`, JSON, GitHub Actions YAML.

## Global Constraints

- Work only on `WBmaker2/rhwp` branch `feat/firebase-collaboration-mvp-v1`.
- Do not reimplement `deploy/staging/staging-manifest.json`, `scripts/staging_preflight.py`, or existing preflight workflow behavior.
- Do not execute `gcloud`, `firebase`, deployment, IAM, billing, Secret Manager, Cloud Run, Cloud Tasks, or other cloud mutation commands.
- Keep `operations.cloudMutationApproved=false`.
- Redact secret values, tokens, credentials, authorization headers, private keys, passwords, and equivalent sensitive fields from JSON, Markdown, logs, and error output.
- Reject unresolved `${PLACEHOLDER}` values, including placeholders embedded inside larger strings.
- Keep PR #1 in Draft state and do not merge it.
- Use RED → GREEN → REFACTOR for every production behavior.

---

## File Structure

- Create `scripts/staging_approval_packet.py`: input validation, packet derivation, IAM comparison, redaction, Markdown rendering, CLI, and failure handling.
- Create `scripts/tests/test_staging_approval_packet.py`: unit and CLI contract tests with concrete temporary fixtures.
- Create `docs/runbooks/staging-approval-packet.md`: operator-facing input, output, security, and workflow instructions.
- Modify `.github/workflows/staging-config-validate.yml`: in the approved live job, regenerate the static report, run live preflight, generate JSON/Markdown packets, and upload all outputs.

### Task 1: Input contracts and placeholder rejection

**Files:**
- Create: `scripts/tests/test_staging_approval_packet.py`
- Create: `scripts/staging_approval_packet.py`

**Interfaces:**
- Produces: `ApprovalPacketError`, `load_json_object(path: Path, label: str) -> dict[str, Any]`, `validate_approval_inputs(manifest, static_report, live_report=None) -> None`.
- Consumes: manifest schema `rhwp.staging/v1` and preflight report schema `rhwp.preflight-report/v1`.

- [ ] **Step 1: Write failing tests for concrete input acceptance and placeholder rejection**

```python
class ApprovalInputValidationTest(unittest.TestCase):
    def test_rejects_embedded_placeholder_before_packet_generation(self) -> None:
        manifest = concrete_manifest()
        manifest["firebase"]["authDomain"] = "${FIREBASE_STAGING_PROJECT_ID}.firebaseapp.com"
        with self.assertRaisesRegex(ApprovalPacketError, "unresolved placeholder"):
            build_approval_packet(manifest, static_report(manifest), None)

    def test_rejects_non_pass_static_report_or_mutation_commands(self) -> None:
        manifest = concrete_manifest()
        report = static_report(manifest)
        report["mutationCommands"] = ["gcloud run deploy forbidden"]
        with self.assertRaisesRegex(ApprovalPacketError, "mutationCommands"):
            build_approval_packet(manifest, report, None)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest scripts.tests.test_staging_approval_packet.ApprovalInputValidationTest -v
```

Expected: import failure because `scripts.staging_approval_packet` does not exist.

- [ ] **Step 3: Implement minimal JSON loading and validation**

Validation must enforce:

```text
manifest.schemaVersion == rhwp.staging/v1
manifest.environment == staging
manifest.operations.cloudMutationApproved == false
no string anywhere in manifest contains ${[A-Z0-9_]+}
static report schema == rhwp.preflight-report/v1
static report mode == static
static report status == pass
static report projectId == manifest.project.id
static report cloudQueries == []
static report mutationCommands == []
live report, when present, uses mode live, status pass or review,
projectId matches, and mutationCommands == []
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same unittest command and expect all tests to pass.

### Task 2: Deterministic JSON packet and IAM diff

**Files:**
- Modify: `scripts/tests/test_staging_approval_packet.py`
- Modify: `scripts/staging_approval_packet.py`

**Interfaces:**
- Produces: `build_approval_packet(manifest, static_report, live_report=None) -> dict[str, Any]`.
- Packet schema: `rhwp.staging-approval-packet/v1`.

- [ ] **Step 1: Write failing tests for required packet sections**

Assert exact sections:

```text
approval
project
firebase
budget
iamDiff
secrets
cloudRun
cloudTasks
internalFlush
rollback
acceptanceTests
preflight
security
```

Assert that Cloud Run entries include ingress and derived reachability, Cloud Tasks include retry/rate/deadline, and budget currency remains `KRW` without conversion.

- [ ] **Step 2: Write failing tests for conservative IAM comparison**

Given live `cloudState.iamPolicy.bindings`, project-level expected bindings become `present` or `missing`. Resource-level bindings that the existing preflight does not query become `not-observed`, with `plannedAction=verify-before-grant` rather than being claimed missing.

- [ ] **Step 3: Run focused tests and verify RED**

Expected: missing packet fields and IAM comparison behavior.

- [ ] **Step 4: Implement minimal packet derivation**

Required derivations:

```text
public reachability:
  ingress=all -> internet-reachable-application-auth-required
  ingress=internal -> internal-only

IAM diff:
  project binding present -> state=present, plannedAction=none
  project binding absent -> state=missing, plannedAction=grant-after-approval
  non-project binding -> state=not-observed, plannedAction=verify-before-grant

acceptance tests:
  Google sign-in and ACL
  HWP upload within 200 MiB contract
  parse worker completion
  share-link acceptance by a second account
  two-browser concurrent editing
  WebSocket reconnect and state convergence
  collaboration restart and snapshot recovery
  HWPX export
  exported HWPX re-import
  edited content and readonly complex-object preservation
  rollback revision readiness
```

- [ ] **Step 5: Run focused tests and verify GREEN**

### Task 3: Redaction and Markdown rendering

**Files:**
- Modify: `scripts/tests/test_staging_approval_packet.py`
- Modify: `scripts/staging_approval_packet.py`

**Interfaces:**
- Produces: `redact_sensitive(value: Any) -> Any`, `render_markdown(packet: dict[str, Any]) -> str`.

- [ ] **Step 1: Write failing redaction tests**

Inject values under keys such as `accessToken`, `id_token`, `authorization`, `credential`, `privateKey`, `secretValue`, and `password`. Assert neither JSON serialization nor Markdown contains the original values and that each is replaced by `[REDACTED]`.

- [ ] **Step 2: Write failing Markdown structure tests**

Require headings for Project, Budget, IAM diff, Secret metadata, Cloud Run, Cloud Tasks, Internal flush security, Rollback, Acceptance tests, and Preflight evidence. Require an explicit statement that the packet contains no cloud mutation commands and is not deployment approval by itself.

- [ ] **Step 3: Run focused tests and verify RED**

- [ ] **Step 4: Implement recursive redaction and render Markdown only from the sanitized packet**

Markdown must not read raw manifest or report objects. It must consume the final redacted packet, use stable ordering, and format budget as an integer plus `KRW` without currency conversion.

- [ ] **Step 5: Run focused tests and verify GREEN**

### Task 4: CLI, file outputs, and failure artifacts

**Files:**
- Modify: `scripts/tests/test_staging_approval_packet.py`
- Modify: `scripts/staging_approval_packet.py`

**Interfaces:**
- CLI arguments:

```text
--manifest PATH
--static-report PATH
--live-report PATH        optional
--json-output PATH
--markdown-output PATH
```

- [ ] **Step 1: Write failing CLI test**

Use a temporary directory and concrete fixtures. Run `main([...])`; assert return code 0, JSON and Markdown files exist, JSON parses, and stdout contains only a compact non-sensitive status summary.

- [ ] **Step 2: Write failing placeholder CLI test**

Use the repository placeholder manifest and assert return code 1, neither successful packet is written, and stderr contains only placeholder paths—not resolved or secret values.

- [ ] **Step 3: Run CLI tests and verify RED**

- [ ] **Step 4: Implement atomic output writes and safe errors**

Write each file through a sibling temporary file and replace the target only after successful serialization. Create parent directories. On error, return 1 and print `staging approval packet failed: <safe message>`.

- [ ] **Step 5: Run the complete packet test module and verify GREEN**

```bash
python3 -m unittest scripts.tests.test_staging_approval_packet -v
```

### Task 5: GitHub Actions integration

**Files:**
- Modify: `scripts/tests/test_staging_approval_packet.py`
- Modify: `.github/workflows/staging-config-validate.yml`

**Interfaces:**
- Live job outputs:

```text
artifacts/staging-preflight-static.json
artifacts/staging-preflight-live.json
artifacts/staging-approval-packet.json
artifacts/staging-approval-packet.md
```

- [ ] **Step 1: Write failing workflow contract test**

Assert that the live job:

```text
regenerates a static report locally
runs the existing live preflight
runs scripts/staging_approval_packet.py with both reports
uploads both packet formats
contains no direct gcloud/firebase mutation command
```

- [ ] **Step 2: Run workflow test and verify RED**

- [ ] **Step 3: Update the live job**

Do not generate a packet in pull-request static execution because the repository manifest intentionally contains unresolved placeholders. Packet generation runs only after `workflow_dispatch` with `live_check=true`, protected environment approval, WIF authentication, a concrete manifest, and successful static/live preflight generation.

- [ ] **Step 4: Run all Python tests and verify GREEN**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

### Task 6: Operator runbook and full regression verification

**Files:**
- Create: `docs/runbooks/staging-approval-packet.md`

- [ ] **Step 1: Document prerequisites and safe invocation**

Document input schemas, placeholder failure, redaction, output contents, workflow behavior, and the rule that packet generation is read-only and does not itself approve deployment.

- [ ] **Step 2: Run repository formatting and targeted service tests available locally**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

- [ ] **Step 3: Verify GitHub Actions regression**

After branch updates, confirm the existing PR workflows remain successful, including CI, CodeQL, Staging configuration, Document API, Collaboration server, Firebase rules, Collaboration WASM bridge, Nested collaboration objects, collaboration recovery E2E, emulator E2E, browser visual, Render Diff, document worker, and rhwp-studio tests.

- [ ] **Step 4: Preserve PR state**

Verify PR #1 remains open, Draft, unmerged, and targets `devel`.
