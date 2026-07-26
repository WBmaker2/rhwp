import assert from 'node:assert/strict'
import type { IncomingMessage, ServerResponse } from 'node:http'
import test from 'node:test'

import { Server } from '@hocuspocus/server'

import type { MembershipStore, TokenVerifier } from '../src/auth.js'
import { ParticipantRegistry } from '../src/participants.js'
import {
  InternalHttpRequestHandledError,
  ParticipantLimitError,
  createCollaborationHooks,
  createCollaborationServer,
  handleInternalHttpRequest,
} from '../src/server.js'

const tokenVerifier: TokenVerifier = {
  async verifyIdToken(idToken) {
    return {
      uid: idToken,
      displayName: idToken,
      photoURL: null,
    }
  },
}

const membershipStore: MembershipStore = {
  async getMembership(_documentId, userId) {
    return { role: userId === 'viewer' ? 'viewer' : 'editor' }
  },
}

test('authenticates, applies viewer read-only mode, and returns trusted context', async () => {
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
  })
  const connection = { readOnly: false }

  const context = await hooks.onAuthenticate({
    documentName: 'doc-1',
    token: 'viewer',
    socketId: 'tab-viewer',
    connection,
  })

  assert.equal(connection.readOnly, true)
  assert.deepEqual(context, {
    documentId: 'doc-1',
    userId: 'viewer',
    role: 'viewer',
    displayName: 'viewer',
    photoURL: null,
  })
})

test('releases the participant slot on disconnect', async () => {
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
  })
  const contexts = []

  for (let index = 1; index <= 10; index += 1) {
    contexts.push(
      await hooks.onAuthenticate({
        documentName: 'doc-1',
        token: `user-${index}`,
        socketId: `tab-${index}`,
        connection: { readOnly: false },
      }),
    )
  }

  await assert.rejects(
    hooks.onAuthenticate({
      documentName: 'doc-1',
      token: 'user-11',
      socketId: 'tab-11',
      connection: { readOnly: false },
    }),
    (error: unknown) => error instanceof ParticipantLimitError,
  )

  hooks.onDisconnect({
    documentName: 'doc-1',
    socketId: 'tab-1',
    context: contexts[0],
  })

  const admitted = await hooks.onAuthenticate({
    documentName: 'doc-1',
    token: 'user-11',
    socketId: 'tab-11',
    connection: { readOnly: false },
  })
  assert.equal(admitted.userId, 'user-11')
})

test('rejects the Hocuspocus hook chain after an internal response was handled', async () => {
  const request = {} as IncomingMessage
  const response = {} as ServerResponse

  await assert.rejects(
    handleInternalHttpRequest(async (receivedRequest, receivedResponse) => {
      assert.equal(receivedRequest, request)
      assert.equal(receivedResponse, response)
      return true
    }, request, response),
    (error: unknown) => error instanceof InternalHttpRequestHandledError,
  )

  await handleInternalHttpRequest(async () => false, request, response)
})

test('creates a Hocuspocus server without starting a listener', () => {
  const server = createCollaborationServer({
    port: 1234,
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
  })

  assert.ok(server instanceof Server)
})
