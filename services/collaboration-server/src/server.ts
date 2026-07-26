import { Server } from '@hocuspocus/server'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Doc } from 'yjs'

import {
  verifyConnection,
  type AuthorizedConnection,
  type MembershipStore,
  type TokenVerifier,
} from './auth.js'
import { ParticipantRegistry } from './participants.js'
import {
  type SnapshotRecord,
  YjsSnapshotPersistence,
} from './persistence.js'

export class ParticipantLimitError extends Error {
  readonly code = 'participant-limit'

  constructor(readonly uniqueUsers: number) {
    super(`document participant limit reached: ${uniqueUsers}`)
    this.name = 'ParticipantLimitError'
  }
}

export class InternalHttpRequestHandledError extends Error {
  constructor() {
    super('internal HTTP request handled')
    this.name = 'InternalHttpRequestHandledError'
  }
}

export interface CollaborationServerDependencies {
  port?: number
  tokenVerifier: TokenVerifier
  membershipStore: MembershipStore
  participants?: ParticipantRegistry
  persistence?: YjsSnapshotPersistence
  internalRequestHandler?: (
    request: IncomingMessage,
    response: ServerResponse,
  ) => Promise<boolean>
}

export interface AuthenticateHookInput {
  documentName: string
  token: string
  socketId: string
  connection: {
    readOnly: boolean
  }
}

export interface DocumentHookInput {
  documentName: string
  document: Doc
}

export interface LoadDocumentHookInput {
  documentName: string
}

export interface DisconnectHookInput {
  documentName: string
  socketId: string
  context: AuthorizedConnection | undefined
}

export interface UnloadDocumentHookInput {
  documentName: string
}

export interface CollaborationHooks {
  onAuthenticate(input: AuthenticateHookInput): Promise<AuthorizedConnection>
  onLoadDocument(input: LoadDocumentHookInput): Promise<Uint8Array | undefined>
  afterLoadDocument(input: DocumentHookInput): void
  onStoreDocument(input: DocumentHookInput): Promise<SnapshotRecord | undefined>
  onDisconnect(input: DisconnectHookInput): Promise<void>
  afterUnloadDocument(input: UnloadDocumentHookInput): void
  onDestroy(): Promise<void>
  flushForExport(documentId: string): Promise<SnapshotRecord | null>
}

export function createCollaborationHooks(
  dependencies: CollaborationServerDependencies,
): CollaborationHooks {
  const participants = dependencies.participants ?? new ParticipantRegistry()
  const persistence = dependencies.persistence

  return {
    async onAuthenticate(input) {
      const authorized = await verifyConnection({
        documentId: input.documentName,
        idToken: input.token,
        tokenVerifier: dependencies.tokenVerifier,
        membershipStore: dependencies.membershipStore,
      })
      const joinResult = participants.tryJoin(
        authorized.documentId,
        authorized.userId,
        input.socketId,
      )

      if (!joinResult.accepted) {
        throw new ParticipantLimitError(joinResult.uniqueUsers)
      }

      input.connection.readOnly = authorized.role === 'viewer'
      return authorized
    },

    async onLoadDocument(input) {
      return (await persistence?.load(input.documentName)) ?? undefined
    },

    afterLoadDocument(input) {
      persistence?.register(input.documentName, input.document)
    },

    async onStoreDocument(input) {
      if (!persistence) return undefined
      return persistence.save(input.documentName, input.document, 'debounce')
    },

    async onDisconnect(input) {
      if (!input.context) return
      participants.leave(
        input.context.documentId,
        input.context.userId,
        input.socketId,
      )
      if (participants.uniqueUsers(input.context.documentId) === 0) {
        await persistence?.flush(input.context.documentId, 'last-user')
      }
    },

    afterUnloadDocument(input) {
      persistence?.unregister(input.documentName)
    },

    async onDestroy() {
      await persistence?.flushForShutdown()
    },

    async flushForExport(documentId) {
      return (await persistence?.flushForExport(documentId)) ?? null
    },
  }
}

export async function handleInternalHttpRequest(
  handler: NonNullable<CollaborationServerDependencies['internalRequestHandler']>,
  request: IncomingMessage,
  response: ServerResponse,
): Promise<void> {
  if (await handler(request, response)) {
    throw new InternalHttpRequestHandledError()
  }
}

export function createCollaborationServer(
  dependencies: CollaborationServerDependencies,
): Server<AuthorizedConnection> {
  const hooks = createCollaborationHooks(dependencies)

  return new Server<AuthorizedConnection>({
    port: dependencies.port ?? 1234,
    quiet: true,
    maxUnauthenticatedQueueSize: 5 * 1024 * 1024,
    maxUnauthenticatedQueueMessages: 1000,
    maxPendingDocuments: 100,

    async onRequest(payload) {
      if (!dependencies.internalRequestHandler) return
      const { request, response } = payload as typeof payload & {
        request: IncomingMessage
        response: ServerResponse
      }
      await handleInternalHttpRequest(
        dependencies.internalRequestHandler,
        request,
        response,
      )
    },

    async onAuthenticate(payload) {
      const { documentName, token, socketId } = payload
      const { connection } = payload as typeof payload & {
        connection: { readOnly: boolean }
      }

      return hooks.onAuthenticate({
        documentName,
        token,
        socketId,
        connection,
      })
    },

    async onLoadDocument({ documentName }) {
      return hooks.onLoadDocument({ documentName })
    },

    async afterLoadDocument({ documentName, document }) {
      hooks.afterLoadDocument({ documentName, document })
    },

    async onStoreDocument({ documentName, document }) {
      return hooks.onStoreDocument({ documentName, document })
    },

    async onDisconnect({ documentName, socketId, context }) {
      await hooks.onDisconnect({ documentName, socketId, context })
    },

    async afterUnloadDocument({ documentName }) {
      hooks.afterUnloadDocument({ documentName })
    },

    async onDestroy() {
      await hooks.onDestroy()
    },
  })
}
