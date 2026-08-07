# Firebase 협업 Task 6 빌드·WASM·E2E·세션 수명주기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 브랜치의 협업 기능을 실제 rhwp-studio 빌드와 최신 WASM 산출물에서 검증하고, 문서 수명주기에 맞춰 협업 런타임을 시작·재시작·종료하는 세션 매니저를 구현한 뒤 두 탭 E2E로 증명한다.

**Architecture:** 기존 `CollaborationController`·`RhwpYjsAdapter`·`bootstrapStudioCollaboration`을 유지하고, Task 6에서는 새 데이터 모델을 추가하지 않는다. 빌드 파이프라인은 `npm ci → wasm-pack build → generated API 검증 → Studio build` 순서로 고정하고, 세션 매니저는 현재 bootstrap 함수를 단일 활성 세션으로 감싸 문서 변경과 브라우저 종료를 안전하게 처리한다.

**Tech Stack:** Rust, wasm-bindgen, wasm-pack, TypeScript 7, Vite 8, Node.js test runner, Puppeteer Core, BroadcastChannel, 기존 Yjs/Hocuspocus 협업 런타임.

## Global Constraints

- 작업 브랜치는 `feat/firebase-collaboration-mvp-v1`을 유지한다.
- 원격에서 이미 반영된 이미지 patch·Yjs·Firebase 인증·presence 기능을 삭제하거나 단순화하지 않는다.
- `pkg/`, `node_modules/`, `.chatgpt2codex/`는 커밋 대상이 아니다.
- 이번 단계에서는 사용자용 공유 링크 UI를 추가하지 않는다.
- 새 세션 매니저는 동시에 하나의 활성 협업 세션만 허용한다.
- 새 문서 열기, 문서 닫기, fingerprint 변경, 구조 변경, `beforeunload`에서 기존 세션을 종료한다.
- 구조 변경 후에는 기존 StableId registry를 계속 사용하지 않고 세션 재시작 또는 중단으로 처리한다.
- 커밋과 push는 사용자가 별도로 요청할 때만 수행한다.

---

### Task 6-1: Studio 의존성 설치와 전체 TypeScript/Vite 빌드

**Files:**
- Modify only if build errors require it: `rhwp-studio/package.json`
- Modify only if build errors require it: `rhwp-studio/package-lock.json`
- Modify as required by actual type errors: `rhwp-studio/src/collaboration/*.ts`
- Test: `rhwp-studio/tests/collaboration-*.test.ts`

**Interfaces:**
- Consumes: current package lock and collaboration modules.
- Produces: reproducible `npm ci`, passing collaboration focused tests, and passing `npm run build` after Task 6-2 generates `pkg/`.

- [ ] **Step 1: Verify baseline tool and dependency state**

Run:

```bash
node --version
npm --version
wasm-pack --version
[ -d rhwp-studio/node_modules ] && echo present || echo missing
```

Expected: Node and npm are present. Missing `node_modules` or `wasm-pack` is recorded as setup work, not treated as a source-code defect.

- [ ] **Step 2: Install exact Studio dependencies from lockfile**

Run:

```bash
npm --prefix rhwp-studio ci
```

Expected: `rhwp-studio/node_modules/.bin/tsc`, `vite`, `tsx`, and `puppeteer-core` exist without modifying dependency versions.

- [ ] **Step 3: Run collaboration focused tests before code changes**

Run:

```bash
npm --prefix rhwp-studio run test:collaboration
```

Expected: all collaboration tests pass. Any failure is investigated before continuing.

- [ ] **Step 4: Run TypeScript typecheck separately**

Run:

```bash
npm --prefix rhwp-studio exec tsc -- --noEmit
```

Expected: PASS after the WASM package exists. If the only failure is missing `@wasm/rhwp.js`, continue to Task 6-2 and repeat this step.

---

### Task 6-2: WASM 패키지 재생성과 공개 API 검증

