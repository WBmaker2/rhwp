import { getApps, initializeApp, type App } from 'firebase-admin/app'
import { getFirestore, type Firestore } from 'firebase-admin/firestore'
import { getStorage } from 'firebase-admin/storage'

import type { ExportTaskPayload, ParseTaskPayload } from './contracts.js'
import type {
  ParsedDocumentState,
  TaskClaim,
  WorkerObjectMetadata,
  WorkerObjectStore,
  WorkerStateStore,
} from './worker.js'

type StorageBucket = ReturnType<ReturnType<typeof getStorage>['bucket']>

const TASK_LEASE_MS = 20 * 60 * 1_000

export interface DocumentWorkerEnvironment {
  port: number
  storageBucket: string
  nativeBinaryPath: string
  allowEmulatorTasks: boolean
}

export interface DocumentWorkerFirebaseAdapters {
  app: App
  objects: FirebaseWorkerObjectStore
  state: FirestoreWorkerStateStore
}

export class FirebaseWorkerObjectStore implements WorkerObjectStore {
  constructor(private readonly bucket: Pick<StorageBucket, 'file' | 'upload'>) {}

  async stat(path: string): Promise<WorkerObjectMetadata | null> {
    try {
      const [metadata] = await this.bucket.file(assertObjectPath(path)).getMetadata()
      const sizeBytes = Number(metadata.size)
      const generation = String(metadata.generation ?? '')
      if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0 || !generation) {
        throw new Error('invalid storage object metadata')
      }
      return {
        sizeBytes,
        generation,
        contentType: String(metadata.contentType ?? 'application/octet-stream'),
      }
    } catch (error) {
      if (isNotFound(error)) return null
      throw error
    }
  }

  async download(path: string, destination: string): Promise<void> {
    await this.bucket.file(assertObjectPath(path)).download({ destination })
  }

  async upload(path: string, source: string, contentType: string): Promise<void> {
    await this.bucket.upload(source, {
      destination: assertObjectPath(path),
      resumable: false,
      metadata: {
        contentType,
        cacheControl: 'private, no-store',
      },
    })
  }
}

export class FirestoreWorkerStateStore implements WorkerStateStore {
  constructor(private readonly firestore: Pick<Firestore, 'doc' | 'runTransaction'>) {}

  async claimParse(payload: ParseTaskPayload, taskKey: string, now: Date): Promise<TaskClaim> {
    const reference = this.firestore.doc(documentPath(payload.documentId))
    return this.firestore.runTransaction(async (transaction) => {
      const snapshot = await transaction.get(reference)
      if (!snapshot.exists) throw new Error('document metadata does not exist')
      const current = parseTaskState(snapshot.get('parseWorker'))
      const claim = reusableClaim(current, taskKey, now)
      if (claim) return claim
      transaction.set(reference, {
        parseWorker: {
          taskKey,
          status: 'processing',
          sourceGeneration: payload.sourceGeneration,
          sourcePath: payload.sourcePath,
          leaseExpiresAt: new Date(now.getTime() + TASK_LEASE_MS),
          updatedAt: now,
          error: null,
        },
      }, { merge: true })
      return 'acquired'
    })
  }

  async completeParse(payload: ParseTaskPayload, result: {
    taskKey: string
    sourceFingerprint: string
    manifestPath: string
    paragraphCount: number
    cellCount: number
    completedAt: Date
  }): Promise<void> {
    await this.firestore.doc(documentPath(payload.documentId)).set({
      status: 'ready',
      sourceGeneration: payload.sourceGeneration,
      sourceFingerprint: result.sourceFingerprint,
      collaborationManifestPath: result.manifestPath,
      parseWorker: {
        taskKey: result.taskKey,
        status: 'ready',
        sourceGeneration: payload.sourceGeneration,
        sourceFingerprint: result.sourceFingerprint,
        sourcePath: payload.sourcePath,
        manifestPath: result.manifestPath,
        paragraphCount: result.paragraphCount,
        cellCount: result.cellCount,
        leaseExpiresAt: null,
        completedAt: result.completedAt,
        updatedAt: result.completedAt,
        error: null,
      },
      updatedAt: result.completedAt,
    }, { merge: true })
  }

  async failParse(payload: ParseTaskPayload, result: {
    taskKey: string
    message: string
    failedAt: Date
  }): Promise<void> {
    await this.firestore.doc(documentPath(payload.documentId)).set({
      parseWorker: {
        taskKey: result.taskKey,
        status: 'failed',
        sourceGeneration: payload.sourceGeneration,
        sourcePath: payload.sourcePath,
        leaseExpiresAt: null,
        failedAt: result.failedAt,
        updatedAt: result.failedAt,
        error: result.message,
      },
      updatedAt: result.failedAt,
    }, { merge: true })
  }

  async getParsedDocument(documentId: string): Promise<ParsedDocumentState | null> {
    const snapshot = await this.firestore.doc(documentPath(documentId)).get()
    if (!snapshot.exists) return null
    const state = snapshot.get('parseWorker')
    if (!state || typeof state !== 'object') return null
    const input = state as Record<string, unknown>
    if (
      input.status !== 'ready'
      || typeof input.sourceGeneration !== 'string'
      || typeof input.sourceFingerprint !== 'string'
      || typeof input.sourcePath !== 'string'
      || typeof input.manifestPath !== 'string'
    ) {
      return null
    }
    return {
      status: 'ready',
      sourceGeneration: input.sourceGeneration,
      sourceFingerprint: input.sourceFingerprint,
      sourcePath: input.sourcePath,
      manifestPath: input.manifestPath,
    }
  }

