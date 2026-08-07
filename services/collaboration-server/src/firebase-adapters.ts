import { getApps, initializeApp, type App } from 'firebase-admin/app'
import { getAuth } from 'firebase-admin/auth'
import { getFirestore, type Firestore } from 'firebase-admin/firestore'
import { getStorage } from 'firebase-admin/storage'

import {
  createFirebaseTokenVerifier,
  createFirestoreMembershipStore,
} from './auth.js'
import type {
  SnapshotDocumentState,
  SnapshotMetadataStore,
  SnapshotObjectStore,
  SnapshotReason,
  SnapshotRecord,
} from './persistence.js'

type StorageBucket = ReturnType<ReturnType<typeof getStorage>['bucket']>

export interface CollaborationServerEnvironment {
  port: number
  storageBucket: string
  internalApiToken: string
}

export interface CollaborationFirebaseAdapters {
  app: App
  tokenVerifier: ReturnType<typeof createFirebaseTokenVerifier>
  membershipStore: ReturnType<typeof createFirestoreMembershipStore>
  objects: SnapshotObjectStore
  metadata: SnapshotMetadataStore
}

export class FirebaseSnapshotObjectStore implements SnapshotObjectStore {
  constructor(private readonly bucket: Pick<StorageBucket, 'file'>) {}

  async write(path: string, value: Uint8Array): Promise<void> {
    await this.bucket.file(assertObjectPath(path)).save(Buffer.from(value), {
      resumable: false,
      contentType: 'application/octet-stream',
      metadata: { cacheControl: 'private, no-store' },
    })
  }

  async read(path: string): Promise<Uint8Array | null> {
    try {
      const [value] = await this.bucket.file(assertObjectPath(path)).download()
      return new Uint8Array(value)
    } catch (error) {
      if (isNotFound(error)) return null
      throw error
    }
  }

  async delete(path: string): Promise<void> {
    try {
      await this.bucket.file(assertObjectPath(path)).delete({ ignoreNotFound: true })
    } catch (error) {
      if (!isNotFound(error)) throw error
    }
  }
}

export class FirebaseSnapshotMetadataStore implements SnapshotMetadataStore {
  constructor(private readonly firestore: Pick<Firestore, 'doc'>) {}

  async load(documentId: string): Promise<SnapshotDocumentState | null> {
    const snapshot = await this.firestore.doc(documentPath(documentId)).get()
    if (!snapshot.exists) return null
    const latestSnapshotPath = snapshot.get('latestSnapshotPath')
    const rawSnapshots = snapshot.get('collaborationSnapshots')
    const snapshots = Array.isArray(rawSnapshots)
      ? rawSnapshots.filter(isSnapshotRecord)
      : []
    return {
      latestSnapshotPath:
        typeof latestSnapshotPath === 'string' ? latestSnapshotPath : null,
      snapshots,
    }
  }

  async commit(documentId: string, state: SnapshotDocumentState): Promise<void> {
    await this.firestore.doc(documentPath(documentId)).set({
      latestSnapshotPath: state.latestSnapshotPath,
      collaborationSnapshots: state.snapshots,
      updatedAt: new Date(),
    }, { merge: true })
  }
}

export function readCollaborationServerEnvironment(
  environment: NodeJS.ProcessEnv,
): CollaborationServerEnvironment {
  const port = Number(environment.PORT ?? '8080')
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer from 1 to 65535')
  }
  const storageBucket = required(environment, 'FIREBASE_STORAGE_BUCKET')
  const internalApiToken = required(environment, 'INTERNAL_API_TOKEN')
  return { port, storageBucket, internalApiToken }
}

export function createCollaborationFirebaseAdapters(
  environment: NodeJS.ProcessEnv = process.env,
): CollaborationFirebaseAdapters {
  const configuration = readCollaborationServerEnvironment(environment)
  const app = getApps()[0] ?? initializeApp({
    storageBucket: configuration.storageBucket,
  })
  const firestore = getFirestore(app)
  const bucket = getStorage(app).bucket(configuration.storageBucket)
  return {
    app,
    tokenVerifier: createFirebaseTokenVerifier(getAuth(app)),
    membershipStore: createFirestoreMembershipStore(firestore),
    objects: new FirebaseSnapshotObjectStore(bucket),
    metadata: new FirebaseSnapshotMetadataStore(firestore),
  }
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}

function documentPath(documentId: string): string {
  const normalized = documentId.trim()
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(normalized)) {
    throw new Error('invalid documentId')
  }
  return `documents/${normalized}`
}

function assertObjectPath(path: string): string {
  const normalized = path.trim()
  if (!normalized.startsWith('documents/') || normalized.includes('..')) {
    throw new Error('invalid storage object path')
  }
  return normalized
}

function isSnapshotRecord(value: unknown): value is SnapshotRecord {
  if (!value || typeof value !== 'object') return false
  const record = value as Partial<SnapshotRecord>
  return typeof record.path === 'string'
    && typeof record.checksum === 'string'
    && typeof record.createdAt === 'string'
    && isSnapshotReason(record.reason)
    && Number.isSafeInteger(record.sizeBytes)
    && Number(record.sizeBytes) >= 0
}

function isSnapshotReason(value: unknown): value is SnapshotReason {
  return value === 'debounce'
    || value === 'size-threshold'
    || value === 'last-user'
    || value === 'export'
    || value === 'shutdown'
}

function isNotFound(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const code = (error as { code?: unknown }).code
  return code === 404 || code === '404' || code === 'storage/object-not-found'
}
