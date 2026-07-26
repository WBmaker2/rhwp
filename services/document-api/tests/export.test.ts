import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createExportHwpxHandler,
  type ExportHwpxDependencies,
} from '../src/routes/export-hwpx.js'

test('flushes collaboration state before queuing a versioned HWPX export task', async () => {
  const events: string[] = []
  const payloads: unknown[] = []
  const dependencies: ExportHwpxDependencies = {
    auth: {
      async verifyIdToken() {
        return { uid: 'editor-1' }
      },
    },
    members: {
      async getRole() {
        return 'editor'
      },
    },
    collaboration: {
      async flushForExport(documentId) {
        events.push(`flush:${documentId}`)
        return {
          path: 'documents/doc-1/collaboration/snapshots/1-checksum.bin',
        }
      },
    },
    exportJobs: {
      async enqueue(input) {
        events.push(`enqueue:${input.snapshotPath}`)
        payloads.push(input)
        return { jobId: 'projects/p/locations/l/queues/q/tasks/task-7' }
      },
    },
    createExportId: () => 'export-7',
  }
  const handler = createExportHwpxHandler(dependencies)

  const response = await handler({
    params: { documentId: 'doc-1' },
    headers: {
      authorization: 'Bearer valid-token',
      'content-type': 'application/json',
    },
    body: {},
  })

  assert.equal(response.status, 202)
  assert.deepEqual(events, [
    'flush:doc-1',
    'enqueue:documents/doc-1/collaboration/snapshots/1-checksum.bin',
  ])
  assert.deepEqual(payloads, [{
    schemaVersion: 1,
    documentId: 'doc-1',
    exportId: 'export-7',
    snapshotPath: 'documents/doc-1/collaboration/snapshots/1-checksum.bin',
  }])
  assert.deepEqual(response.body, {
    status: 'queued',
    jobId: 'projects/p/locations/l/queues/q/tasks/task-7',
    exportId: 'export-7',
    outputPath: 'documents/doc-1/exports/export-7.hwpx',
  })
})
