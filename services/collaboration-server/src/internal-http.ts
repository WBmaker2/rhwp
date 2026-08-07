import { timingSafeEqual } from 'node:crypto'
import type { IncomingMessage, ServerResponse } from 'node:http'

import type { SnapshotRecord } from './persistence.js'

export interface CollaborationInternalHttpDependencies {
  internalApiToken: string
  flushForExport(documentId: string): Promise<SnapshotRecord | null>
}

export function createCollaborationInternalRequestHandler(
  dependencies: CollaborationInternalHttpDependencies,
): (request: IncomingMessage, response: ServerResponse) => Promise<boolean> {
  const expectedToken = dependencies.internalApiToken.trim()
  if (!expectedToken) throw new Error('INTERNAL_API_TOKEN is required')

  return async (request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost')
    if (request.method === 'GET' && url.pathname === '/healthz') {
      writeJson(response, 200, { status: 'ok' })
      return true
    }

    const match = /^\/internal\/documents\/([A-Za-z0-9_-]{1,128})\/flush$/.exec(
      url.pathname,
    )
    const documentId = match?.[1]
    if (!documentId || request.method !== 'POST') return false
    const token = headerValue(request.headers['x-rhwp-internal-token'])
    if (!secureEqual(token, expectedToken)) {
      writeJson(response, 401, { error: 'unauthorized' })
      return true
    }

    const snapshot = await dependencies.flushForExport(documentId)
    if (!snapshot) {
      writeJson(response, 409, { error: 'collaboration-state-unavailable' })
      return true
    }
    writeJson(response, 200, { path: snapshot.path })
    return true
  }
}

function writeJson(
  response: ServerResponse,
  status: number,
  body: Record<string, unknown>,
): void {
  response.statusCode = status
  response.setHeader('content-type', 'application/json; charset=utf-8')
  response.setHeader('cache-control', 'no-store')
  response.end(JSON.stringify(body))
}

function headerValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? '' : value ?? ''
}

function secureEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left)
  const rightBytes = Buffer.from(right)
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes)
}
