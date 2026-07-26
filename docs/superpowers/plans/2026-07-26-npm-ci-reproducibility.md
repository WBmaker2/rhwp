# Collaboration CI npm Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Convert the remaining collaboration CI package installations from `npm install` to deterministic `npm ci`, including creating and validating the missing `services/document-worker/package-lock.json`.

**Architecture:** Each Node package owns an npm v3 lockfile generated under Node.js 22. GitHub Actions uses the committed lockfiles for both `npm ci` and npm cache keys. A temporary branch-local workflow generated and verified the missing document-worker lockfile, then was removed.

**Tech Stack:** GitHub Actions, Node.js 22, npm lockfileVersion 3, TypeScript, Firebase Emulator Suite, Rust collaboration worker

## Global Constraints

- Work only on `feat/firebase-collaboration-mvp-v1` targeting Draft PR #1.
- Do not merge, deploy, remove Draft status, or create/change Firebase or GCP resources.
- Preserve `--ignore-scripts --no-audit --no-fund` on deterministic dependency installation steps.
- Keep collaboration behavior unchanged; this task changes dependency reproducibility and CI configuration only.

## Baseline

- [x] Confirmed every workflow on head `1f6de8ac761af9ea5ad976414435efb273685875`, including `CI` and `CodeQL`, completed successfully before implementation.
- [x] Confirmed `services/e2e/package.json` and `services/e2e/package-lock.json` contain the same direct dependency versions.
- [x] Confirmed `services/document-worker/package-lock.json` was absent.
- [x] Confirmed the remaining nondeterministic installs were:
  - `.github/workflows/collaboration-e2e.yml` → `services/e2e`
  - `.github/workflows/collaboration-emulator-e2e.yml` → `services/document-worker`

---

## Task 1: Create and verify the document-worker lockfile

**Files:**
- Created: `services/document-worker/package-lock.json`
- Created then deleted: `.github/workflows/document-worker-lockfile-sync.yml`

- [x] Added a temporary workflow using Node.js 22.
- [x] Generated the lockfile with:

```bash
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
```

- [x] Verified a clean deterministic install with:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

- [x] Ran `npm test` successfully.
- [x] Ran `npm run build` successfully.
- [x] Corrected the temporary workflow to detect a newly generated untracked lockfile with `git status --porcelain`.
- [x] Committed the generated lockfile.
- [x] Verified the committed root metadata:

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

## Task 2: Convert Collaboration recovery E2E to npm ci

**File:** `.github/workflows/collaboration-e2e.yml`

- [x] Upgraded the workflow setup step to `actions/setup-node@v6` with Node.js 22.
- [x] Enabled npm caching with:

```yaml
cache-dependency-path: |
  firebase/package-lock.json
  services/collaboration-server/package-lock.json
  services/e2e/package-lock.json
```

- [x] Replaced the `services/e2e` install command with:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

- [x] Verified the recovery E2E workflow on code head `41a25ec163548d1092e2cb911b53b04bda334683`.
  - Workflow run: `30188907035`
  - Conclusion: `success`
  - Firebase authorization rules: success
  - Collaboration server install: success
  - Process-level recovery flow: success
  - Three Rust collaboration/export tests: success

---

## Task 3: Convert Emulator E2E document-worker installation to npm ci

**File:** `.github/workflows/collaboration-emulator-e2e.yml`

- [x] Added `services/document-worker/package-lock.json` to `cache-dependency-path`.
- [x] Replaced the document-worker install command with:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

- [x] Verified the Emulator E2E workflow on code head `41a25ec163548d1092e2cb911b53b04bda334683`.
  - Workflow run: `30188907012`
  - Conclusion: `success`
  - Firebase, collaboration server, Document API, document worker, and E2E installs: success
  - Rust formatting and native worker build: success
  - Deterministic HWPX fixture generation: success
  - Real Firebase Emulator multi-process flow: success

---

## Task 4: Verify document-worker package gates

- [x] Verified the `Document worker` workflow on code head `41a25ec163548d1092e2cb911b53b04bda334683`.
  - Workflow run: `30188907056`
  - Node worker job: success
  - Native worker job: success

---

## Task 5: Final cleanup

- [x] Deleted `.github/workflows/document-worker-lockfile-sync.yml` after the lockfile was committed.
- [x] Confirmed `.github/workflows/collaboration-e2e.yml` installs `services/e2e` with `npm ci`.
- [x] Confirmed `.github/workflows/collaboration-emulator-e2e.yml` installs `services/document-worker` with `npm ci`.
- [x] Confirmed the document-worker lockfile participates in npm cache calculation.
- [x] Preserved Draft PR status and avoided merge, deployment, and GCP/Firebase resource changes.
- [x] Recorded the final documentation-head workflow state in Draft PR #1.

## Final Verification

Final verified head: `07a7243cdc68349efe333c3fd240258f689f0b64`.

- [x] `CI` run `30190262464`: success
- [x] `CodeQL` run `30190262429`: success
- [x] `Collaboration recovery E2E` run `30190262444`: success
- [x] `Collaboration Emulator E2E` run `30190262455`: success
- [x] `Document worker` run `30190262428`: success
- [x] `Collaboration browser visual` run `30190262486`: success
- [x] `Render Diff` run `30190262427`: success
- [x] All remaining workflows associated with the head completed successfully.

## Resulting Permanent Files

- `services/document-worker/package-lock.json`
- `.github/workflows/collaboration-e2e.yml`
- `.github/workflows/collaboration-emulator-e2e.yml`
- `docs/superpowers/plans/2026-07-26-npm-ci-reproducibility.md`

## Remaining Roadmap

1. Finalize staging architecture and deployment runbook.
2. Implement the staging preflight validator.
3. Obtain explicit approval before creating or changing cloud resources.
4. Create and deploy staging resources only after approval.
5. Run staging acceptance tests.
6. Decide whether to remove Draft status and merge.
