import { getApps, initializeApp, type App } from 'firebase-admin/app'
import { getAuth, type Auth } from 'firebase-admin/auth'
import { getFirestore, type Firestore } from 'firebase-admin/firestore'
import { getStorage } from 'firebase-admin/storage'
import { CloudTasksClient } from '@google-cloud/tasks'

import type { ParseLeaseState, ParseLeaseStore } from './parse-lease.js'
import type { DocumentRole } from './routes/complete-upload.js'
import type {
  ShareLinkRecord,
  ShareLinkRedemption,
  ShareLinkRole,
  ShareLinkStore,
} from './share-links.js'

type StorageBucket = ReturnType<ReturnType<typeof getStorage>['bucket']>

export interface TaskQueueConfiguration {
  projectId: string
  location: string
  queue: string
  targetUrl: string
  serviceAccountEmail: string
}

export interface DocumentApiEnvironment {
  port: number
  storageBucket: string
  collaborationFlushUrl: string
  parseQueue: TaskQueueConfiguration
  exportQueue: TaskQueueConfiguration
}

export interface DocumentApiFirebaseAdapters {
  app: App
  auth: FirebaseIdTokenVerifier
  members: FirestoreMemberStore
  objects: FirebaseObjectMetadataStore
  leaseStore: FirestoreParseLeaseStore
  shareLinks: FirestoreShareLinkStore
  parseQueue: CloudTasksJobQueue
  exportQueue: CloudTasksJobQueue
}

export class FirebaseIdTokenVerifier {
  constructor(private readonly auth: Pick<Auth, 'verifyIdToken'>) {}
  async verifyIdToken(token: string): Promise<{ uid: string }> {
    const decoded = await this.auth.verifyIdToken(token)
    if (!decoded.uid) throw new Error('verified token has no uid')
    return { uid: decoded.uid }
  }
}

export class FirestoreMemberStore {
  constructor(private readonly firestore: Pick<Firestore, 'doc'>) {}
  async getRole(documentId: string, uid: string): Promise<DocumentRole | null> {
    const snapshot = await this.firestore
      .doc(`documents/${assertId(documentId)}/members/${assertId(uid)}`)
      .get()
    if (!snapshot.exists) return null
    const role = snapshot.get('role')
    return isDocumentRole(role) ? role : null
  }
}

export class FirebaseObjectMetadataStore {
  constructor(private readonly bucket: Pick<StorageBucket, 'file'>) {}
  async stat(path: string): Promise<{
    sizeBytes: number
    generation: string
    contentType: string
  } | null> {
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
}

export class FirestoreParseLeaseStore implements ParseLeaseStore {
  constructor(private readonly firestore: Pick<Firestore, 'doc' | 'runTransaction'>) {}

  async runTransaction<T>(
    documentId: string,
    operation: (current: ParseLeaseState | null) => {
      state: ParseLeaseState
      result: T
    },
  ): Promise<T> {
    const reference = this.firestore.doc(`documents/${assertId(documentId)}`)
    return this.firestore.runTransaction(async (transaction) => {
      const snapshot = await transaction.get(reference)
      const raw = snapshot.exists ? snapshot.get('parseLease') : null
      const current = isParseLeaseState(raw) ? raw : null
      const next = operation(current)
      transaction.set(reference, { parseLease: next.state }, { merge: true })
      return next.result
    })
  }
}

export class FirestoreShareLinkStore implements ShareLinkStore {
  constructor(
    private readonly firestore: Pick<Firestore, 'collection' | 'doc' | 'runTransaction'>,
  ) {}

  async create(record: ShareLinkRecord): Promise<void> {
    await this.firestore.doc(`shareLinks/${record.shareId}`).create({
      documentId: record.documentId,
      role: record.role,
      enabled: record.enabled,
      expiresAt: record.expiresAt === null ? null : new Date(record.expiresAt),
      createdBy: record.createdBy,
      createdAt: new Date(record.createdAt),
    })
  }

  async list(documentId: string, createdBy: string): Promise<ShareLinkRecord[]> {
    const snapshot = await this.firestore
      .collection('shareLinks')
      .where('documentId', '==', assertId(documentId))
      .get()
    return snapshot.docs
      .map((document) => parseShareLinkRecord(document.id, document.data()))
      .filter((record): record is ShareLinkRecord => (
        record !== null && record.createdBy === createdBy
      ))
  }