  async claimExport(payload: ExportTaskPayload, taskKey: string, now: Date): Promise<TaskClaim> {
    const reference = this.firestore.doc(exportMetadataPath(payload.documentId, payload.exportId))
    return this.firestore.runTransaction(async (transaction) => {
      const snapshot = await transaction.get(reference)
      const current = snapshot.exists ? parseTaskState(snapshot.data()) : null
      const claim = reusableClaim(current, taskKey, now)
      if (claim) return claim
      transaction.set(reference, {
        taskKey,
        status: 'processing',
        snapshotPath: payload.snapshotPath,
        leaseExpiresAt: new Date(now.getTime() + TASK_LEASE_MS),
        createdAt: snapshot.exists ? snapshot.get('createdAt') ?? now : now,
        updatedAt: now,
        error: null,
      }, { merge: true })
      return 'acquired'
    })
  }

  async completeExport(payload: ExportTaskPayload, result: {
    taskKey: string
    outputPath: string
    outputBytes: number
    updatedParagraphs: number
    updatedCells: number
    completedAt: Date
  }): Promise<void> {
    const batchTime = result.completedAt
    await this.firestore.runTransaction(async (transaction) => {
      const exportReference = this.firestore.doc(
        exportMetadataPath(payload.documentId, payload.exportId),
      )
      const documentReference = this.firestore.doc(documentPath(payload.documentId))
      transaction.set(exportReference, {
        taskKey: result.taskKey,
        status: 'ready',
        snapshotPath: payload.snapshotPath,
        storagePath: result.outputPath,
        sizeBytes: result.outputBytes,
        updatedParagraphs: result.updatedParagraphs,
        updatedCells: result.updatedCells,
        leaseExpiresAt: null,
        completedAt: batchTime,
        updatedAt: batchTime,
        error: null,
      }, { merge: true })
      transaction.set(documentReference, {
        latestExportPath: result.outputPath,
        updatedAt: batchTime,
      }, { merge: true })
    })
  }

  async failExport(payload: ExportTaskPayload, result: {
    taskKey: string
    message: string
    failedAt: Date
  }): Promise<void> {
    await this.firestore.doc(exportMetadataPath(payload.documentId, payload.exportId)).set({
      taskKey: result.taskKey,
      status: 'failed',
      snapshotPath: payload.snapshotPath,
      leaseExpiresAt: null,
      failedAt: result.failedAt,
      updatedAt: result.failedAt,
      error: result.message,
    }, { merge: true })
  }
}

export function readDocumentWorkerEnvironment(
  environment: NodeJS.ProcessEnv,
): DocumentWorkerEnvironment {
  const port = Number(environment.PORT ?? '8080')
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer from 1 to 65535')
  }
  return {
    port,
    storageBucket: required(environment, 'FIREBASE_STORAGE_BUCKET'),
    nativeBinaryPath: required(environment, 'RHWP_COLLABORATION_WORKER_BIN'),
    allowEmulatorTasks: environment.ALLOW_EMULATOR_TASKS === 'true',
  }
}

export function createDocumentWorkerFirebaseAdapters(
  environment: NodeJS.ProcessEnv = process.env,
): DocumentWorkerFirebaseAdapters {
  const configuration = readDocumentWorkerEnvironment(environment)
  const app = getApps()[0] ?? initializeApp({ storageBucket: configuration.storageBucket })
  const firestore = getFirestore(app)
  const bucket = getStorage(app).bucket(configuration.storageBucket)
  return {
    app,
    objects: new FirebaseWorkerObjectStore(bucket),
    state: new FirestoreWorkerStateStore(firestore),
  }
}

interface StoredTaskState {
  taskKey: string
  status: 'processing' | 'ready' | 'failed'
  leaseExpiresAt: Date | null
}

function reusableClaim(
  current: StoredTaskState | null,
  taskKey: string,
  now: Date,
): TaskClaim | null {
  if (!current || current.taskKey !== taskKey) return null
  if (current.status === 'ready') return 'already-ready'
  if (
    current.status === 'processing'
    && current.leaseExpiresAt !== null
    && current.leaseExpiresAt.getTime() > now.getTime()
  ) {
    return 'already-processing'
  }
  return null
}

function parseTaskState(value: unknown): StoredTaskState | null {
  if (!value || typeof value !== 'object') return null
  const input = value as Record<string, unknown>
  if (
    typeof input.taskKey !== 'string'
    || (input.status !== 'processing' && input.status !== 'ready' && input.status !== 'failed')
  ) {
    return null
  }
  return {
    taskKey: input.taskKey,
    status: input.status,
    leaseExpiresAt: timestampDate(input.leaseExpiresAt),
  }
}

function timestampDate(value: unknown): Date | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null
  if (value && typeof value === 'object') {
    const toDate = (value as { toDate?: unknown }).toDate
    if (typeof toDate === 'function') {
      const date = toDate.call(value) as unknown
      return date instanceof Date && Number.isFinite(date.getTime()) ? date : null
    }
  }
  return null
}

function documentPath(documentId: string): string {
  return `documents/${assertId(documentId)}`
}

function exportMetadataPath(documentId: string, exportId: string): string {
  return `documents/${assertId(documentId)}/exports/${assertId(exportId)}`
}

function assertId(value: string): string {
  const normalized = value.trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(normalized)) {
    throw new Error('invalid identifier')
  }
  return normalized
}

function assertObjectPath(value: string): string {
  const normalized = value.trim()
  if (!normalized.startsWith('documents/') || normalized.includes('..')) {
    throw new Error('invalid storage object path')
  }
  return normalized
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}

function isNotFound(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const code = (error as { code?: unknown }).code
  return code === 404 || code === '404' || code === 'storage/object-not-found'
}
