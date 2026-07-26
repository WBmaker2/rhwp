import { createServer, type IncomingHttpHeaders, type Server } from 'node:http'

import type { ApiRequest, ApiResponse } from './routes/complete-upload.js'
import type {
  ShareLinkHandlers,
  ShareLinkManagementRequest,
  ShareLinkRequest,
} from './routes/share-links.js'

export interface DocumentApiHandlers {
  completeUpload(request: ApiRequest): Promise<ApiResponse>
  exportHwpx(request: ApiRequest): Promise<ApiResponse>
  shareLinks: ShareLinkHandlers
}

export async function dispatchDocumentApiRequest(
  handlers: DocumentApiHandlers,
  input: {
    method: string
    url: string
    headers: IncomingHttpHeaders
    body: unknown
  },
): Promise<ApiResponse> {
  const url = new URL(input.url, 'http://localhost')
  if (input.method === 'GET' && url.pathname === '/healthz') {
    return { status: 200, body: { status: 'ok' } }
  }
  if (input.method === 'POST' && url.pathname === '/v1/share-links/redeem') {
    return handlers.shareLinks.redeem(toShareLinkRequest(input.headers, input.body))
  }

  const complete = /^\/v1\/documents\/([A-Za-z0-9_-]{1,128})\/complete-upload$/.exec(url.pathname)
  const completeDocumentId = complete?.[1]
  if (input.method === 'POST' && completeDocumentId) {
    return handlers.completeUpload(toApiRequest(completeDocumentId, input.headers, input.body))
  }
  const exportMatch = /^\/v1\/documents\/([A-Za-z0-9_-]{1,128})\/export-hwpx$/.exec(url.pathname)
  const exportDocumentId = exportMatch?.[1]
  if (input.method === 'POST' && exportDocumentId) {
    return handlers.exportHwpx(toApiRequest(exportDocumentId, input.headers, input.body))
  }

  const collectionMatch = /^\/v1\/documents\/([A-Za-z0-9_-]{1,128})\/share-links$/.exec(url.pathname)
  const collectionDocumentId = collectionMatch?.[1]
  if (collectionDocumentId) {
    const request = toShareLinkManagementRequest(
      collectionDocumentId,
      input.headers,
      input.body,
    )
    if (input.method === 'POST') return handlers.shareLinks.create(request)
    if (input.method === 'GET') return handlers.shareLinks.list(request)
  }

  const itemMatch = /^\/v1\/documents\/([A-Za-z0-9_-]{1,128})\/share-links\/([a-f0-9]{64})$/.exec(
    url.pathname,
  )
  const itemDocumentId = itemMatch?.[1]
  const shareId = itemMatch?.[2]
  if (input.method === 'DELETE' && itemDocumentId && shareId) {
    return handlers.shareLinks.disable(
      toShareLinkManagementRequest(itemDocumentId, input.headers, input.body),
      shareId,
    )
  }
  return { status: 404, body: { error: 'not-found' } }
}

export function createDocumentApiHttpServer(
  handlers: DocumentApiHandlers,
): Server {
  return createServer(async (request, response) => {
    try {
      const body = await readJsonBody(request)
      const result = await dispatchDocumentApiRequest(handlers, {
        method: request.method ?? 'GET',
        url: request.url ?? '/',
        headers: request.headers,
        body,
      })
      response.statusCode = result.status
      response.setHeader('content-type', 'application/json; charset=utf-8')
      response.setHeader('cache-control', 'no-store')
      response.end(JSON.stringify(result.body))
    } catch (error) {
      response.statusCode = error instanceof PayloadTooLargeError ? 413 : 400
      response.setHeader('content-type', 'application/json; charset=utf-8')
      response.end(JSON.stringify({
        error: error instanceof PayloadTooLargeError ? 'payload-too-large' : 'invalid-json',
      }))
    }
  })
}

function toApiRequest(
  documentId: string,
  headers: IncomingHttpHeaders,
  body: unknown,
): ApiRequest {
  return {
    params: { documentId },
    headers: normalizeHeaders(headers),
    body,
  }
}

function toShareLinkRequest(
  headers: IncomingHttpHeaders,
  body: unknown,
): ShareLinkRequest {
  return { headers: normalizeHeaders(headers), body }
}

function toShareLinkManagementRequest(
  documentId: string,
  headers: IncomingHttpHeaders,
  body: unknown,
): ShareLinkManagementRequest {
  return {
    params: { documentId },
    headers: normalizeHeaders(headers),
    body,
  }
}

function normalizeHeaders(headers: IncomingHttpHeaders): Record<string, string | undefined> {
  const normalized: Record<string, string | undefined> = {}
  for (const [name, value] of Object.entries(headers)) {
    normalized[name.toLowerCase()] = Array.isArray(value) ? value[0] : value
  }
  return normalized
}

async function readJsonBody(request: AsyncIterable<Uint8Array>): Promise<unknown> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.byteLength
    if (size > 1024 * 1024) throw new PayloadTooLargeError()
    chunks.push(Buffer.from(chunk))
  }
  if (chunks.length === 0) return null
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

class PayloadTooLargeError extends Error {}
