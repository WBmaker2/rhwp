import assert from 'node:assert/strict'
import test from 'node:test'

import { DirectHttpJobQueue } from '../src/direct-job-queue.js'

test('direct worker queue posts JSON only to localhost', async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const queue = new DirectHttpJobQueue(
    'http://127.0.0.1:8093/run/parse',
    async (input, init) => {
      calls.push({ url: String(input), init: init ?? {} })
      return new Response(JSON.stringify({ status: 'ready' }), { status: 200 })
    },
  )

  const result = await queue.enqueue({ schemaVersion: 1, documentId: 'doc-1' })

  assert.match(result.jobId, /^emulator-/)
  assert.equal(calls[0]?.url, 'http://127.0.0.1:8093/run/parse')
  assert.equal((calls[0]?.init.headers as Record<string, string>)['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(String(calls[0]?.init.body)), {
    schemaVersion: 1,
    documentId: 'doc-1',
  })
})

test('direct worker queue rejects non-local and HTTPS targets', () => {
  assert.throws(
    () => new DirectHttpJobQueue('https://worker.example/run'),
    /localhost/,
  )
  assert.throws(
    () => new DirectHttpJobQueue('http://worker.example/run'),
    /localhost/,
  )
})

test('direct worker queue surfaces failed worker responses', async () => {
  const queue = new DirectHttpJobQueue(
    'http://localhost:8093/run/export',
    async () => new Response('worker-failed', { status: 500 }),
  )
  await assert.rejects(queue.enqueue({}), /HTTP 500 worker-failed/)
})
