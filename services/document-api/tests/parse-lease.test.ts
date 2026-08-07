import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ParseLease,
  type ParseLeaseState,
  type ParseLeaseStore,
} from '../src/parse-lease.js'

class MemoryLeaseStore implements ParseLeaseStore {
  readonly records = new Map<string, ParseLeaseState>()

  async runTransaction<T>(
    documentId: string,
    operation: (
      current: ParseLeaseState | null,
    ) => { state: ParseLeaseState; result: T },
  ): Promise<T> {
    const current = this.records.get(documentId) ?? null
    const mutation = operation(current ? structuredClone(current) : null)
    this.records.set(documentId, structuredClone(mutation.state))
    return mutation.result
  }
}

test('acquires once per source generation and rejects a duplicate active parse', async () => {
  const store = new MemoryLeaseStore()
  const lease = new ParseLease(store, { leaseDurationMs: 5 * 60 * 1_000 })
  const now = new Date('2026-07-25T02:00:00.000Z')

  const first = await lease.acquire('doc-1', 'generation-7', now)
  const second = await lease.acquire('doc-1', 'generation-7', now)

  assert.deepEqual(first, {
    acquired: true,
    expiresAt: '2026-07-25T02:05:00.000Z',
  })
  assert.deepEqual(second, {
    acquired: false,
    reason: 'already-processing',
  })
})

test('allows the same source generation to be retried after the lease expires', async () => {
  const store = new MemoryLeaseStore()
  const lease = new ParseLease(store, { leaseDurationMs: 60_000 })

  assert.equal(
    (await lease.acquire(
      'doc-1',
      'generation-7',
      new Date('2026-07-25T02:00:00.000Z'),
    )).acquired,
    true,
  )
  assert.equal(
    (await lease.acquire(
      'doc-1',
      'generation-7',
      new Date('2026-07-25T02:01:00.001Z'),
    )).acquired,
    true,
  )
})
