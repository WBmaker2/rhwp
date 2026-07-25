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
}

test('dispatches health, upload completion, export, and missing routes', async () => {
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
    method: 'GET', url: '/missing', headers: {}, body: null,
  }), { status: 404, body: { error: 'not-found' } })
})
