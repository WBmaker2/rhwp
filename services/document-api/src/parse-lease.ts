import { assertId } from './storage-paths.js'

export type ParseLeaseStatus = 'processing' | 'ready' | 'failed'

export interface ParseLeaseState {
  sourceGeneration: string
  status: ParseLeaseStatus
  leaseExpiresAt: string | null
}

export interface ParseLeaseStore {
  runTransaction<T>(
    documentId: string,
    operation: (
      current: ParseLeaseState | null,
    ) => { state: ParseLeaseState; result: T },
  ): Promise<T>
}

export type LeaseResult =
  | { acquired: true; expiresAt: string }
  | {
      acquired: false
      reason: 'already-processing' | 'already-complete'
    }

export interface ParseLeaseOptions {
  leaseDurationMs?: number
}

export class ParseLease {
  readonly #leaseDurationMs: number

  constructor(
    readonly store: ParseLeaseStore,
    options: ParseLeaseOptions = {},
  ) {
    const duration = options.leaseDurationMs ?? 15 * 60 * 1_000
    if (!Number.isSafeInteger(duration) || duration < 1) {
      throw new RangeError('leaseDurationMs must be a positive safe integer')
    }
    this.#leaseDurationMs = duration
  }

  async acquire(
    documentId: string,
    sourceGeneration: string,
    now: Date,
  ): Promise<LeaseResult> {
    const normalizedDocumentId = assertId(documentId, 'documentId')
    const normalizedGeneration = assertId(sourceGeneration, 'sourceGeneration')
    const nowMs = now.getTime()
    if (Number.isNaN(nowMs)) {
      throw new RangeError('lease time must be valid')
    }

    return this.store.runTransaction<LeaseResult>(
      normalizedDocumentId,
      (current) => {
        if (current?.sourceGeneration === normalizedGeneration) {
          if (current.status === 'ready') {
            return {
              state: current,
              result: {
                acquired: false,
                reason: 'already-complete',
              },
            }
          }

          const expiresAtMs = current.leaseExpiresAt
            ? Date.parse(current.leaseExpiresAt)
            : Number.NaN
          if (current.status === 'processing' && expiresAtMs > nowMs) {
            return {
              state: current,
              result: {
                acquired: false,
                reason: 'already-processing',
              },
            }
          }
        }

        const expiresAt = new Date(
          nowMs + this.#leaseDurationMs,
        ).toISOString()
        return {
          state: {
            sourceGeneration: normalizedGeneration,
            status: 'processing',
            leaseExpiresAt: expiresAt,
          },
          result: {
            acquired: true,
            expiresAt,
          },
        }
      },
    )
  }
}
