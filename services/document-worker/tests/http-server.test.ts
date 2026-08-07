import assert from 'node:assert/strict'
import test from 'node:test'

import { dispatchWorkerRequest } from '../src/http-server.js'

const parsePayload = {
  schemaVersion: 1,
  documentId: 'doc-1',
  sourceGeneration: 'generation-1',
  sourcePath: 'documents/doc-1/source/original.hwp',
}
const exportPayload = {
  schemaVersion: 1,
  documentId: 'doc-1',
  exportId: 'export-1',
  snapshotPath: 'documents/doc-1/collaboration/snapshots/100-checksum.bin',
}

function headers(includeTask = true) {
  return {
    'content-type': 'application/json',
    ...(includeTask ? { 'x-cloudtasks-taskname': 'projects/p/locations/l/queues/q/tasks/t' } : {}),
  }
}

test('dispatches health, parse, and export tasks', async () => {
  const calls: unknown[] = []
  const worker = {
    async parse(body: unknown) {
      calls.push(['parse', body])
      return { status: 'ready' as const, path: 'manifest.json' }
    },
    async export(body: unknown) {
      calls.push(['export', body])
      return { status: 'already-ready' as const }
    },
  }

  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'GET', url: '/healthz', headers: {}, body: null,
  }), { status: 200, body: { status: 'ok' } })
  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse', headers: headers(), body: parsePayload,
  }), { status: 200, body: { status: 'ready', path: 'manifest.json' } })
  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/export', headers: headers(), body: exportPayload,
  }), { status: 200, body: { status: 'already-ready' } })
  assert.deepEqual(calls, [['parse', parsePayload], ['export', exportPayload]])
})

test('requires Cloud Tasks identity outside emulator mode', async () => {
  const worker = {
    async parse() { throw new Error('must not run') },
    async export() { throw new Error('must not run') },
  }

  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse', headers: headers(false), body: parsePayload,
  }), { status: 401, body: { error: 'cloud-task-header-required' } })
  assert.equal((await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse', headers: headers(false), body: parsePayload,
  }, { allowEmulatorTasks: true })).status, 500)
})

test('returns 400 for invalid task contracts and 500 for retryable worker failures', async () => {
  const worker = {
    async parse(body: unknown) {
      if (body === parsePayload) throw new Error('transient storage failure')
      throw new Error('schemaVersion must be 1')
    },
    async export() { return { status: 'ready' as const } },
  }

  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse', headers: headers(), body: {},
  }), { status: 400, body: { error: 'schemaVersion must be 1' } })
  assert.deepEqual(await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse', headers: headers(), body: parsePayload,
  }), { status: 500, body: { error: 'worker-failed' } })
})

test('rejects unsupported media types and unknown routes', async () => {
  const worker = {
    async parse() { return { status: 'ready' as const } },
    async export() { return { status: 'ready' as const } },
  }
  assert.equal((await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/run/parse',
    headers: { ...headers(), 'content-type': 'text/plain' }, body: parsePayload,
  })).status, 415)
  assert.equal((await dispatchWorkerRequest(worker as never, {
    method: 'POST', url: '/unknown', headers: headers(), body: parsePayload,
  })).status, 404)
})
