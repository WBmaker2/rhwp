import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  FirebaseSnapshotMetadataStore,
  FirebaseSnapshotObjectStore,
  readCollaborationServerEnvironment,
} from '../src/firebase-adapters.js'

class FakeFile {
  bytes: Uint8Array | null = null
  async save(value: Uint8Array): Promise<void> { this.bytes = value.slice() }
  async download(): Promise<[Buffer]> {
    if (!this.bytes) throw Object.assign(new Error('missing'), { code: 404 })
    return [Buffer.from(this.bytes)]
  }
  async delete(): Promise<void> { this.bytes = null }
}

class FakeBucket {
  readonly files = new Map<string, FakeFile>()
  file(path: string): FakeFile {
    const file = this.files.get(path) ?? new FakeFile()
    this.files.set(path, file)
    return file
  }
}

test('snapshot object adapter writes, reads, and deletes exact bytes', async () => {
  const bucket = new FakeBucket()
  const store = new FirebaseSnapshotObjectStore(bucket as never)
  const path = 'documents/doc-1/collaboration/snapshots/1-a.bin'

  await store.write(path, Uint8Array.of(1, 2, 3))
  assert.deepEqual(await store.read(path), Uint8Array.of(1, 2, 3))
  await store.delete(path)
  assert.equal(await store.read(path), null)
})

class FakeSnapshot {
  constructor(readonly exists: boolean, readonly value: Record<string, unknown> = {}) {}
  get(field: string): unknown { return this.value[field] }
}

class FakeDocument {
  data: Record<string, unknown> | null = null
  async get(): Promise<FakeSnapshot> {
    return this.data ? new FakeSnapshot(true, this.data) : new FakeSnapshot(false)
  }
  async set(value: Record<string, unknown>, options: { merge: boolean }): Promise<void> {
    assert.equal(options.merge, true)
    this.data = { ...(this.data ?? {}), ...value }
  }
}

class FakeFirestore {
  readonly documents = new Map<string, FakeDocument>()
  doc(path: string): FakeDocument {
    const document = this.documents.get(path) ?? new FakeDocument()
    this.documents.set(path, document)
    return document
  }
}

test('snapshot metadata adapter publishes the latest path and retained records', async () => {
  const firestore = new FakeFirestore()
  const store = new FirebaseSnapshotMetadataStore(firestore as never)
  const state = {
    latestSnapshotPath: 'documents/doc-1/collaboration/snapshots/1-a.bin',
    snapshots: [{
      path: 'documents/doc-1/collaboration/snapshots/1-a.bin',
      checksum: 'a'.repeat(64),
      createdAt: '2026-07-25T05:00:00.000Z',
      reason: 'debounce' as const,
      sizeBytes: 3,
    }],
  }

  await store.commit('doc-1', state)

  assert.deepEqual(await store.load('doc-1'), state)
  assert.equal(
    firestore.doc('documents/doc-1').data?.latestSnapshotPath,
    state.latestSnapshotPath,
  )
})

test('collaboration environment validates port, bucket, and internal token', () => {
  assert.deepEqual(readCollaborationServerEnvironment({
    PORT: '8080',
    FIREBASE_STORAGE_BUCKET: 'example-staging.appspot.com',
    INTERNAL_API_TOKEN: 'test-internal-token',
  }), {
    port: 8080,
    storageBucket: 'example-staging.appspot.com',
    internalApiToken: 'test-internal-token',
  })
  assert.throws(
    () => readCollaborationServerEnvironment({
      PORT: '0',
      FIREBASE_STORAGE_BUCKET: 'bucket',
      INTERNAL_API_TOKEN: 'token',
    }),
    /PORT/,
  )
  assert.throws(
    () => readCollaborationServerEnvironment({
      PORT: '8080',
      INTERNAL_API_TOKEN: 'token',
    }),
    /FIREBASE_STORAGE_BUCKET/,
  )
  assert.throws(
    () => readCollaborationServerEnvironment({
      PORT: '8080',
      FIREBASE_STORAGE_BUCKET: 'bucket',
    }),
    /INTERNAL_API_TOKEN/,
  )
})
