import assert from 'node:assert/strict'
import { test } from 'node:test'

import * as Y from 'yjs'

import { ParticipantRegistry } from '../../collaboration-server/src/participants.js'
import {
  SnapshotStore,
  YjsSnapshotPersistence,
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

const apiRequest = {
  params: { documentId: 'doc-1' },
  headers: { authorization: 'Bearer token', 'content-type': 'application/json' },
  body: {},
}

test('upload, collaborate, snapshot, restart, recover, and flush export as one flow', async () => {
  const leaseStore = new MemoryLeaseStore()
  let parseJobs = 0
  const parsePayloads: unknown[] = []
  const completeUpload = createCompleteUploadHandler({
    auth: { verifyIdToken: async () => ({ uid: 'owner-1' }) },
    members: { getRole: async () => 'owner' },
    objects: {
      stat: async () => ({
        sizeBytes: 100 * 1024 * 1024,
        generation: 'generation-1',
        contentType: 'application/x-hwp',
      }),
    },
    lease: new ParseLease(leaseStore),
    parseJobs: {
      enqueue: async (input) => {
        parseJobs += 1
        parsePayloads.push(input)
      },
    },
    now: () => new Date('2026-07-25T06:00:00.000Z'),
  })

  assert.equal((await completeUpload(apiRequest)).body.status, 'processing')
  assert.equal((await completeUpload(apiRequest)).body.status, 'already-processing')
  assert.equal(parseJobs, 1)
  assert.deepEqual(parsePayloads, [{
    schemaVersion: 1,
    documentId: 'doc-1',
    sourceGeneration: 'generation-1',
    sourcePath: 'documents/doc-1/source/original.hwp',
  }])

  const editorA = new Y.Doc()
  const editorB = new Y.Doc()
  editorA.getText('paragraph:paragraph-1').insert(0, '공동 편집 복구 본문')
  editorA.getText('cell:cell-1').insert(0, '공동 편집 복구 셀')
  Y.applyUpdate(editorB, Y.encodeStateAsUpdate(editorA))
  editorB.getText('paragraph:paragraph-1').insert(
    editorB.getText('paragraph:paragraph-1').length,
    ' + 동시 편집',
  )
  Y.applyUpdate(editorA, Y.encodeStateAsUpdate(editorB))
  assert.equal(
    editorA.getText('paragraph:paragraph-1').toString(),
    editorB.getText('paragraph:paragraph-1').toString(),
  )

  const objects = new MemoryObjects()
  const metadata = new MemoryMetadata()
  let now = new Date('2026-07-25T06:01:00.000Z')
  const firstRepository = new SnapshotStore(objects, metadata, { now: () => now })
  const firstProcess = new YjsSnapshotPersistence(firstRepository)
  const valid = await firstProcess.save('doc-1', editorA, 'debounce')

  editorA.getText('paragraph:paragraph-1').insert(
    editorA.getText('paragraph:paragraph-1').length,
    ' + 손상될 최신 변경',
  )
  now = new Date('2026-07-25T06:02:00.000Z')
  const corrupt = await firstProcess.save('doc-1', editorA, 'last-user')
  objects.values.set(corrupt.path, Uint8Array.of(9, 9, 9))

  const restartedRepository = new SnapshotStore(objects, metadata, {
    now: () => new Date('2026-07-25T06:03:00.000Z'),
  })
  const recoveredUpdate = await restartedRepository.load('doc-1')
  assert(recoveredUpdate)
  const recovered = new Y.Doc()
  Y.applyUpdate(recovered, recoveredUpdate)
  assert.equal(
    recovered.getText('paragraph:paragraph-1').toString(),
    '공동 편집 복구 본문 + 동시 편집',
  )
  assert.equal(recovered.getText('cell:cell-1').toString(), '공동 편집 복구 셀')
  assert.equal(metadata.state?.snapshots[1]?.path, valid.path)

  const restartedPersistence = new YjsSnapshotPersistence(restartedRepository)
  restartedPersistence.register('doc-1', recovered)
  const order: string[] = []
  let exportedSnapshotPath = ''
  const exportPayloads: unknown[] = []
  const exportHwpx = createExportHwpxHandler({
    auth: { verifyIdToken: async () => ({ uid: 'editor-1' }) },
    members: { getRole: async () => 'editor' },
    collaboration: {
      flushForExport: async (documentId) => {
        order.push('flush')
        const snapshot = await restartedPersistence.flushForExport(documentId)
        exportedSnapshotPath = snapshot?.path ?? ''
        return snapshot
      },
    },
    exportJobs: {
      enqueue: async (input) => {
        order.push('queue')
        exportPayloads.push(input)
        assert.equal(input.snapshotPath, exportedSnapshotPath)
        return { jobId: 'projects/p/locations/l/queues/q/tasks/export-task-1' }
      },
    },
    createExportId: () => 'export-1',
  })

  const exportResponse = await exportHwpx(apiRequest)
  assert.equal(exportResponse.status, 202)
  assert.deepEqual(order, ['flush', 'queue'])
  assert.match(exportedSnapshotPath, /\/collaboration\/snapshots\//)
  assert.deepEqual(exportPayloads, [{
    schemaVersion: 1,
    documentId: 'doc-1',
    exportId: 'export-1',
    snapshotPath: exportedSnapshotPath,
  }])
  assert.equal(exportResponse.body.outputPath, 'documents/doc-1/exports/export-1.hwpx')
})

test('viewer export is rejected before flush and queue', async () => {
  const order: string[] = []
  const handler = createExportHwpxHandler({
    auth: { verifyIdToken: async () => ({ uid: 'viewer-1' }) },
    members: { getRole: async () => 'viewer' },
    collaboration: { flushForExport: async () => { order.push('flush'); return { path: 'x' } } },
    exportJobs: { enqueue: async () => { order.push('queue'); return { jobId: 'export-1' } } },
  })

  assert.equal((await handler(apiRequest)).status, 403)
  assert.deepEqual(order, [])
})

test('participant accounting counts tabs by UID and rejects the eleventh unique user', () => {
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
