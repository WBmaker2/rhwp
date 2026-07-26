# Collaboration CI npm Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the remaining collaboration CI package installations from `npm install` to deterministic `npm ci`, including creating and validating the missing `services/document-worker/package-lock.json`.

**Architecture:** Keep each Node package independently reproducible with its own npm v3 lockfile generated under Node 22. GitHub Actions must use each package's committed lockfile for both `npm ci` installation and npm cache key calculation. Use a temporary, branch-local workflow only to generate and verify the missing lockfile; remove that workflow after the lockfile is committed.

**Tech Stack:** GitHub Actions, Node.js 22, npm lockfileVersion 3, TypeScript, Firebase Emulator Suite, Rust collaboration worker

## Global Constraints

- Work only on `feat/firebase-collaboration-mvp-v1` targeting Draft PR #1.
- Do not merge, deploy, remove Draft status, or create/change Firebase or GCP resources.
- Preserve `--ignore-scripts --no-audit --no-fund` on deterministic dependency installation steps.
- Generate lockfiles with Node.js 22 and verify them using a clean `npm ci` in GitHub Actions.
- Keep the current collaboration behavior unchanged; this task changes dependency reproducibility and CI configuration only.
- Record the baseline that all workflows on head `1f6de8ac761af9ea5ad976414435efb273685875`, including `CI` and `CodeQL`, completed successfully before this implementation.

---

## File Structure

- Create: `services/document-worker/package-lock.json` — exact direct and transitive dependency graph for the document worker.
- Modify: `.github/workflows/collaboration-e2e.yml` — install `services/e2e` with `npm ci` and cache its lockfile.
- Modify: `.github/workflows/collaboration-emulator-e2e.yml` — install `services/document-worker` with `npm ci` and cache its lockfile.
- Create then delete: `.github/workflows/document-worker-lockfile-sync.yml` — one-time Node 22 lockfile generation and verification workflow.
- Modify: `docs/superpowers/plans/2026-07-26-npm-ci-reproducibility.md` — check off completed tasks and record final verification evidence.

---

### Task 1: Capture the baseline and validate package manifests

**Files:**
- Inspect: `services/e2e/package.json`
- Inspect: `services/e2e/package-lock.json`
- Inspect: `services/document-worker/package.json`
- Inspect: `services/document-worker/package-lock.json`
- Inspect: `.github/workflows/collaboration-e2e.yml`
- Inspect: `.github/workflows/collaboration-emulator-e2e.yml`

**Interfaces:**
- Consumes: PR head workflow results and the committed package manifests.
- Produces: An exact list of missing or mismatched lockfiles and remaining `npm install` commands.

- [ ] **Step 1: Verify the baseline workflow state**

Check GitHub Actions for head `1f6de8ac761af9ea5ad976414435efb273685875`.

Expected: `CI`, `CodeQL`, `Collaboration recovery E2E`, `Collaboration Emulator E2E`, `Collaboration browser visual`, `Document worker`, and the remaining listed workflows are `completed/success`.

- [ ] **Step 2: Compare E2E manifest and lockfile roots**

Expected root dependencies in both files:

```json
{
  "@hocuspocus/provider": "4.4.0",
  "firebase-admin": "14.2.0",
  "puppeteer-core": "25.3.0",
  "yjs": "13.6.31"
}
```

- [ ] **Step 3: Confirm the document worker lockfile gap**

Expected: `services/document-worker/package.json` declares `firebase-admin`, `yjs`, `@types/node`, `tsx`, and `typescript`, while `services/document-worker/package-lock.json` is absent.

- [ ] **Step 4: Confirm the remaining nondeterministic installs**

Expected matches:

```yaml
# .github/workflows/collaboration-e2e.yml
npm install --ignore-scripts --no-audit --no-fund

# .github/workflows/collaboration-emulator-e2e.yml
npm install --ignore-scripts --no-audit --no-fund
```

---

### Task 2: Generate and verify the document worker lockfile

**Files:**
- Create: `.github/workflows/document-worker-lockfile-sync.yml`
- Create: `services/document-worker/package-lock.json`

**Interfaces:**
- Consumes: `services/document-worker/package.json` under Node.js 22.
- Produces: npm lockfileVersion 3 with exact direct and transitive dependencies, verified by `npm ci`.

- [ ] **Step 1: Add a temporary lockfile generation workflow**

The workflow must:

```yaml
name: Document worker lockfile sync

on:
  pull_request:
    branches: [devel]
    paths:
      - 'services/document-worker/package.json'
      - 'services/document-worker/package-lock.json'
      - '.github/workflows/document-worker-lockfile-sync.yml'

permissions:
  contents: write
```

It must check out `${{ github.head_ref }}`, use Node 22, run the following commands in `services/document-worker`, and commit only the generated lockfile:

```bash
rm -f package-lock.json
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run build
```

- [ ] **Step 2: Run the temporary workflow**

Expected: lockfile generation, clean `npm ci`, document-worker tests, and TypeScript build all complete successfully.

- [ ] **Step 3: Verify the committed lockfile root**

Expected root metadata:

```json
{
  "name": "@rhwp/document-worker",
  "version": "0.1.0",
  "lockfileVersion": 3,
  "dependencies": {
    "firebase-admin": "14.2.0",
    "yjs": "13.6.31"
  },
  "devDependencies": {
    "@types/node": "26.1.1",
    "tsx": "4.23.1",
    "typescript": "7.0.2"
  }
}
```

---

### Task 3: Convert the recovery E2E workflow to npm ci

**Files:**
- Modify: `.github/workflows/collaboration-e2e.yml`

**Interfaces:**
- Consumes: Valid `services/e2e/package-lock.json`.
- Produces: Recovery E2E installation that fails on manifest/lockfile drift instead of modifying dependency state.

- [ ] **Step 1: Enable npm caching with exact lockfile inputs**

Change the setup-node step to:

```yaml
- uses: actions/setup-node@v6
  with:
    node-version: 22
    cache: npm
    cache-dependency-path: |
      firebase/package-lock.json
      services/collaboration-server/package-lock.json
      services/e2e/package-lock.json
```

- [ ] **Step 2: Replace the E2E install command**

Change:

```bash
npm install --ignore-scripts --no-audit --no-fund
```

To:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

- [ ] **Step 3: Verify the workflow**

Expected: dependency installation succeeds, `npm test` succeeds, and the three Rust collaboration tests succeed.

---

### Task 4: Convert the Emulator E2E document worker installation to npm ci

**Files:**
- Modify: `.github/workflows/collaboration-emulator-e2e.yml`

**Interfaces:**
- Consumes: Valid `services/document-worker/package-lock.json`.
- Produces: Emulator E2E installation and npm caching tied to the document-worker lockfile.

- [ ] **Step 1: Add the document-worker lockfile to cache inputs**

Add this line to `cache-dependency-path`:

```yaml
services/document-worker/package-lock.json
```

- [ ] **Step 2: Replace the document worker install command**

Change:

```bash
npm install --ignore-scripts --no-audit --no-fund
```

To:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

- [ ] **Step 3: Verify the workflow**

Expected: all dependency installation steps succeed, the native collaboration worker builds, the deterministic HWPX fixture is generated, and the actual Firebase Emulator multi-process flow succeeds.

---

### Task 5: Remove temporary automation and complete verification

**Files:**
- Delete: `.github/workflows/document-worker-lockfile-sync.yml`
- Modify: `docs/superpowers/plans/2026-07-26-npm-ci-reproducibility.md`
- Modify: PR #1 description

**Interfaces:**
- Consumes: Successful lockfile generation and final workflow runs.
- Produces: A branch containing only permanent lockfile/workflow/documentation changes, with completion evidence recorded.

- [ ] **Step 1: Delete the temporary lockfile workflow**

Expected: `.github/workflows/document-worker-lockfile-sync.yml` is absent from the final head.

- [ ] **Step 2: Check for remaining targeted installs**

The following workflow/package pairs must contain no `npm install`:

```text
.github/workflows/collaboration-e2e.yml → services/e2e
.github/workflows/collaboration-emulator-e2e.yml → services/document-worker
```

- [ ] **Step 3: Verify final workflow results**

Required successful workflows on the final head:

```text
Collaboration recovery E2E
Collaboration Emulator E2E
Document worker
```

Also record the status of `CI` and `CodeQL`; do not claim they succeeded until their final-head runs complete successfully.

- [ ] **Step 4: Update this plan with completion evidence**

Check every completed step and append the final head SHA and workflow run conclusions.

- [ ] **Step 5: Update Draft PR #1**

Move this item to completed work and leave only staging design, explicit deployment approval, staging deployment, staging acceptance testing, and Draft/merge decision as future stages.
