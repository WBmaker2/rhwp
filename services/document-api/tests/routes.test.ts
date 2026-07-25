import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createCompleteUploadHandler,
  type CompleteUploadDependencies,
} from '../src/routes/complete-upload.js'
import {
  createExportHwpxHandler,
  type ExportHwpxDependencies,
} from '../src/routes/export-hwpx.js'

const mib = 1024 * 1024

function request(
  authorization = 'Bearer valid-token',
  contentType = 'application/json',
) {
  return {
    params: { documentId: 'doc-1' },
    headers: {
      authorization,
      'content-type': contentType,
    },
    body: {},
  }
}

function completeUploadDependencies(
  overrides: Partial<CompleteUploadDependencies> = {},
): CompleteUploadDependencies {
  return {
    auth: {
      async verifyIdToken() {
        return { uid: 'user-1' }
      },
    },
    members: {
      async getRole() {
        return 'editor'
      },
    },
    objects: {
      async stat() {
        return {
          sizeBytes: 100 * mib,
          generation: 'generation-7',
          contentType: 'application/x-hwp',
        }
      },
    },
    lease: {
      async acquire() {
        return {
          acquired: true,
          expiresAt: '2026-07-25T02:05:00.000Z',
        }
      },
    },
    parseJobs: {
      async enqueue() {},
    },
    now: () => new Date('2026-07-25T02:00:00.000Z'),
    ...overrides,
  }
}

test('complete-upload rejects a missing Firebase bearer token', async () => {
  const handler = createCompleteUploadHandler(completeUploadDependencies())

  const response = await handler(request(''))

  assert.equal(response.status, 401)
})

test('complete-upload rejects a user without document membership', async () => {
  const handler = createCompleteUploadHandler(
    completeUploadDependencies({
      members: {
        async getRole() {
          return null
        },
      },
    }),
  )

  const response = await handler(request())

  assert.equal(response.status, 403)
})

test('complete-upload rejects a non-JSON request body', async () => {
  const handler = createCompleteUploadHandler(completeUploadDependencies())

  const response = await handler(request('Bearer valid-token', 'text/plain'))

  assert.equal(response.status, 415)
})

test('complete-upload rejects source objects outside the 100 to 200 MiB V1 range', async () => {
  const handler = createCompleteUploadHandler(
    completeUploadDependencies({
      objects: {
        async stat() {
          return {
            sizeBytes: 99 * mib,
            generation: 'generation-7',
            contentType: 'application/x-hwp',
          }
        },
      },
    }),
  )

  const response = await handler(request())

  assert.equal(response.status, 422)
})

test('duplicate upload completion does not enqueue a second parse', async () => {
  let leaseCalls = 0
  let parseStarts = 0
  const handler = createCompleteUploadHandler(
    completeUploadDependencies({
      lease: {
        async acquire() {
          leaseCalls += 1
          return leaseCalls === 1
            ? {
                acquired: true,
                expiresAt: '2026-07-25T02:05:00.000Z',
              }
            : {
                acquired: false,
                reason: 'already-processing',
              }
        },
      },
      parseJobs: {
        async enqueue() {
          parseStarts += 1
        },
      },
    }),
  )

  const first = await handler(request())
  const second = await handler(request())

  assert.equal(first.status, 202)
  assert.equal(second.status, 202)
  assert.equal(parseStarts, 1)
})

test('viewer cannot request an HWPX export', async () => {
  let flushCalls = 0
  let exportStarts = 0
  const dependencies: ExportHwpxDependencies = {
    auth: {
      async verifyIdToken() {
        return { uid: 'viewer-1' }
      },
    },
    members: {
      async getRole() {
        return 'viewer'
      },
    },
    collaboration: {
      async flushForExport() {
        flushCalls += 1
        return { path: 'snapshot.bin' }
      },
    },
    exportJobs: {
      async enqueue() {
        exportStarts += 1
        return { jobId: 'export-1' }
      },
    },
  }
  const handler = createExportHwpxHandler(dependencies)

  const response = await handler(request())

  assert.equal(response.status, 403)
  assert.equal(flushCalls, 0)
  assert.equal(exportStarts, 0)
})