  async disable(documentId: string, createdBy: string, shareId: string): Promise<boolean> {
    const reference = this.firestore.doc(`shareLinks/${assertShareId(shareId)}`)
    return this.firestore.runTransaction(async (transaction) => {
      const snapshot = await transaction.get(reference)
      if (!snapshot.exists) return false
      const record = parseShareLinkRecord(snapshot.id, snapshot.data())
      if (
        record === null
        || record.documentId !== documentId
        || record.createdBy !== createdBy
      ) {
        return false
      }
      if (record.enabled) transaction.update(reference, { enabled: false })
      return true
    })
  }

  async redeem(shareId: string, uid: string, now: Date): Promise<ShareLinkRedemption> {
    const linkReference = this.firestore.doc(`shareLinks/${assertShareId(shareId)}`)
    return this.firestore.runTransaction(async (transaction) => {
      const linkSnapshot = await transaction.get(linkReference)
      if (!linkSnapshot.exists) return { status: 'not-found' }
      const record = parseShareLinkRecord(linkSnapshot.id, linkSnapshot.data())
      if (record === null) return { status: 'not-found' }
      if (!record.enabled) return { status: 'disabled' }
      if (record.expiresAt !== null && new Date(record.expiresAt).getTime() <= now.getTime()) {
        return { status: 'expired' }
      }

      const documentReference = this.firestore.doc(`documents/${assertId(record.documentId)}`)
      const memberReference = this.firestore.doc(
        `documents/${assertId(record.documentId)}/members/${assertId(uid)}`,
      )
      const documentSnapshot = await transaction.get(documentReference)
      if (!documentSnapshot.exists) return { status: 'not-found' }
      const memberSnapshot = await transaction.get(memberReference)
      const ownerId = documentSnapshot.get('ownerId')
      if (ownerId === uid) {
        return { status: 'accepted', documentId: record.documentId, role: 'owner' }
      }

      const currentRole = memberSnapshot.exists ? memberSnapshot.get('role') : null
      const effectiveRole = strongerRole(currentRole, record.role)
      if (!memberSnapshot.exists) {
        transaction.create(memberReference, {
          role: effectiveRole,
          invitedBy: record.createdBy,
          createdAt: now,
        })
      } else if (currentRole !== effectiveRole) {
        transaction.update(memberReference, { role: effectiveRole })
      }
      return {
        status: 'accepted',
        documentId: record.documentId,
        role: effectiveRole,
      }
    })
  }
}

export class CloudTasksJobQueue {
  constructor(
    private readonly client: Pick<CloudTasksClient, 'queuePath' | 'createTask'>,
    private readonly configuration: TaskQueueConfiguration,
  ) {}

  async enqueue(input: Record<string, unknown>): Promise<{ jobId: string }> {
    const parent = this.client.queuePath(
      this.configuration.projectId,
      this.configuration.location,
      this.configuration.queue,
    )
    const body = Buffer.from(JSON.stringify(input)).toString('base64')
    const [task] = await this.client.createTask({
      parent,
      task: {
        httpRequest: {
          httpMethod: 'POST',
          url: this.configuration.targetUrl,
          headers: { 'Content-Type': 'application/json' },
          body,
          oidcToken: {
            serviceAccountEmail: this.configuration.serviceAccountEmail,
            audience: this.configuration.targetUrl,
          },
        },
      },
    })
    return { jobId: task.name ?? `${this.configuration.queue}/unknown` }
  }
}

export function readDocumentApiEnvironment(
  environment: NodeJS.ProcessEnv,
): DocumentApiEnvironment {
  const port = parsePort(environment.PORT ?? '8080')
  const projectId = required(environment, 'GCP_PROJECT_ID')
  const location = required(environment, 'GCP_LOCATION')
  const serviceAccountEmail = required(environment, 'TASKS_SERVICE_ACCOUNT_EMAIL')
  const queue = (
    queueName: 'PARSE_QUEUE' | 'EXPORT_QUEUE',
    workerUrl: 'PARSE_WORKER_URL' | 'EXPORT_WORKER_URL',
  ): TaskQueueConfiguration => ({
    projectId,
    location,
    queue: required(environment, queueName),
    targetUrl: assertHttpsUrl(required(environment, workerUrl), workerUrl),
    serviceAccountEmail,
  })
  return {
    port,
    storageBucket: required(environment, 'FIREBASE_STORAGE_BUCKET'),
    collaborationFlushUrl: assertHttpsUrl(
      required(environment, 'COLLABORATION_FLUSH_URL'),
      'COLLABORATION_FLUSH_URL',
    ),
    parseQueue: queue('PARSE_QUEUE', 'PARSE_WORKER_URL'),
    exportQueue: queue('EXPORT_QUEUE', 'EXPORT_WORKER_URL'),
  }
}

export function createDocumentApiFirebaseAdapters(
  environment: NodeJS.ProcessEnv = process.env,
): DocumentApiFirebaseAdapters {
  const configuration = readDocumentApiEnvironment(environment)
  const app = getApps()[0] ?? initializeApp({ storageBucket: configuration.storageBucket })
  const firestore = getFirestore(app)
  const bucket = getStorage(app).bucket(configuration.storageBucket)
  const tasks = new CloudTasksClient()
  return {
    app,
    auth: new FirebaseIdTokenVerifier(getAuth(app)),
    members: new FirestoreMemberStore(firestore),
    objects: new FirebaseObjectMetadataStore(bucket),
    leaseStore: new FirestoreParseLeaseStore(firestore),
    shareLinks: new FirestoreShareLinkStore(firestore),
    parseQueue: new CloudTasksJobQueue(tasks, configuration.parseQueue),
    exportQueue: new CloudTasksJobQueue(tasks, configuration.exportQueue),
  }
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}

function parsePort(value: string): number {
  const port = Number(value)
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer from 1 to 65535')
  }
  return port
}

