import assert from 'node:assert/strict'
import test from 'node:test'

import {
  FirestoreWorkerStateStore,
  readDocumentWorkerEnvironment,
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
    private readonly values: Map<string, Record<string, unknown>>,
  ) {
    this.id = path.split('/').at(-1) ?? ''
  }
  async get(): Promise<FakeSnapshot> {
    return new FakeSnapshot(this.id, this.values.get(this.path))
  }
  async set(value: Record<string, unknown>, options: { merge: boolean }): Promise<void> {
    assert.equal(options.merge, true)
    this.values.set(this.path, {
      ...(this.values.get(this.path) ?? {}),
      ...value,
    })
  }
}

class FakeTransaction {
  constructor(private readonly values: Map<string, Record<string, unknown>>) {}
  async get(reference: FakeReference): Promise<FakeSnapshot> {
    return new FakeSnapshot(reference.id, this.values.get(reference.path))
  }
  set(
    reference: FakeReference,
    value: Record<string, unknown>,
    options: { merge: boolean },
  ): void {
    assert.equal(options.merge, true)
    this.values.set(reference.path, {
      ...(this.values.get(reference.path) ?? {}),
      ...value,
    })
  }
}

class FakeFirestore {
  readonly values = new Map<string, Record<string, unknown>>()
  doc(path: string): FakeReference { return new FakeReference(path, this.values) }
  async runTransaction<T>(operation: (transaction: FakeTransaction) => Promise<T>): Promise<T> {
    return operation(new FakeTransaction(this.values))
  }
}

const parsePayload = {
  schemaVersion: 1 as const,
  documentId: 'doc-1',
  sourceGeneration: 'generation-1',
  sourcePath: 'documents/doc-1/source/original.hwp',
}
const exportPayload = {
  schemaVersion: 1 as const,
  documentId: 'doc-1',
  exportId: 'export-1',
  snapshotPath: 'documents/doc-1/collaboration/snapshots/100-checksum.bin',
}
const now = new Date('2026-07-26T02:00:00.000Z')

test('parse claim reuses ready and active processing tasks but reacquires expired leases', async () => {
  const firestore = new FakeFirestore()
  firestore.values.set('documents/doc-1', { ownerId: 'owner-1' })
  const store = new FirestoreWorkerStateStore(firestore as never)
  const key = 'parse:doc-1:generation-1'

  assert.equal(await store.claimParse(parsePayload, key, now), 'acquired')
  assert.equal(await store.claimParse(parsePayload, key, now), 'already-processing')
  firestore.values.set('documents/doc-1', {
    ownerId: 'owner-1',
    parseWorker: {
      taskKey: key,
      status: 'ready',
      leaseExpiresAt: null,
    },
  })
  assert.equal(await store.claimParse(parsePayload, key, now), 'already-ready')
  firestore.values.set('documents/doc-1', {
    ownerId: 'owner-1',
    parseWorker: {
      taskKey: key,
      status: 'processing',
      leaseExpiresAt: new Date(now.getTime() - 1),
    },
  })
  assert.equal(await store.claimParse(parsePayload, key, now), 'acquired')
})

test('parse completion exposes canonical ready state for export', async () => {
  const firestore = new FakeFirestore()
  firestore.values.set('documents/doc-1', { ownerId: 'owner-1' })
  const store = new FirestoreWorkerStateStore(firestore as never)

  await store.completeParse(parsePayload, {
    taskKey: 'parse:doc-1:generation-1',
    sourceFingerprint: 'blake3:fixture',
    manifestPath: 'documents/doc-1/derived/collaboration-manifest.json',
    paragraphCount: 2,
    cellCount: 3,
    completedAt: now,
  })

  assert.deepEqual(await store.getParsedDocument('doc-1'), {
    status: 'ready',
    sourceGeneration: 'generation-1',
    sourceFingerprint: 'blake3:fixture',
    sourcePath: 'documents/doc-1/source/original.hwp',
    manifestPath: 'documents/doc-1/derived/collaboration-manifest.json',
  })
})

test('export claims and completion publish ready metadata and latest export pointer', async () => {
  const firestore = new FakeFirestore()
  firestore.values.set('documents/doc-1', { ownerId: 'owner-1' })
  const store = new FirestoreWorkerStateStore(firestore as never)
  const key = 'export:doc-1:export-1'

  assert.equal(await store.claimExport(exportPayload, key, now), 'acquired')
  assert.equal(await store.claimExport(exportPayload, key, now), 'already-processing')
  await store.completeExport(exportPayload, {
    taskKey: key,
    outputPath: 'documents/doc-1/exports/export-1.hwpx',
    outputBytes: 10,
    updatedParagraphs: 1,
    updatedCells: 2,
    completedAt: now,
  })
  assert.equal(
    firestore.values.get('documents/doc-1/exports/export-1')?.status,
    'ready',
  )
  assert.equal(
    firestore.values.get('documents/doc-1')?.latestExportPath,
    'documents/doc-1/exports/export-1.hwpx',
  )
  assert.equal(await store.claimExport(exportPayload, key, now), 'already-ready')
})

test('worker environment requires bucket and native binary path', () => {
  assert.deepEqual(readDocumentWorkerEnvironment({
    PORT: '8080',
    FIREBASE_STORAGE_BUCKET: 'staging.appspot.com',
    RHWP_COLLABORATION_WORKER_BIN: '/usr/local/bin/rhwp-collaboration-worker',
    ALLOW_EMULATOR_TASKS: 'true',
  }), {
    port: 8080,
    storageBucket: 'staging.appspot.com',
    nativeBinaryPath: '/usr/local/bin/rhwp-collaboration-worker',
    allowEmulatorTasks: true,
  })
  assert.throws(() => readDocumentWorkerEnvironment({}), /FIREBASE_STORAGE_BUCKET/)
})
