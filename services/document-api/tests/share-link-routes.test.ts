import assert from 'node:assert/strict'
import test from 'node:test'

import { createShareLinkHandlers } from '../src/routes/share-links.js'
import type { ShareLinkRecord, ShareLinkRedemption } from '../src/share-links.js'

const authorization = 'Bearer valid-token'

function managementRequest(body: unknown = null) {
  return {
    params: { documentId: 'doc-1' },
    headers: {
      authorization,
      'content-type': 'application/json',
    },
    body,
  }
}

function dependencies(role: 'owner' | 'editor' | 'viewer' | null = 'owner') {
  const calls = {
    create: [] as unknown[][],
    list: [] as unknown[][],
    disable: [] as unknown[][],
    redeem: [] as unknown[][],
  }
  const links: ShareLinkRecord[] = [{
    shareId: 'a'.repeat(64),
    documentId: 'doc-1',
    role: 'viewer',
    enabled: true,
    expiresAt: null,
    createdBy: 'owner-1',
    createdAt: '2026-07-26T01:00:00.000Z',
  }]
  let redemption: ShareLinkRedemption = {
    status: 'accepted',
    documentId: 'doc-1',
    role: 'viewer',
  }
  const handlers = createShareLinkHandlers({
    auth: {
      async verifyIdToken(token) {
        assert.equal(token, 'valid-token')
        return { uid: 'owner-1' }
      },
    },
    members: {
      async getRole() {
        return role
      },
    },
    shareLinks: {
      async create(...args) {
        calls.create.push(args)
        return {
          shareId: 'a'.repeat(64),
          token: 'raw-token-returned-once',
          role: 'viewer',
          expiresAt: null,
          createdAt: '2026-07-26T01:00:00.000Z',
        }
      },
      async list(...args) {
        calls.list.push(args)
        return links
      },
      async disable(...args) {
        calls.disable.push(args)
        return true
      },
      async redeem(...args) {
        calls.redeem.push(args)
        return redemption
      },
    },
  })
  return {
    handlers,
    calls,
    setRedemption(value: ShareLinkRedemption) {
      redemption = value
    },
  }
}

test('owner creates a viewer link and receives the raw token once', async () => {
  const fixture = dependencies()

  const result = await fixture.handlers.create(managementRequest({ role: 'viewer' }))

  assert.equal(result.status, 201)
  assert.equal(result.body.token, 'raw-token-returned-once')
  assert.deepEqual(fixture.calls.create, [['doc-1', 'owner-1', 'viewer', null]])
})

test('non-owner cannot manage links and invalid input is rejected', async () => {
  const editor = dependencies('editor')
  assert.equal(
    (await editor.handlers.create(managementRequest({ role: 'viewer' }))).status,
    403,
  )
  assert.equal(editor.calls.create.length, 0)

  const owner = dependencies()
  assert.equal(
    (await owner.handlers.create(managementRequest({ role: 'owner' }))).status,
    400,
  )
  assert.equal(
    (await owner.handlers.create(managementRequest({ role: 'viewer', unexpected: true }))).status,
    400,
  )
})

test('list returns public metadata without raw token or creator UID', async () => {
  const fixture = dependencies()

  const result = await fixture.handlers.list(managementRequest())

  assert.equal(result.status, 200)
  const links = result.body.links as Array<Record<string, unknown>>
  assert.deepEqual(links, [{
    shareId: 'a'.repeat(64),
    role: 'viewer',
    enabled: true,
    expiresAt: null,
    createdAt: '2026-07-26T01:00:00.000Z',
  }])
  assert.equal('token' in links[0]!, false)
  assert.equal('createdBy' in links[0]!, false)
})

test('owner disables one link by document and share ID', async () => {
  const fixture = dependencies()
  const shareId = 'b'.repeat(64)

  const result = await fixture.handlers.disable(managementRequest(), shareId)

  assert.deepEqual(result, { status: 200, body: { status: 'disabled' } })
  assert.deepEqual(fixture.calls.disable, [['doc-1', 'owner-1', shareId]])
})

test('authenticated user redeems a link and receives document membership', async () => {
  const fixture = dependencies()
  const request = {
    headers: { authorization, 'content-type': 'application/json' },
    body: { token: 'a'.repeat(43) },
  }

  const accepted = await fixture.handlers.redeem(request)
  assert.deepEqual(accepted, {
    status: 200,
    body: { status: 'accepted', documentId: 'doc-1', role: 'viewer' },
  })
  assert.deepEqual(fixture.calls.redeem, [['a'.repeat(43), 'owner-1']])

  fixture.setRedemption({ status: 'expired' })
  assert.deepEqual(await fixture.handlers.redeem(request), {
    status: 410,
    body: { error: 'share-link-expired' },
  })
})

test('share-link handlers require Firebase bearer authentication', async () => {
  const fixture = dependencies()
  const request = managementRequest({ role: 'viewer' })
  request.headers.authorization = ''

  assert.equal((await fixture.handlers.create(request)).status, 401)
  assert.equal((await fixture.handlers.list(request)).status, 401)
  assert.equal((await fixture.handlers.disable(request, 'a'.repeat(64))).status, 401)
  assert.equal((await fixture.handlers.redeem({ headers: request.headers, body: { token: 'a'.repeat(43) } })).status, 401)
})
