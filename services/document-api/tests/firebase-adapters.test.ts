import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  CloudTasksJobQueue,
  FirestoreParseLeaseStore,
  FirestoreShareLinkStore,
  readDocumentApiEnvironment,
} from '../src/firebase-adapters.js'

class FakeSnapshot {
  constructor(
    readonly id: string,
    private readonly value: Record<string, unknown> | undefined,
  ) {}
  get exists(): boolean { return this.value !== undefined }
  get(field: string): unknown { return this.value?.[field] }
  data(): Record<string, unknown> | undefined { return this.value }
}

class FakeReference {
  readonly id: string
  constructor(
    readonly path: string,
    private readonly data: Map<string, Record<string, unknown>>,
  ) {
    this.id = path.split('/').at(-1) ?? ''
  }
  async get(): Promise<FakeSnapshot> {
    return new FakeSnapshot(this.id, this.data.get(this.path))
  }
  async create(value: Record<string, unknown>): Promise<void> {
    if (this.data.has(this.path)) throw new Error('already exists')
    this.data.set(this.path, value)
  }
}

class FakeTransaction {
  readonly writes: Array<{ operation: string; path: string; value: unknown }> = []
  constructor(private readonly data: Map<string, Record<string, unknown>>) {}
  async get(reference: FakeReference): Promise<FakeSnapshot> {
    return new FakeSnapshot(reference.id, this.data.get(reference.path))
  }
  set(
    reference: FakeReference,
    value: Record<string, unknown>,
    options: { merge: boolean },
  ): void {
    assert.equal(options.merge, true)
    this.data.set(reference.path, {
      ...(this.data.get(reference.path) ?? {}),
      ...value,
    })
    this.writes.push({ operation: 'set', path: reference.path, value })
  }
  create(reference: FakeReference, value: Record<string, unknown>): void {
    if (this.data.has(reference.path)) throw new Error('already exists')
    this.data.set(reference.path, value)
    this.writes.push({ operation: 'create', path: reference.path, value })
  }
  update(reference: FakeReference, value: Record<string, unknown>): void {
    const current = this.data.get(reference.path)
    if (!current) throw new Error('not found')
    this.data.set(reference.path, { ...current, ...value })
    this.writes.push({ operation: 'update', path: reference.path, value })
  }
}

class FakeQuery {
  private filters: Array<{ field: string; value: unknown }> = []
  constructor(private readonly firestore: FakeFirestore) {}
  where(field: string, operator: string, value: unknown): FakeQuery {
    assert.equal(operator, '==')
    this.filters.push({ field, value })
    return this
  }
  async get(): Promise<{ docs: FakeSnapshot[] }> {
    const docs: FakeSnapshot[] = []
    for (const [path, value] of this.firestore.data) {
      if (!path.startsWith('shareLinks/')) continue
      if (this.filters.every((filter) => value[filter.field] === filter.value)) {
        docs.push(new FakeSnapshot(path.split('/').at(-1) ?? '', value))
      }
    }
    return { docs }
  }
}

class FakeFirestore {
  readonly data = new Map<string, Record<string, unknown>>()
  lastTransaction: FakeTransaction | null = null
  doc(path: string): FakeReference { return new FakeReference(path, this.data) }
  collection(path: string): FakeQuery {
    assert.equal(path, 'shareLinks')
    return new FakeQuery(this)
  }
  async runTransaction<T>(operation: (transaction: FakeTransaction) => Promise<T>): Promise<T> {
    const transaction = new FakeTransaction(this.data)
    this.lastTransaction = transaction
    return operation(transaction)
  }
}

const shareId = 'a'.repeat(64)

function seedShareLink(
  firestore: FakeFirestore,
  overrides: Record<string, unknown> = {},
): void {
  firestore.data.set(`shareLinks/${shareId}`, {
    documentId: 'doc-1',
    role: 'viewer',
    enabled: true,
    expiresAt: null,
    createdBy: 'owner-1',
    createdAt: new Date('2026-07-26T01:00:00.000Z'),
    ...overrides,
  })
  firestore.data.set('documents/doc-1', { ownerId: 'owner-1' })
}

test('parse lease store performs the callback inside one Firestore transaction', async () => {
  const firestore = new FakeFirestore()
  const store = new FirestoreParseLeaseStore(firestore as never)

  const result = await store.runTransaction('doc-1', (state) => {
    assert.equal(state, null)
    return {
      state: {
        sourceGeneration: 'generation-1',
        status: 'processing' as const,
        leaseExpiresAt: '2026-07-25T06:15:00.000Z',
      },
      result: 'acquired',
    }
  })

  assert.equal(result, 'acquired')
  assert.deepEqual(firestore.data.get('documents/doc-1'), {
    parseLease: {
      sourceGeneration: 'generation-1',
      status: 'processing',
      leaseExpiresAt: '2026-07-25T06:15:00.000Z',
    },
  })
})