**Files:**
- Source of truth: `src/wasm_api.rs`
- Generated, ignored: `pkg/rhwp.js`
- Generated, ignored: `pkg/rhwp.d.ts`
- Generated, ignored: `pkg/rhwp_bg.wasm`
- Generated, ignored: `pkg/rhwp_bg.wasm.d.ts`
- Verify against declarations: `typescript/rhwp.d.ts`
- Optional local sync for browser verification: `rhwp-studio/public/`

**Interfaces:**
- Consumes Rust methods:
  - `getCollaborationManifest`
  - `applyCollaborationParagraphText`
  - `applyCollaborationCellText`
  - `getCollaborationParagraphText`
  - `getCollaborationCellText`
- Produces generated JavaScript and declaration files exposing each method exactly once.

- [ ] **Step 1: Install `wasm-pack` if absent**

Run only when `wasm-pack --version` fails:

```bash
cargo install wasm-pack --locked
```

Expected: `wasm-pack --version` succeeds.

- [ ] **Step 2: Build the web-target WASM package**

Run:

```bash
wasm-pack build --target web --out-dir pkg
```

Expected: `pkg/rhwp.js`, `pkg/rhwp.d.ts`, `pkg/rhwp_bg.wasm`, and `pkg/rhwp_bg.wasm.d.ts` are created.

- [ ] **Step 3: Verify all five collaboration methods in generated bindings**

Run:

```bash
for name in \
  getCollaborationManifest \
  applyCollaborationParagraphText \
  applyCollaborationCellText \
  getCollaborationParagraphText \
  getCollaborationCellText
do
  test "$(grep -c "$name" pkg/rhwp.js)" -ge 1
  test "$(grep -c "$name" pkg/rhwp.d.ts)" -ge 1
done
```

Expected: all methods are present in JavaScript glue and generated declarations.

- [ ] **Step 4: Run Studio typecheck and Vite build against fresh `pkg/`**

Run:

```bash
npm --prefix rhwp-studio run build
```

Expected: `tsc && vite build` passes with the newly generated bindings.

- [ ] **Step 5: Preserve generated-output policy**

Run:

```bash
git status --short pkg rhwp-studio/public
```

Expected: `pkg/` remains ignored. Any tracked `rhwp-studio/public` diff is reviewed and excluded unless the repository contract explicitly requires synchronization.

---

### Task 6-3: 실제 두 탭 BroadcastChannel E2E 실행과 안정화

**Files:**
- Modify: `rhwp-studio/e2e/collaboration-two-tab.test.mjs`
- Modify only if required: `rhwp-studio/src/collaboration/broadcast-channel-transport.ts`
- Modify only if required: `rhwp-studio/src/collaboration/local-collaboration-controller.ts`
- Test fixture/helper if required: `rhwp-studio/e2e/fixtures/collaboration-two-tab.html`

**Interfaces:**
- Consumes: browser-native `BroadcastChannel`, `LocalCollaborationController`, `CollaborationDocumentAdapter`.
- Produces: deterministic two-page test proving paragraph and cell propagation, no echo, duplicate suppression, and disconnect behavior.

- [ ] **Step 1: Run the existing E2E as the RED/baseline check**

Run:

```bash
node rhwp-studio/e2e/collaboration-two-tab.test.mjs
```

Expected: PASS. If it fails, retain the first actionable assertion or browser error as the defect to fix.

- [ ] **Step 2: Ensure Chromium discovery is deterministic**

The test must resolve an installed Chromium/Chrome executable using the repository's established E2E helper or an explicit ordered candidate list. It must fail with a clear message when no browser is installed.

- [ ] **Step 3: Verify the complete two-tab scenario**

Assertions must cover:

```text
A paragraph local edit → B receives final Korean text once
B cell local edit → A receives final cell text once
remote apply does not generate a reflected local update
duplicate updateId is ignored
controller.stop() prevents later delivery
```

- [ ] **Step 4: Repeat the E2E to detect timing flakiness**

