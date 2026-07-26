import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hashShareToken,
  ShareLinkService,
  type ShareLinkRecord,
  type ShareLinkRedemption,
  type ShareLinkStore,
} from '../src/share-links.js'

const fixedToken = 'abcdefghijklmnopqrstuvwxyzABCDE_1234567890-xyz'
const fixedNow = new Date('2026-07-26T01:00:00.000Z')

class FakeShareLinkStore implements ShareLinkStore {
  created: ShareLinkRecord[] = []
  records: ShareLinkRecord[] = []
  disabled: Array<{ documentId: string; createdBy: string; shareId: string }> = []
  redeemed: Array<{ shareId: string; uid: string; now: Date }> = []
  redemption: ShareLinkRedemption = {
    status: 'accepted',
    documentId: 'doc-1',
    role: 'viewer',
  }

  async create(record: ShareLinkRecord): Promise<void> {
    this.created.push(structuredClone(record))
  }

  async list(documentId: string, createdBy: string): Promise<ShareLinkRecord[]> {
    return this.records.filter((record) => (
      record.documentId === documentId && record.createdBy === createdBy
    ))
  }

  async disable(documentId: string, createdBy: string, shareId: string): Promise<boolean> {
    this.disabled.push({ documentId, createdBy, shareId })
    return true
  }

  async redeem(shareId: string, uid: string, now: Date): Promise<ShareLinkRedemption> {
    this.redeemed.push({ shareId, uid, now })
    return this.redemption
  }
}

function service(store = new FakeShareLinkStore()): {
  store: FakeShareLinkStore
  service: ShareLinkService
} {
  return {
    store,
    service: new ShareLinkService(store, () => fixedNow, () => fixedToken),
  }
}

test('create persists only the token hash and returns the raw token once', async () => {
  const fixture = service()

  const created = await fixture.service.create(
    'doc-1',
    'owner-1',
    'editor',
    '2026-07-27T01:00:00.000Z',
  )

  assert.equal(created.token, fixedToken)
  assert.equal(created.shareId, hashShareToken(fixedToken))
  assert.equal(fixture.store.created.length, 1)
  assert.deepEqual(fixture.store.created[0], {
    shareId: hashShareToken(fixedToken),
    documentId: 'doc-1',
    role: 'editor',
    enabled: true,
    expiresAt: '2026-07-27T01:00:00.000Z',
    createdBy: 'owner-1',
    createdAt: fixedNow.toISOString(),
  })
  assert.equal('token' in fixture.store.created[0]!, false)
})

test('create rejects an expired timestamp or owner role', async () => {
  const fixture = service()

  await assert.rejects(
    fixture.service.create('doc-1', 'owner-1', 'viewer', fixedNow.toISOString()),
    /future/,
  )
  await assert.rejects(
    fixture.service.create('doc-1', 'owner-1', 'owner' as never, null),
    /editor or viewer/,
  )
  assert.equal(fixture.store.created.length, 0)
})

test('list returns owned metadata newest first without adding token fields', async () => {
  const fixture = service()
  fixture.store.records = [
    {
      shareId: 'a'.repeat(64),
      documentId: 'doc-1',
      role: 'viewer',
      enabled: false,
      expiresAt: null,
      createdBy: 'owner-1',
      createdAt: '2026-07-26T00:00:00.000Z',
    },
    {
      shareId: 'b'.repeat(64),
      documentId: 'doc-1',
      role: 'editor',
      enabled: true,
      expiresAt: null,
      createdBy: 'owner-1',
      createdAt: '2026-07-26T00:30:00.000Z',
    },
  ]

  const records = await fixture.service.list('doc-1', 'owner-1')

  assert.deepEqual(records.map((record) => record.shareId), ['b'.repeat(64), 'a'.repeat(64)])
  assert.equal(records.some((record) => 'token' in record), false)
})

test('disable validates identifiers and delegates ownership checks to the store', async () => {
  const fixture = service()
  const shareId = 'c'.repeat(64)

  assert.equal(await fixture.service.disable('doc-1', 'owner-1', shareId), true)
  assert.deepEqual(fixture.store.disabled, [{ documentId: 'doc-1', createdBy: 'owner-1', shareId }])
  await assert.rejects(
    fixture.service.disable('doc-1', 'owner-1', '../bad'),
    /shareId is invalid/,
  )
})

test('redeem hashes the raw token before calling the store', async () => {
  const fixture = service()

  const result = await fixture.service.redeem(fixedToken, 'user-1')

  assert.deepEqual(result, {
    status: 'accepted',
    documentId: 'doc-1',
    role: 'viewer',
  })
  assert.equal(fixture.store.redeemed.length, 1)
  assert.deepEqual(fixture.store.redeemed[0], {
    shareId: hashShareToken(fixedToken),
    uid: 'user-1',
    now: fixedNow,
  })
})
