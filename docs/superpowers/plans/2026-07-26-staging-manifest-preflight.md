# Staging Manifest and Read-only Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cloud Tasks HTTP task에 `dispatchDeadline=900s`를 명시하고, staging architecture를 JSON manifest로 고정하며, 실제 클라우드 리소스를 변경하지 않는 정적·live read-only preflight validator와 수동 GitHub Actions 실행 경로를 구현한다.

**Architecture:** `deploy/staging/staging-manifest.json`을 staging 계약의 machine-readable source of truth로 추가한다. Python validator는 manifest와 repository template의 정합성을 항상 검사하고, `--live`일 때만 허용된 `gcloud`/`firebase` 조회 명령을 실행해 실제 project 상태를 JSON report로 출력한다. GitHub Actions의 `workflow_dispatch`는 기본적으로 static 검증만 수행하며, live 검증은 Workload Identity Federation용 repository secret이 구성되고 사용자가 명시적으로 선택한 경우에만 수행한다.

**Tech Stack:** TypeScript, Node.js 22 test runner, Google Cloud Tasks v2 client, Python 3 standard library, JSON, GitHub Actions, Google Workload Identity Federation

## Global Constraints

- 저장소: `WBmaker2/rhwp`
- 작업 브랜치: `feat/firebase-collaboration-mvp-v1`
- 대상 PR: Draft PR `#1`, base `devel`
- PR을 merge하거나 Draft 상태를 해제하지 않는다.
- Firebase/GCP project, billing, API, IAM, Secret Manager, Cloud Tasks, Cloud Run, Firebase Hosting·Rules 리소스를 생성·변경·배포하지 않는다.
- 기본 리전은 `asia-northeast3`으로 유지한다.
- Cloud Tasks HTTP task dispatch deadline은 `900`초로 고정한다.
- 파일 업로드 계약 `0 < 파일 크기 ≤ 200 MiB`와 사용자 이미지 최대 `20 MiB`를 유지한다.
- secret 원문, service-account key JSON, Firebase Admin credential을 저장소·workflow input·artifact에 기록하지 않는다.
- live preflight는 create, update, delete, set-iam-policy, add-iam-policy-binding, deploy, enable, disable 명령을 실행하지 않는다.
- 모든 production code 변경은 RED → GREEN 순서로 검증한다.

---

### Task 1: Cloud Tasks dispatch deadline 계약

**Files:**
- Modify: `services/document-api/tests/firebase-adapters.test.ts`
- Modify: `services/document-api/tests/firebase-environment.test.ts`
- Modify: `services/document-api/src/firebase-adapters.ts`
- Modify: `services/document-api/src/runtime-environment.ts`
- Modify: `deploy/cloudrun/document-api.service.yaml`
- Modify: `firebase/staging.env.example`

**Interfaces:**
- Consumes: `TaskQueueConfiguration`, `CloudTasksJobQueue.enqueue()`, `readDocumentApiEnvironment()`, `readDocumentApiRuntimeEnvironment()`
- Produces: `TaskQueueConfiguration.dispatchDeadlineSeconds: number` and Cloud Tasks `task.dispatchDeadline = { seconds: 900 }`

- [ ] **Step 1: dispatch deadline failing tests를 작성한다**

`CloudTasksJobQueue` 테스트에서 `createTask` 입력의 다음 값을 검증한다.

```ts
assert.deepEqual(call.task.dispatchDeadline, { seconds: 900 })
```

환경 테스트에서는 기본값과 범위를 검증한다.

```ts
assert.equal(configuration.parseQueue.dispatchDeadlineSeconds, 900)
assert.throws(
  () => readDocumentApiRuntimeEnvironment({
    ...validEnvironment,
    TASK_DISPATCH_DEADLINE_SECONDS: '1801',
  }),
  /TASK_DISPATCH_DEADLINE_SECONDS/,
)
```

- [ ] **Step 2: RED를 확인한다**

Run: `cd services/document-api && npm test`

Expected: `dispatchDeadline` 또는 `dispatchDeadlineSeconds`가 없어 관련 assertion이 실패한다.

- [ ] **Step 3: 최소 구현을 추가한다**

```ts
export interface TaskQueueConfiguration {
  projectId: string
  location: string
  queue: string
  targetUrl: string
  serviceAccountEmail: string
  dispatchDeadlineSeconds: number
}
```

`TASK_DISPATCH_DEADLINE_SECONDS`는 기본 `900`, 허용 범위 `15..1800`으로 파싱하고 parse/export queue에 동일하게 전달한다.

