import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SnapshotStore,
  type SnapshotDocumentState,
  type SnapshotMetadataStore,
  type SnapshotObjectStore,
} from '../src/persistence.js'

class MemoryObjects implements SnapshotObjectStore {
  readonly values = new Map<string, Uint8Array>()
  readonly events: string[]

  constructor(events: string[] = []) {
    this.events = events
  }

  async write(path: string, value: Uint8Array): Promise<void> {
    this.events.push(`object:${path}`)
    this.values.set(path, value.slice())
  }

  async read(path: string): Promise<Uint8Array | null> {
    const value = this.values.get(path)
    return value?.slice() ?? null
  }

  async delete(path: string): Promise<void> {
    this.values.delete(path)
  }

  corrupt(path: string): void {
    this.values.set(path, Uint8Array.of(0xff, 0x00, 0xff))
  }
}

class MemoryDocuments implements SnapshotMetadataStore {
  readonly values = new Map<string, SnapshotDocumentState>()
  readonly events: string[]

  constructor(events: string[] = []) {
    this.events = events
  }

  async load(documentId: string): Promise<SnapshotDocumentState | null> {
    return structuredClone(this.values.get(documentId) ?? null)
  }

  async commit(
    documentId: string,
    state: SnapshotDocumentState,
  ): Promise<void> {
    this.events.push(`metadata:${documentId}`)
    this.values.set(documentId, structuredClone(state))
  }
}

function sequenceClock(start = Date.UTC(2026, 6, 25)): () => Date {
  let offset = 0
  return () => new Date(start + offset++ * 1_000)
}

test('writes the object before atomically publishing the latest snapshot', async () => {
  const events: string[] = []
  const objects = new MemoryObjects(events)
  const documents = new MemoryDocuments(events)
  const store = new SnapshotStore(objects, documents, {
    now: sequenceClock(),
  })
  const update = Uint8Array.of(1, 2, 3, 4)

  const record = await store.save('doc-1', update, 'debounce')

  assert.match(
    record.path,
    /^documents\/doc-1\/collaboration\/snapshots\/\d+-[a-f0-9]{64}\.bin$/,
  )
  assert.equal(record.reason, 'debounce')
  assert.equal(record.sizeBytes, update.byteLength)
  assert.equal(events[0], `object:${record.path}`)
  assert.equal(events[1], 'metadata:doc-1')
  assert.deepEqual(await store.load('doc-1'), update)

  const metadata = await documents.load('doc-1')
  assert.equal(metadata?.latestSnapshotPath, record.path)
  assert.deepEqual(metadata?.snapshots, [record])
})

test('falls back to the previous valid snapshot when the latest is corrupt', async () => {
  const objects = new MemoryObjects()
  const documents = new MemoryDocuments()
  const store = new SnapshotStore(objects, documents, {
    now: sequenceClock(),
  })
  const previous = Uint8Array.of(10, 20, 30)
  const latest = Uint8Array.of(40, 50, 60)

  await store.save('doc-1', previous, 'debounce')
  const latestRecord = await store.save('doc-1', latest, 'size-threshold')
  objects.corrupt(latestRecord.path)

  assert.deepEqual(await store.load('doc-1'), previous)
})

test('retains only the ten newest snapshots and deletes older objects', async () => {
  const objects = new MemoryObjects()
  const documents = new MemoryDocuments()
  const store = new SnapshotStore(objects, documents, {
    now: sequenceClock(),
    maxSnapshots: 10,
  })
  const paths: string[] = []

  for (let index = 0; index < 11; index += 1) {
    const record = await store.save(
      'doc-1',
      Uint8Array.of(index),
      index === 10 ? 'export' : 'debounce',
    )
    paths.push(record.path)
  }

  const metadata = await documents.load('doc-1')
  assert.equal(metadata?.snapshots.length, 10)
  assert.equal(metadata?.latestSnapshotPath, paths[10])
  assert.equal(objects.values.has(paths[0] ?? ''), false)
  assert.equal(objects.values.size, 10)
  assert.deepEqual(await store.load('doc-1'), Uint8Array.of(10))
})

test('returns null when no valid recorded snapshot exists', async () => {
  const objects = new MemoryObjects()
  const documents = new MemoryDocuments()
  const store = new SnapshotStore(objects, documents)

  assert.equal(await store.load('missing-document'), null)
})