test('share-link redemption never downgrades an existing editor', async () => {
  const firestore = new FakeFirestore()
  seedShareLink(firestore, { role: 'viewer' })
  firestore.data.set('documents/doc-1/members/user-1', {
    role: 'editor',
    invitedBy: 'owner-1',
    createdAt: new Date('2026-07-25T00:00:00.000Z'),
  })
  const store = new FirestoreShareLinkStore(firestore as never)

  const result = await store.redeem(shareId, 'user-1', new Date('2026-07-26T02:00:00.000Z'))

  assert.deepEqual(result, { status: 'accepted', documentId: 'doc-1', role: 'editor' })
  assert.equal(firestore.data.get('documents/doc-1/members/user-1')?.role, 'editor')
  assert.deepEqual(firestore.lastTransaction?.writes, [])
})

test('share-link redemption upgrades viewer to editor atomically', async () => {
  const firestore = new FakeFirestore()
  seedShareLink(firestore, { role: 'editor' })
  firestore.data.set('documents/doc-1/members/user-1', {
    role: 'viewer',
    invitedBy: 'owner-1',
    createdAt: new Date('2026-07-25T00:00:00.000Z'),
  })
  const store = new FirestoreShareLinkStore(firestore as never)

  const result = await store.redeem(shareId, 'user-1', new Date('2026-07-26T02:00:00.000Z'))

  assert.deepEqual(result, { status: 'accepted', documentId: 'doc-1', role: 'editor' })
  assert.equal(firestore.data.get('documents/doc-1/members/user-1')?.role, 'editor')
  assert.deepEqual(firestore.lastTransaction?.writes, [{
    operation: 'update',
    path: 'documents/doc-1/members/user-1',
    value: { role: 'editor' },
  }])
})

test('share-link redemption creates a membership and rejects unavailable links', async () => {
  const firestore = new FakeFirestore()
  seedShareLink(firestore)
  const store = new FirestoreShareLinkStore(firestore as never)
  const now = new Date('2026-07-26T02:00:00.000Z')

  assert.deepEqual(await store.redeem(shareId, 'new-user', now), {
    status: 'accepted', documentId: 'doc-1', role: 'viewer',
  })
  assert.deepEqual(firestore.data.get('documents/doc-1/members/new-user'), {
    role: 'viewer', invitedBy: 'owner-1', createdAt: now,
  })

  seedShareLink(firestore, { enabled: false })
  assert.deepEqual(await store.redeem(shareId, 'another-user', now), { status: 'disabled' })
  seedShareLink(firestore, { expiresAt: new Date('2026-07-26T01:59:59.000Z') })
  assert.deepEqual(await store.redeem(shareId, 'another-user', now), { status: 'expired' })
})

test('share-link disable is owner-scoped and idempotent', async () => {
  const firestore = new FakeFirestore()
  seedShareLink(firestore)
  const store = new FirestoreShareLinkStore(firestore as never)

  assert.equal(await store.disable('doc-2', 'owner-1', shareId), false)
  assert.equal(await store.disable('doc-1', 'other-owner', shareId), false)
  assert.equal(await store.disable('doc-1', 'owner-1', shareId), true)
  assert.equal(firestore.data.get(`shareLinks/${shareId}`)?.enabled, false)
  assert.equal(await store.disable('doc-1', 'owner-1', shareId), true)
})

test('Cloud Tasks queue creates an OIDC-authenticated JSON task', async () => {
  const calls: unknown[] = []
  const client = {
    queuePath: (project: string, location: string, queue: string) => `${project}/${location}/${queue}`,
    async createTask(input: unknown): Promise<[{ name: string }]> {
      calls.push(input)
      return [{ name: 'tasks/123' }]
    },
  }
  const queue = new CloudTasksJobQueue(client as never, {
    projectId: 'staging-project',
    location: 'asia-northeast3',
    queue: 'parse-documents',
    targetUrl: 'https://worker.example/parse',
    serviceAccountEmail: 'tasks@staging-project.iam.gserviceaccount.com',
  })

  const job = await queue.enqueue({ documentId: 'doc-1', sourceGeneration: 'generation-1' })

  assert.equal(job.jobId, 'tasks/123')
  const call = calls[0] as { task: { httpRequest: { headers: Record<string, string>; oidcToken: unknown } } }
  assert.equal(call.task.httpRequest.headers['Content-Type'], 'application/json')
  assert.deepEqual(call.task.httpRequest.oidcToken, {
    serviceAccountEmail: 'tasks@staging-project.iam.gserviceaccount.com',
    audience: 'https://worker.example/parse',
  })
})

test('document API environment requires private service URLs and queue configuration', () => {
  const configuration = readDocumentApiEnvironment({
    PORT: '8080',
    GCP_PROJECT_ID: 'staging-project',
    GCP_LOCATION: 'asia-northeast3',
    FIREBASE_STORAGE_BUCKET: 'staging-project.appspot.com',
    PARSE_QUEUE: 'parse-documents',
    PARSE_WORKER_URL: 'https://parse-worker.example/run',
    EXPORT_QUEUE: 'export-documents',
    EXPORT_WORKER_URL: 'https://export-worker.example/run',
    TASKS_SERVICE_ACCOUNT_EMAIL: 'tasks@staging-project.iam.gserviceaccount.com',
    COLLABORATION_FLUSH_URL: 'https://collaboration.example/internal/flush',
  })
  assert.equal(configuration.port, 8080)
  assert.equal(configuration.parseQueue.queue, 'parse-documents')
  assert.throws(() => readDocumentApiEnvironment({}), /GCP_PROJECT_ID/)
})
