export interface JoinAccepted {
  accepted: true
  uniqueUsers: number
}

export interface JoinRejected {
  accepted: false
  reason: 'participant-limit'
  uniqueUsers: number
}

export type JoinResult = JoinAccepted | JoinRejected

export class ParticipantRegistry {
  readonly #documents = new Map<string, Map<string, Set<string>>>()

  constructor(readonly maxUniqueUsers = 10) {
    if (!Number.isSafeInteger(maxUniqueUsers) || maxUniqueUsers < 1) {
      throw new RangeError('maxUniqueUsers must be a positive safe integer')
    }
  }

  tryJoin(documentId: string, userId: string, connectionId: string): JoinResult {
    const participants = this.#documents.get(documentId)
    const existingConnections = participants?.get(userId)

    if (existingConnections) {
      existingConnections.add(connectionId)
      return {
        accepted: true,
        uniqueUsers: participants?.size ?? 0,
      }
    }

    const uniqueUsers = participants?.size ?? 0
    if (uniqueUsers >= this.maxUniqueUsers) {
      return {
        accepted: false,
        reason: 'participant-limit',
        uniqueUsers,
      }
    }

    const documentParticipants = participants ?? new Map<string, Set<string>>()
    documentParticipants.set(userId, new Set([connectionId]))
    this.#documents.set(documentId, documentParticipants)

    return {
      accepted: true,
      uniqueUsers: documentParticipants.size,
    }
  }

  leave(documentId: string, userId: string, connectionId: string): void {
    const participants = this.#documents.get(documentId)
    const connections = participants?.get(userId)
    if (!participants || !connections) {
      return
    }

    connections.delete(connectionId)
    if (connections.size > 0) {
      return
    }

    participants.delete(userId)
    if (participants.size === 0) {
      this.#documents.delete(documentId)
    }
  }

  uniqueUsers(documentId: string): number {
    return this.#documents.get(documentId)?.size ?? 0
  }
}