function assertHttpsUrl(value: string, name: string): string {
  const url = new URL(value)
  if (url.protocol !== 'https:') throw new Error(`${name} must use https`)
  return url.toString().replace(/\/$/, '')
}

function assertId(value: string): string {
  const normalized = value.trim()
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(normalized)) throw new Error('invalid identifier')
  return normalized
}

function assertShareId(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (!/^[a-f0-9]{64}$/.test(normalized)) throw new Error('invalid share ID')
  return normalized
}

function assertObjectPath(value: string): string {
  const normalized = value.trim()
  if (!normalized.startsWith('documents/') || normalized.includes('..')) {
    throw new Error('invalid object path')
  }
  return normalized
}

function parseShareLinkRecord(
  shareId: string,
  value: Record<string, unknown> | undefined,
): ShareLinkRecord | null {
  if (!value) return null
  const role = value.role
  const documentId = value.documentId
  const createdBy = value.createdBy
  const enabled = value.enabled
  const createdAt = timestampToIso(value.createdAt)
  const expiresAt = value.expiresAt === null ? null : timestampToIso(value.expiresAt)
  if (
    (role !== 'editor' && role !== 'viewer')
    || typeof documentId !== 'string'
    || typeof createdBy !== 'string'
    || typeof enabled !== 'boolean'
    || createdAt === null
    || (value.expiresAt !== null && expiresAt === null)
  ) {
    return null
  }
  return {
    shareId: assertShareId(shareId),
    documentId,
    role,
    enabled,
    expiresAt,
    createdBy,
    createdAt,
  }
}

function timestampToIso(value: unknown): string | null {
  if (value instanceof Date && Number.isFinite(value.getTime())) return value.toISOString()
  if (value && typeof value === 'object') {
    const toDate = (value as { toDate?: unknown }).toDate
    if (typeof toDate === 'function') {
      const date = toDate.call(value) as unknown
      if (date instanceof Date && Number.isFinite(date.getTime())) return date.toISOString()
    }
  }
  if (typeof value === 'string') {
    const date = new Date(value)
    if (Number.isFinite(date.getTime())) return date.toISOString()
  }
  return null
}

function strongerRole(current: unknown, invited: ShareLinkRole): ShareLinkRole {
  if (current === 'editor') return 'editor'
  return invited
}

function isDocumentRole(value: unknown): value is DocumentRole {
  return value === 'owner' || value === 'editor' || value === 'viewer'
}

function isParseLeaseState(value: unknown): value is ParseLeaseState {
  if (!value || typeof value !== 'object') return false
  const state = value as Partial<ParseLeaseState>
  return typeof state.sourceGeneration === 'string'
    && (state.status === 'processing' || state.status === 'ready' || state.status === 'failed')
    && (state.leaseExpiresAt === null || typeof state.leaseExpiresAt === 'string')
}

function isNotFound(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const code = (error as { code?: unknown }).code
  return code === 404 || code === '404' || code === 'storage/object-not-found'
}
