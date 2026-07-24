import { Server } from '@hocuspocus/server'

import {
  verifyConnection,
  type AuthorizedConnection,
  type MembershipStore,
  type TokenVerifier,
} from './auth.js'
import { ParticipantRegistry } from './participants.js'

export class ParticipantLimitError extends Error {
  readonly code = 'participant-limit'

  constructor(readonly uniqueUsers: number) {
    super(`document participant limit reached: ${uniqueUsers}`)
    this.name = 'ParticipantLimitError'
  }
}

export interface CollaborationServerDependencies {
  port?: number
  tokenVerifier: TokenVerifier
  membershipStore: MembershipStore
  participants?: ParticipantRegistry
}

export interface AuthenticateHookInput {
  documentName: string
  token: string
  socketId: string
  connection: {
    readOnly: boolean
  }
}

export interface DisconnectHookInput {
  documentName: string
  socketId: string
  context: AuthorizedConnection | undefined
}

export interface CollaborationHooks {
  onAuthenticate(input: AuthenticateHookInput): Promise<AuthorizedConnection>
  onDisconnect(input: DisconnectHookInput): void
}

export function createCollaborationHooks(
  dependencies: CollaborationServerDependencies,
): CollaborationHooks {
  const participants = dependencies.participants ?? new ParticipantRegistry()

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

    onDisconnect(input) {
      if (!input.context) {
        return
      }

      participants.leave(
        input.context.documentId,
        input.context.userId,
        input.socketId,
      )
    },
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

    async onAuthenticate(payload) {
      // Hocuspocus v4 exposes `connection.readOnly` at runtime and documents it
      // as the supported read-only switch, but 4.4.0 omits it from the shipped
      // onAuthenticate payload declaration. Keep the compatibility cast at this
      // library boundary instead of weakening types throughout the service.
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

    async onDisconnect({ documentName, socketId, context }) {
      hooks.onDisconnect({
        documentName,
        socketId,
        context,
      })
    },
  })
}
