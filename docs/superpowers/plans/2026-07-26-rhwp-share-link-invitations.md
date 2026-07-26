# rhwp Secure Share-Link Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 문서 소유자가 편집 또는 열람 공유 링크를 발급·조회·폐기하고, Google 로그인 사용자가 링크를 수락해 문서 멤버십을 얻을 수 있게 한다.

**Architecture:** 원문 공유 토큰은 최초 발급 응답에서만 노출하고 Firestore에는 `SHA-256(token)`을 share ID로 저장한다. Document API가 Firebase ID token과 문서 owner 권한을 검증해 링크를 관리하며, 수락은 Firestore transaction에서 링크 상태·만료·기존 멤버 역할을 검증하고 멤버십을 원자적으로 생성 또는 승격한다. 클라이언트 SDK의 `shareLinks` 직접 읽기·쓰기는 차단한다.

**Tech Stack:** Node.js 22, TypeScript, Firebase Admin SDK, Firestore transactions, Firebase Authentication, rhwp-studio, Node test runner, Firebase Rules Emulator.

## Global Constraints

- 원본 HWP 업로드 크기는 `0 < 파일 크기 ≤ 200 MiB`다.
- 역할은 `owner`, `editor`, `viewer`이며 공유 링크는 `editor` 또는 `viewer`만 부여한다.
- 원문 공유 토큰은 Firestore, 로그, URL query, 오류 응답에 저장하지 않는다.
- 링크 수락은 Firebase Google 로그인 이후에만 가능하다.
- 기존 owner 역할은 변경하지 않고, 기존 editor를 viewer로 낮추지 않는다.
- 만료되었거나 disabled인 링크는 수락할 수 없다.
- merge와 Firebase·Cloud Run 배포는 사용자 명시적 승인 전까지 수행하지 않는다.

---

### Task 1: Share-link domain and Firestore adapter

**Files:**
- Create: `services/document-api/src/share-links.ts`
- Modify: `services/document-api/src/firebase-adapters.ts`
- Test: `services/document-api/tests/share-links.test.ts`

**Interfaces:**
- Produces: `ShareLinkStore`, `ShareLinkService`, `ShareLinkRecord`, `createShareToken()`, `hashShareToken(token)`.
- `ShareLinkService.create(documentId, ownerUid, role, expiresAt)` returns `{ shareId, token, role, expiresAt }`.
- `ShareLinkService.list(documentId, ownerUid)` returns metadata without token.
- `ShareLinkService.disable(documentId, ownerUid, shareId)` disables one owned link.
- `ShareLinkService.redeem(token, uid)` returns `{ documentId, role }` and atomically creates or upgrades membership.

- [ ] Write focused tests for token hashing, no token persistence, owner-only management, expiration, disabled links, existing-role preservation, and viewer-to-editor upgrade.
- [ ] Run `cd services/document-api && npm test -- tests/share-links.test.ts` and verify RED.
- [ ] Implement the minimal domain service and Firestore adapter.
- [ ] Run `cd services/document-api && npm run check` and verify GREEN.
- [ ] Commit the task.

### Task 2: Document API routes

**Files:**
- Create: `services/document-api/src/routes/share-links.ts`
- Modify: `services/document-api/src/http-server.ts`
- Modify: `services/document-api/src/main.ts`
- Modify: `services/document-api/src/index.ts`
- Test: `services/document-api/tests/share-link-routes.test.ts`
- Test: `services/document-api/tests/http-server.test.ts`

**Interfaces:**
- `POST /v1/documents/{documentId}/share-links` body `{ role, expiresAt? }`.
- `GET /v1/documents/{documentId}/share-links`.
- `DELETE /v1/documents/{documentId}/share-links/{shareId}`.
- `POST /v1/share-links/redeem` body `{ token }`.
- All routes require a valid Firebase bearer token; management routes require owner membership.

- [ ] Write route tests for validation, authentication, owner authorization, response redaction, expiration parsing, revoke, and redeem.
- [ ] Run focused tests and verify RED.
- [ ] Wire handlers into the HTTP dispatcher and runtime.
- [ ] Run `cd services/document-api && npm run check` and verify GREEN.
- [ ] Commit the task.

### Task 3: Firestore security boundary

**Files:**
- Modify: `firebase/firestore.rules`
- Modify: `firebase/tests/rules.test.mjs`

**Interfaces:**
- Client SDK access to top-level `shareLinks/{shareId}` is denied for create/read/update/delete.
- Server Admin SDK remains the sole management and redemption path.

- [ ] Replace the existing owner-direct-write test with denial tests for owner, editor, viewer, and unauthenticated clients.
- [ ] Run Firebase Rules Emulator tests and verify RED under the old rules.
- [ ] Deny all client access to `shareLinks`.
- [ ] Run the rules workflow locally or in CI and verify GREEN.
- [ ] Commit the task.

### Task 4: Studio share dialog and invitation redemption

**Files:**
- Create: `rhwp-studio/src/collaboration/ShareLinkClient.ts`
- Create: `rhwp-studio/src/collaboration/ShareDialog.ts`
- Modify: `rhwp-studio/src/collaboration/bootstrap.ts`
- Modify: `rhwp-studio/src/collaboration-entry.ts`
- Modify: `rhwp-studio/src/main.ts`
- Test: `rhwp-studio/tests/collaboration-share-links.test.ts`

**Interfaces:**
- Owner sees a `공유` action with role, optional expiry, copy-link, active-link list, and revoke controls.
- Invitation URL uses a path fragment or route-safe token segment, not a query parameter.
- On invitation entry, Studio completes Google login, calls redeem, removes the raw token from browser history with `history.replaceState`, then opens the document.

- [ ] Write unit tests for API calls, owner-only rendering, copy payload, revoke, redeem, token removal, and error states.
- [ ] Run `cd rhwp-studio && npm run test:collaboration` and verify RED.
- [ ] Implement client and UI using existing collaboration bootstrap patterns.
- [ ] Run Studio collaboration tests and TypeScript build; verify GREEN.
- [ ] Commit the task.

### Task 5: End-to-end contracts and documentation

**Files:**
- Modify: `services/e2e/tests/collaboration-flow.test.ts`
- Create: `docs/superpowers/status/2026-07-26-rhwp-share-link-status.md`
- Modify: PR #1 description after verification.

**Interfaces:**
- End-to-end test proves owner issues editor/viewer links, authenticated users redeem, disabled/expired links fail, role downgrade is prevented, and no raw token is persisted.

- [ ] Add service-level share-link flow tests.
- [ ] Run Document API, Firebase Rules, Studio collaboration, and recovery E2E workflows.
- [ ] Verify the latest head has no required failed checks.
- [ ] Record implemented scope, known limitations, and the next worker/E2E tasks.
- [ ] Keep PR #1 Draft and do not merge or deploy.
