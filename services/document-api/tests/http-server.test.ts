import assert from 'node:assert/strict'
import { test } from 'node:test'

import { dispatchDocumentApiRequest } from '../src/http-server.js'

const handlers = {
  async completeUpload(request: { params: { documentId: string } }) {
    return { status: 202, body: { route: 'complete', documentId: request.params.documentId } }
  },
  async exportHwpx(request: { params: { documentId: string } }) {
    return { status: 202, body: { route: 'export', documentId: request.params.documentId } }
  },
  shareLinks: {
    async create(request: { params: { documentId: string } }) {
      return { status: 201, body: { route: 'share-create', documentId: request.params.documentId } }
    },
    async list(request: { params: { documentId: string } }) {
      return { status: 200, body: { route: 'share-list', documentId: request.params.documentId } }
    },
    async disable(request: { params: { documentId: string } }, shareId: string) {
      return {
        status: 200,
        body: { route: 'share-disable', documentId: request.params.documentId, shareId },
      }
    },
    async redeem() {
      return { status: 200, body: { route: 'share-redeem' } }
    },
  },
}

test('dispatches health, document, share-link, and missing routes', async () => {
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'GET', url: '/healthz', headers: {}, body: null,
  }), { status: 200, body: { status: 'ok' } })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'POST', url: '/v1/documents/doc-1/complete-upload',
    headers: { 'content-type': 'application/json' }, body: {},
  }), { status: 202, body: { route: 'complete', documentId: 'doc-1' } })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'POST', url: '/v1/documents/doc-1/export-hwpx',
    headers: { 'content-type': 'application/json' }, body: {},
  }), { status: 202, body: { route: 'export', documentId: 'doc-1' } })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'POST', url: '/v1/documents/doc-1/share-links',
    headers: { 'content-type': 'application/json' }, body: { role: 'viewer' },
  }), { status: 201, body: { route: 'share-create', documentId: 'doc-1' } })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'GET', url: '/v1/documents/doc-1/share-links',
    headers: {}, body: null,
  }), { status: 200, body: { route: 'share-list', documentId: 'doc-1' } })
  const shareId = 'a'.repeat(64)
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'DELETE', url: `/v1/documents/doc-1/share-links/${shareId}`,
    headers: {}, body: null,
  }), {
    status: 200,
    body: { route: 'share-disable', documentId: 'doc-1', shareId },
  })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'POST', url: '/v1/share-links/redeem',
    headers: { 'content-type': 'application/json' }, body: { token: 'a'.repeat(43) },
  }), { status: 200, body: { route: 'share-redeem' } })
  assert.deepEqual(await dispatchDocumentApiRequest(handlers, {
    method: 'GET', url: '/missing', headers: {}, body: null,
  }), { status: 404, body: { error: 'not-found' } })
})
