import assert from 'node:assert/strict'
import { test } from 'node:test'

import * as Y from 'yjs'

import { ParticipantRegistry } from '../../collaboration-server/src/participants.js'
import {
  SnapshotStore,
  type SnapshotDocumentState,
  type SnapshotMetadataStore,
  type SnapshotObjectStore,
} from '../../collaboration-server/src/persistence.js'
import { ParseLease, type ParseLeaseState, type ParseLeaseStore } from '../../document-api/src/parse-lease.js'
import { createCompleteUploadHandler } from '../../document-api/src/routes/complete-upload.js'
import { createExportHwpxHandler } from '../../document-api/src/routes/export-hwpx.js'

class MemoryLeaseStore implements ParseLeaseStore {
  state: ParseLeaseState | null = null
  async runTransaction<T>(
    _documentId: string,
    operation: (current: ParseLeaseState | null) => { state: ParseLeaseState; result: T },
  ): Promise<T> {
    const next = operation(this.state)
    this.state = next.state
    return next.result
  }
}

test('upload completion is idempotent and queues one parse job', async () => {
  const store = new MemoryLeaseStore()
  let queued = 0
  const handler = createCompleteUploadHandler({
    auth: { verifyIdToken: async () => ({ uid: 'owner-1' }) },
    members: { getRole: async () => 'owner' },
    objects: {
      stat: async () => ({
        sizeBytes: 100 * 1024 * 1024,
        generation: 'generation-1',
        contentType: 'application/x-hwp',
      }),
    },
    lease: new ParseLease(store),
    parseJobs: { enqueue: async () => { queued += 1 } },
    now: () => new Date('2026-07-25T06:00:00.000Z'),
  })
  const request = {
    params: { documentId: 'doc-1' },
    headers: { authorization: 'Bearer token', 'content-type': 'application/json' },
    body: {},
  }

  assert.equal((await handler(request)).body.status, 'processing')
  assert.equal((await handler(request)).body.status, 'already-processing')
  assert.equal(queued, 1)
})

test('two editors converge while participant accounting counts unique UIDs', () => {
  const first = new Y.Doc()
  const second = new Y.Doc()
  first.getText('paragraph:1').insert(0, '첫 번째 편집')
  Y.applyUpdate(second, Y.encodeStateAsUpdate(first))
  second.getText('paragraph:1').insert(second.getText('paragraph:1').length, ' + 두 번째 편집')
  Y.applyUpdate(first, Y.encodeStateAsUpdate(second))

  assert.equal(first.getText('paragraph:1').toString(), second.getText('paragraph:1').toString())

  const participants = new ParticipantRegistry(10)
  assert.deepEqual(participants.tryJoin('doc-1', 'uid-1', 'tab-1'), {
    accepted: true, uniqueUsers: 1,
  })
  assert.deepEqual(participants.tryJoin('doc-1', 'uid-1', 'tab-2'), {
    accepted: true, uniqueUsers: 1,
  })
  for (let index = 2; index <= 10; index += 1) {
    assert.equal(participants.tryJoin('doc-1', `uid-${index}`, `tab-${index}`).accepted, true)
  }
  assert.deepEqual(participants.tryJoin('doc-1', 'uid-11', 'tab-11'), {
    accepted: false, reason: 'participant-limit', uniqueUsers: 10,
  })
})

class MemoryObjects implements SnapshotObjectStore {
  readonly values = new Map<string, Uint8Array>()
  async write(path: string, value: Uint8Array): Promise<void> { this.values.set(path, value.slice()) }
  async read(path: string): Promise<Uint8Array | null> { return this.values.get(path)?.slice() ?? null }
  async delete(path: string): Promise<void> { this.values.delete(path) }
}

class MemoryMetadata implements SnapshotMetadataStore {
  state: SnapshotDocumentState | null = null
  async load(): Promise<SnapshotDocumentState | null> {
    return this.state ? structuredClone(this.state) : null
  }
  async commit(_documentId: string, state: SnapshotDocumentState): Promise<void> {
    this.state = structuredClone(state)
  }
}

test('a restarted snapshot repository falls back when the latest object is corrupt', async () => {
  const objects = new MemoryObjects()
  const metadata = new MemoryMetadata()
  let now = new Date('2026-07-25T06:00:00.000Z')
  const firstProcess = new SnapshotStore(objects, metadata, { now: () => now })
  const first = await firstProcess.save('doc-1', Uint8Array.of(1, 2, 3), 'debounce')
  now = new Date('2026-07-25T06:01:00.000Z')
  const latest = await firstProcess.save('doc-1', Uint8Array.of(4, 5, 6), 'last-user')
  objects.values.set(latest.path, Uint8Array.of(9, 9, 9))

  const restartedProcess = new SnapshotStore(objects, metadata)
  assert.deepEqual(await restartedProcess.load('doc-1'), Uint8Array.of(1, 2, 3))
  assert.equal(metadata.state?.snapshots[1]?.path, first.path)
})

test('export authorization rejects viewers and flushes before queueing for editors', async () => {
  const order: string[] = []
  const viewer = createExportHwpxHandler({
    auth: { verifyIdToken: async () => ({ uid: 'viewer-1' }) },
    members: { getRole: async () => 'viewer' },
    collaboration: { flushForExport: async () => { order.push('flush'); return { path: 'x' } } },
    exportJobs: { enqueue: async () => { order.push('queue'); return { jobId: 'export-1' } } },
  })
  const request = {
    params: { documentId: 'doc-1' },
    headers: { authorization: 'Bearer token', 'content-type': 'application/json' },
    body: {},
  }
  assert.equal((await viewer(request)).status, 403)
  assert.deepEqual(order, [])

  const editor = createExportHwpxHandler({
    auth: { verifyIdToken: async () => ({ uid: 'editor-1' }) },
    members: { getRole: async () => 'editor' },
    collaboration: {
      flushForExport: async () => {
        order.push('flush')
        return { path: 'documents/doc-1/collaboration/snapshots/1-a.bin' }
      },
    },
    exportJobs: {
      enqueue: async () => {
        order.push('queue')
        return { jobId: 'export-1' }
      },
    },
  })
  const response = await editor(request)
  assert.equal(response.status, 202)
  assert.deepEqual(order, ['flush', 'queue'])
  assert.equal(response.body.outputPath, 'documents/doc-1/exports/export-1.hwpx')
})
