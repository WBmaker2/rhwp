import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ConnectionAuthorizationError,
  createFirestoreMembershipStore,
  verifyConnection,
  type MembershipStore,
  type TokenVerifier,
} from '../src/auth.js'

const tokenVerifier: TokenVerifier = {
  async verifyIdToken(idToken) {
    assert.equal(idToken, 'valid-token')
    return {
      uid: 'user-1',
      displayName: '홍길동',
      photoURL: 'https://example.test/avatar.png',
    }
  },
}

const membershipStore: MembershipStore = {
  async getMembership(documentId, userId) {
    assert.equal(documentId, 'doc-1')
    assert.equal(userId, 'user-1')
    return { role: 'editor' }
  },
}

test('verifies the Firebase token and resolves the server-side document role', async () => {
  const authorized = await verifyConnection({
    documentId: 'doc-1',
    idToken: 'valid-token',
    tokenVerifier,
    membershipStore,
  })

  assert.deepEqual(authorized, {
    documentId: 'doc-1',
    userId: 'user-1',
    role: 'editor',
    displayName: '홍길동',
    photoURL: 'https://example.test/avatar.png',
  })
})

test('rejects a connection without an ID token', async () => {
  await assert.rejects(
    verifyConnection({
      documentId: 'doc-1',
      idToken: '',
      tokenVerifier,
      membershipStore,
    }),
    (error: unknown) =>
      error instanceof ConnectionAuthorizationError &&
      error.code === 'unauthenticated',
  )
})

test('rejects an authenticated user without document membership', async () => {
  const noMembership: MembershipStore = {
    async getMembership() {
      return null
    },
  }

  await assert.rejects(
    verifyConnection({
      documentId: 'doc-1',
      idToken: 'valid-token',
      tokenVerifier,
      membershipStore: noMembership,
    }),
    (error: unknown) =>
      error instanceof ConnectionAuthorizationError && error.code === 'forbidden',
  )
})

test('loads membership from the canonical Firestore member path', async () => {
  let requestedPath = ''
  const firestore = {
    doc(path: string) {
      requestedPath = path
      return {
        async get() {
          return {
            exists: true,
            get(field: string) {
              assert.equal(field, 'role')
              return 'editor'
            },
          }
        },
      }
    },
  } as unknown as Parameters<typeof createFirestoreMembershipStore>[0]

  const store = createFirestoreMembershipStore(firestore)
  assert.deepEqual(await store.getMembership('doc-1', 'user-1'), {
    role: 'editor',
  })
  assert.equal(requestedPath, 'documents/doc-1/members/user-1')
})

test('rejects unknown Firestore membership roles', async () => {
  const firestore = {
    doc() {
      return {
        async get() {
          return {
            exists: true,
            get() {
              return 'administrator'
            },
          }
        },
      }
    },
  } as unknown as Parameters<typeof createFirestoreMembershipStore>[0]

  const store = createFirestoreMembershipStore(firestore)
  assert.equal(await store.getMembership('doc-1', 'user-1'), null)
})