Run:

```bash
for i in 1 2 3; do node rhwp-studio/e2e/collaboration-two-tab.test.mjs; done
```

Expected: three consecutive passes.

---

### Task 6-4: Studio 문서 수명주기용 CollaborationSessionManager

**Files:**
- Create: `rhwp-studio/src/collaboration/collaboration-session-manager.ts`
- Create: `rhwp-studio/tests/collaboration-session-manager.test.ts`
- Modify: `rhwp-studio/src/collaboration-entry.ts`
- Modify if runtime event wiring requires it: `rhwp-studio/src/main.ts`
- Modify if bootstrap API needs explicit fingerprint exposure: `rhwp-studio/src/collaboration/bootstrap.ts`

**Interfaces:**
- Consumes:
  - `bootstrapStudioCollaboration(runtime, environment): Promise<() => void>`
  - `runtime.wasm.hasLoadedDocument(): boolean`
  - `runtime.eventBus.on(event, listener): () => void`
- Produces:

```ts
export interface CollaborationSessionManagerOptions {
  runtime: StudioCollaborationRuntime;
  environment: CollaborationEnvironment;
  bootstrap: typeof bootstrapStudioCollaboration;
  windowLike?: Pick<Window, 'addEventListener' | 'removeEventListener'>;
}

export class CollaborationSessionManager {
  start(): Promise<void>;
  restart(reason: string): Promise<void>;
  stop(reason?: string): void;
  readonly isRunning: boolean;
  readonly lastError: unknown | null;
}
```

- [ ] **Step 1: Write failing session-manager tests**

Tests must verify:

```text
start creates one session
concurrent/repeated start does not create duplicates
restart destroys the previous session before creating the next
new-document/document-closed/fingerprint-changed/structure-change events stop or restart according to policy
beforeunload destroys the active session
bootstrap failure leaves no active session and records lastError
stop is idempotent and removes all listeners
```

Run:

```bash
node --test --import tsx rhwp-studio/tests/collaboration-session-manager.test.ts
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement the minimal serialized lifecycle manager**

Implementation rules:

```text
one active destroy callback
one in-flight transition promise
restart = stop old → bootstrap new
stale async bootstrap result is destroyed instead of becoming active
all event subscriptions are retained and removed on stop/destroy
```

- [ ] **Step 3: Replace direct entry bootstrap with the manager**

`rhwp-studio/src/collaboration-entry.ts` changes from a one-shot bootstrap to:

```ts
const manager = new CollaborationSessionManager({
  runtime,
  environment,
  bootstrap: bootstrapStudioCollaboration,
});
await manager.start();
```

The entry must not separately register a duplicate `beforeunload` destroy callback when the manager owns it.

- [ ] **Step 4: Run focused manager and collaboration tests**

Run:

```bash
node --test --import tsx \
  rhwp-studio/tests/collaboration-session-manager.test.ts \
  rhwp-studio/tests/collaboration-*.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Run full Task 6 verification**

Run sequentially:

```bash
cargo fmt --check
cargo check
cargo test --test collaboration_model
cargo test --test collaboration_apply
cargo test --test collaboration_read
npm --prefix rhwp-studio run test:collaboration
npm --prefix rhwp-studio run build
node rhwp-studio/e2e/collaboration-two-tab.test.mjs
git diff --check
git status --short
```

Expected: focused Rust and Studio tests, fresh-WASM Studio build, and two-tab E2E all pass. Only intended source and plan files remain modified; `.chatgpt2codex/`, `pkg/`, and `node_modules/` are not staged.

## Self-review

- Task 6-1 covers exact lockfile installation, focused tests, and full TypeScript/Vite validation.
- Task 6-2 covers fresh WASM generation and the five required public methods.
- Task 6-3 covers actual two-page browser transport behavior and repeated stability runs.
- Task 6-4 reuses the existing Yjs/Firebase bootstrap and adds only missing document-lifecycle ownership.
- No Firebase sharing UI, CRDT redesign, or generated artifact commit is included.
- All function names and paths match the current repository structure.