```ts
task: {
  dispatchDeadline: { seconds: this.configuration.dispatchDeadlineSeconds },
  httpRequest: { /* existing payload */ },
}
```

Cloud Run template과 staging env example에는 다음을 추가한다.

```text
TASK_DISPATCH_DEADLINE_SECONDS=900
```

- [ ] **Step 4: GREEN을 확인한다**

Run: `cd services/document-api && npm run check`

Expected: 모든 test와 TypeScript build 성공.

- [ ] **Step 5: 관련 workflow를 확인한다**

Expected: `Document API`, `Collaboration Emulator E2E`, `Collaboration recovery E2E` 성공.

---

### Task 2: Machine-readable staging manifest

**Files:**
- Create: `deploy/staging/staging-manifest.json`
- Create: `scripts/tests/test_staging_preflight.py`
- Modify: `scripts/validate_staging_config.py`

**Interfaces:**
- Consumes: architecture design section 18, Cloud Run templates, `firebase/staging.env.example`
- Produces: schema version `rhwp.staging/v1` manifest and `load_manifest(path: Path) -> dict[str, object]`

- [ ] **Step 1: manifest validation failing tests를 작성한다**

Python `unittest`로 다음을 검증한다.

```python
manifest = load_manifest(MANIFEST_PATH)
self.assertEqual(manifest["schemaVersion"], "rhwp.staging/v1")
self.assertEqual(manifest["project"]["region"], "asia-northeast3")
self.assertEqual(manifest["tasks"]["parse"]["dispatchDeadlineSeconds"], 900)
self.assertEqual(manifest["tasks"]["export"]["dispatchDeadlineSeconds"], 900)
```

또한 production-like project ID, mutable image tag, secret value field, region mismatch와 budget currency가 `KRW`가 아닌 경우를 거부하는 test를 추가한다.

- [ ] **Step 2: RED를 확인한다**

Run: `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`

Expected: manifest 파일 또는 `load_manifest`가 없어 실패한다.

- [ ] **Step 3: staging manifest를 작성한다**

Manifest는 architecture design section 18의 필드를 모두 포함하고 아직 승인되지 않은 값은 빈 문자열이 아니라 명시적인 `${PLACEHOLDER}` 문자열로 둔다.

핵심 고정값:

```json
{
  "schemaVersion": "rhwp.staging/v1",
  "environment": "staging",
  "project": { "region": "asia-northeast3" },
  "tasks": {
    "parse": { "dispatchDeadlineSeconds": 900 },
    "export": { "dispatchDeadlineSeconds": 900 }
  },
  "budget": { "currency": "KRW", "thresholds": [0.5, 0.8, 1.0] }
}
```

- [ ] **Step 4: static validator를 manifest-aware로 확장한다**

Validator는 다음을 검사한다.

```text
schemaVersion/environment
project ID placeholder와 forbiddenProjectIds
region/location 일치
3개 Cloud Run name/ingress/runtime 값
2개 queue name/location/retry/rate/deadline 값
4개 service account placeholder
secret name/version reference와 secret value 부재
IAM binding 구조와 broad Owner/Editor role 부재
budget.currency=KRW, threshold 정렬과 범위
Cloud Run template 및 staging.env의 TASK_DISPATCH_DEADLINE_SECONDS=900 정합성
```

- [ ] **Step 5: GREEN을 확인한다**

Run:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

Expected: test 성공, validator가 deployment를 수행하지 않았다는 메시지 출력.

---

### Task 3: Live read-only preflight와 JSON report

**Files:**
- Create: `scripts/staging_preflight.py`
- Modify: `scripts/tests/test_staging_preflight.py`

**Interfaces:**
- Consumes: `deploy/staging/staging-manifest.json`, subprocess command runner
- Produces: CLI `python3 scripts/staging_preflight.py --manifest PATH [--live] [--report PATH]`

- [ ] **Step 1: command allowlist와 report failing tests를 작성한다**

Test double runner를 사용해 live mode가 아래 조회 명령만 호출하는지 검증한다.

```text
gcloud auth list
gcloud config get-value project
gcloud projects describe
gcloud billing projects describe
gcloud services list --enabled
gcloud run services list/describe
gcloud tasks queues list/describe
gcloud secrets list/describe
gcloud iam service-accounts list
gcloud projects get-iam-policy
gcloud artifacts repositories list/describe
firebase projects:list
```

금지 verb 또는 명령이 전달되면 실행 전에 실패해야 한다.

