import { createHash } from 'node:crypto'

export type SnapshotReason =
  | 'debounce'
  | 'size-threshold'
  | 'last-user'
  | 'export'
  | 'shutdown'

export interface SnapshotRecord {
  path: string
  checksum: string
  createdAt: string
  reason: SnapshotReason
  sizeBytes: number
}

export interface SnapshotDocumentState {
  latestSnapshotPath: string | null
  snapshots: SnapshotRecord[]
}

export interface SnapshotObjectStore {
  write(path: string, value: Uint8Array): Promise<void>
  read(path: string): Promise<Uint8Array | null>
  delete(path: string): Promise<void>
}

export interface SnapshotMetadataStore {
  load(documentId: string): Promise<SnapshotDocumentState | null>
  commit(documentId: string, state: SnapshotDocumentState): Promise<void>
}

export interface SnapshotStoreOptions {
  now?: () => Date
  maxSnapshots?: number
}

export class SnapshotStore {
  readonly #now: () => Date
  readonly #maxSnapshots: number

  constructor(
    readonly objects: SnapshotObjectStore,
    readonly documents: SnapshotMetadataStore,
    options: SnapshotStoreOptions = {},
  ) {
    const maxSnapshots = options.maxSnapshots ?? 10
    if (!Number.isSafeInteger(maxSnapshots) || maxSnapshots < 1) {
      throw new RangeError('maxSnapshots must be a positive safe integer')
    }

    this.#now = options.now ?? (() => new Date())
    this.#maxSnapshots = maxSnapshots
  }

  async load(documentId: string): Promise<Uint8Array | null> {
    const normalizedDocumentId = assertDocumentId(documentId)
    const state = await this.documents.load(normalizedDocumentId)
    if (!state || state.snapshots.length === 0) {
      return null
    }

    for (const record of orderedCandidates(state)) {
      const update = await this.objects.read(record.path)
      if (!update) {
        continue
      }

      if (sha256(update) === record.checksum) {
        return update.slice()
      }
    }

    return null
  }

  async save(
    documentId: string,
    update: Uint8Array,
    reason: SnapshotReason,
  ): Promise<SnapshotRecord> {
    const normalizedDocumentId = assertDocumentId(documentId)
    const now = this.#now()
    if (Number.isNaN(now.getTime())) {
      throw new RangeError('snapshot timestamp must be valid')
    }

    const storedUpdate = update.slice()
    const checksum = sha256(storedUpdate)
    const record: SnapshotRecord = {
      path: snapshotPath(normalizedDocumentId, now, checksum),
      checksum,
      createdAt: now.toISOString(),
      reason,
      sizeBytes: storedUpdate.byteLength,
    }

    // The object is durable before Firestore publishes it as the latest snapshot.
    await this.objects.write(record.path, storedUpdate)

    const current = await this.documents.load(normalizedDocumentId)
    const records = [
      record,
      ...(current?.snapshots ?? []).filter(
        (candidate) => candidate.path !== record.path,
      ),
    ]
    const retained = records.slice(0, this.#maxSnapshots)
    const expired = records.slice(this.#maxSnapshots)
    await this.documents.commit(normalizedDocumentId, {
      latestSnapshotPath: record.path,
      snapshots: retained,
    })

    // Metadata no longer references expired objects, so cleanup can safely run
    // after the atomic metadata commit. Failed cleanup only leaves an orphan and
    // never makes the published snapshot unreadable.
    await Promise.allSettled(
      expired.map((candidate) => this.objects.delete(candidate.path)),
    )

    return record
  }
}

export function snapshotPath(
  documentId: string,
  createdAt: Date,
  checksum: string,
): string {
  const normalizedDocumentId = assertDocumentId(documentId)
  if (!/^[a-f0-9]{64}$/.test(checksum)) {
    throw new TypeError('snapshot checksum must be lowercase SHA-256 hex')
  }

  return `documents/${normalizedDocumentId}/collaboration/snapshots/${createdAt.getTime()}-${checksum}.bin`
}

function orderedCandidates(state: SnapshotDocumentState): SnapshotRecord[] {
  const byPath = new Map(
    state.snapshots.map((record) => [record.path, record] as const),
  )
  const latest = state.latestSnapshotPath
    ? byPath.get(state.latestSnapshotPath)
    : undefined
  const ordered = latest
    ? [latest, ...state.snapshots.filter((record) => record.path !== latest.path)]
    : state.snapshots

  return ordered
}

function sha256(value: Uint8Array): string {
  return createHash('sha256').update(value).digest('hex')
}

function assertDocumentId(documentId: string): string {
  const normalized = documentId.trim()
  if (
    normalized.length === 0 ||
    normalized === '.' ||
    normalized === '..' ||
    normalized.includes('/') ||
    normalized.includes('\\')
  ) {
    throw new TypeError('documentId must be a non-empty path segment')
  }

  return normalized
}