## 실행 상태 (2026-07-26)

### 완료

- Task 6-3 실제 두 탭 E2E를 `puppeteer-core` 없는 Node 내장 CDP 방식으로 전환했다.
- localhost 동일 origin의 Chrome 탭 2개에서 문단 한글 전파, 표 셀 전파, 원격 echo 방지, 중복 updateId 억제, 종료 후 전달 차단을 검증했다.
- 두 탭 E2E는 최초 1회와 연속 3회 실행을 모두 통과했다.
- Task 6-4 `CollaborationSessionManager`를 구현하고 Studio entry에 연결했다.
- 문서 교체 직전 `collaboration-document-replacing`, 초기화 완료 후 `collaboration-document-ready`를 발행하도록 연결했다.
- 단일 활성 세션, 동시 start 중복 억제, restart 순서, stale bootstrap 폐기, 구조 변경 중단, beforeunload 정리, 오류 기록을 테스트했다.
- 세션 매니저 테스트 10개와 dependency-free 협업 테스트 23개가 통과했다.
- Rust `cargo fmt --check`, `cargo check`, 협업 focused 테스트 23개가 통과했다.
- fresh WASM 산출물의 5개 공개 API를 검사하는 `scripts/check-collaboration-wasm-api.mjs`와 테스트 2개를 추가했다.

### 실행 환경 승인 대기

- `npm ci`는 사용자 승인 후에도 로컬 실행 도구가 `APPROVAL_REQUIRED`를 반환해 실행되지 않았다.
- `npm ci --offline`은 npm 캐시에 `yjs@13.6.31`이 없어 실패했다.
- `wasm-pack`은 설치돼 있지 않고 Cargo 오프라인 캐시에도 없어 fresh `pkg/` 생성이 불가능했다.
- 기존 `rhwp-studio/public` 바인딩에는 요구된 5개 API가 없으며, `pkg/` 디렉터리도 존재하지 않는다.
- 따라서 Task 6-1의 정확한 lockfile 설치·전체 Studio build와 Task 6-2의 fresh WASM 생성·API 실산출물 검증은 네트워크 명령 실행 승인이 실제 도구에 전달된 뒤 완료해야 한다.

### 승인 후 남은 명령

```bash
npm --prefix rhwp-studio ci
cargo install wasm-pack --locked
wasm-pack build --target web --out-dir pkg
node scripts/check-collaboration-wasm-api.mjs pkg
npm --prefix rhwp-studio run test:collaboration
npm --prefix rhwp-studio run build
```

## 2026-07-26 실제 Studio 빌드 후속 검증

사용자가 `npm ci` 후 `npm --prefix rhwp-studio run build`를 실행하면서 다음 두 원인을 확인했다.

1. `collaboration-entry.ts`가 `bootstrap.ts`에 존재하지 않는 `resolveCollaborationEnvironment`를 import했다.
   실제 기존 export인 `collaborationEnvironmentFromWindow`로 수정하고 소스 계약 테스트를 추가했다.
2. `pkg/rhwp.js`와 `pkg/rhwp.d.ts`가 생성되지 않아 `@wasm/rhwp.js` 해석이 실패했다.

수정 후 저장소 CI와 같은 임시 WASM type/runtime stub을 사용해 다음 검증이 통과했다.

```text
npm --prefix rhwp-studio run test:collaboration: 34 passed, 0 failed
npm --prefix rhwp-studio run build: tsc + Vite PASS
```

따라서 현재 TypeScript/Vite 소스 오류는 없으며, 실제 완료를 위해서는 `wasm-pack build --target web --out-dir pkg`로 fresh WASM 패키지를 만든 뒤 공개 API 검사와 실제 빌드를 다시 실행해야 한다. 임시 stub은 검증 직후 제거했다.