```python
with self.assertRaises(PreflightError):
    run_read_only(["gcloud", "run", "deploy", "service"], runner)
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`

Expected: `staging_preflight` module 또는 CLI API가 없어 실패한다.

- [ ] **Step 3: static/live CLI를 구현한다**

Static mode:

```text
manifest schema와 repository 계약 검증
report.status = pass/fail
cloudQueries = []
mutationCommands = []
```

Live mode:

```text
placeholder project ID이면 즉시 중단
active account/project 확인
project, billing, API, Run, Tasks, Secret, service account, IAM, Artifact Registry, Firebase project를 조회
manifest 기대값과 실제 상태의 match/missing/unexpected 차이를 report에 기록
조회 명령 failure는 mutation 없이 report에 기록하고 exit 1
```

Report에는 secret value, access token, Authorization header와 credential JSON을 포함하지 않는다.

- [ ] **Step 4: GREEN을 확인한다**

Run:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/staging_preflight.py \
  --manifest deploy/staging/staging-manifest.json \
  --report /tmp/rhwp-staging-preflight.json
```

Expected: static report 생성, `mode=static`, `mutationCommands=[]`, exit 0.

---

### Task 4: GitHub Actions workflow_dispatch

**Files:**
- Modify: `.github/workflows/staging-config-validate.yml`

**Interfaces:**
- Consumes: manifest, validator CLI, optional repository secrets `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PREFLIGHT_SERVICE_ACCOUNT`
- Produces: manual static/live preflight execution and `staging-preflight-report` artifact

- [ ] **Step 1: workflow validation test를 먼저 추가한다**

Python test가 workflow text에 다음 계약이 있는지 검증한다.

```text
workflow_dispatch
inputs.live_check
inputs.manifest_path
permissions.contents=read
permissions.id-token=write
python3 scripts/staging_preflight.py
upload-artifact
```

또한 workflow에 `gcloud ... create|update|delete|deploy|enable|disable` 명령이 없는지 검사한다.

- [ ] **Step 2: RED를 확인한다**

Run: `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v`

Expected: 기존 workflow에 `workflow_dispatch`와 artifact 단계가 없어 실패한다.

- [ ] **Step 3: 수동 workflow를 구현한다**

`pull_request`에서는 static test와 validator를 실행한다. `workflow_dispatch`에서는 `live_check=false`가 기본이며, true인 경우에만 `google-github-actions/auth`와 `setup-gcloud`을 실행한다.

```yaml
on:
  pull_request: ...
  workflow_dispatch:
    inputs:
      live_check:
        type: boolean
        default: false
      manifest_path:
        type: string
        default: deploy/staging/staging-manifest.json
```

항상 JSON report를 artifact로 업로드하고, live mode에는 environment protection이나 사용자 승인 없이 mutation 단계로 연결되는 job을 추가하지 않는다.

- [ ] **Step 4: GREEN을 확인한다**

Run:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/validate_staging_config.py
```

Expected: workflow contract test와 static validator 성공.

---

### Task 5: 문서·PR 상태와 전체 검증

**Files:**
- Modify: `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- Modify: `docs/runbooks/staging-deployment.md`
- Modify: Draft PR `WBmaker2/rhwp#1` body

**Interfaces:**
- Consumes: 최종 implementation head와 workflow conclusions
- Produces: 완료된 deadline/manifest/preflight 상태와 남은 명시적 승인 단계

- [ ] **Step 1: 설계와 runbook을 구현 결과에 맞춘다**

`TASK_DISPATCH_DEADLINE_SECONDS=900`, manifest 경로, validator CLI, workflow_dispatch static/live mode와 report artifact를 기록한다.

- [ ] **Step 2: 전체 workflow를 확인한다**

필수 성공:

```text
CI
CodeQL
Document API
Staging configuration
Collaboration recovery E2E
Collaboration Emulator E2E
Document worker
Collaboration browser visual
Render Diff
```

- [ ] **Step 3: PR 설명을 최신 head로 갱신한다**

PR body에 다음을 기록한다.

```text
dispatchDeadline=900s 구현 완료
machine-readable manifest 경로
static/live read-only validator 경로와 허용 명령 범위
workflow_dispatch와 report artifact
실제 cloud mutation 없음
다음 단계: project·region·비용·IAM 변경 내역 제시와 명시적 승인
```

- [ ] **Step 4: PR 경계를 재확인한다**

Expected:

```text
state = open
draft = true
merged = false
base = devel
```
