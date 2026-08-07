import { createServer, type IncomingHttpHeaders, type Server } from 'node:http'

import type { DocumentWorker, WorkerResult } from './worker.js'

const MAX_BODY_BYTES = 64 * 1024

export interface WorkerHttpOptions {
  allowEmulatorTasks?: boolean
}

export async function dispatchWorkerRequest(
  worker: Pick<DocumentWorker, 'parse' | 'export'>,
  input: {
    method: string
    url: string
    headers: IncomingHttpHeaders
    body: unknown
  },
  options: WorkerHttpOptions = {},
): Promise<{ status: number; body: Record<string, unknown> }> {
  const url = new URL(input.url, 'http://localhost')
  if (input.method === 'GET' && url.pathname === '/healthz') {
    return { status: 200, body: { status: 'ok' } }
  }
  if (input.method !== 'POST') return response(404, 'not-found')
  if (!options.allowEmulatorTasks && !cloudTaskName(input.headers)) {
    return response(401, 'cloud-task-header-required')
  }
  if (normalizeContentType(input.headers['content-type']) !== 'application/json') {
    return response(415, 'unsupported-media-type')
  }

  try {
    if (url.pathname === '/run/parse') return workerResponse(await worker.parse(input.body))
    if (url.pathname === '/run/export') return workerResponse(await worker.export(input.body))
    return response(404, 'not-found')
  } catch (error) {
    if (error instanceof TypeError || isContractError(error)) {
      return response(400, safeMessage(error))
    }
    return response(500, 'worker-failed')
  }
}

export function createDocumentWorkerHttpServer(
  worker: Pick<DocumentWorker, 'parse' | 'export'>,
  options: WorkerHttpOptions = {},
): Server {
  return createServer(async (request, responseObject) => {
    try {
      const body = await readJsonBody(request)
      const result = await dispatchWorkerRequest(worker, {
        method: request.method ?? 'GET',
        url: request.url ?? '/',
        headers: request.headers,
        body,
      }, options)
      writeJson(responseObject, result.status, result.body)
    } catch (error) {
      if (error instanceof PayloadTooLargeError) {
        writeJson(responseObject, 413, { error: 'payload-too-large' })
      } else {
        writeJson(responseObject, 400, { error: 'invalid-json' })
      }
    }
  })
}

function workerResponse(result: WorkerResult): {
  status: number
  body: Record<string, unknown>
} {
  return {
    status: 200,
    body: result.path === undefined
      ? { status: result.status }
      : { status: result.status, path: result.path },
  }
}

function cloudTaskName(headers: IncomingHttpHeaders): string | null {
  const value = headers['x-cloudtasks-taskname']
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' && normalized.trim() ? normalized.trim() : null
}

function normalizeContentType(value: string | string[] | undefined): string {
  const first = Array.isArray(value) ? value[0] : value
  return first?.split(';', 1)[0]?.trim().toLowerCase() ?? ''
}

async function readJsonBody(request: AsyncIterable<Uint8Array>): Promise<unknown> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.byteLength
    if (size > MAX_BODY_BYTES) throw new PayloadTooLargeError()
    chunks.push(Buffer.from(chunk))
  }
  if (chunks.length === 0) return null
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown
}

function writeJson(
  responseObject: import('node:http').ServerResponse,
  status: number,
  body: Record<string, unknown>,
): void {
  responseObject.statusCode = status
  responseObject.setHeader('content-type', 'application/json; charset=utf-8')
  responseObject.setHeader('cache-control', 'no-store')
  responseObject.end(JSON.stringify(body))
}

function response(status: number, error: string): {
  status: number
  body: Record<string, unknown>
} {
  return { status, body: { error } }
}

function isContractError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return /payload|schemaVersion|documentId|exportId|sourcePath|snapshotPath|unexpected|missing/.test(
    error.message,
  )
}

function safeMessage(error: unknown): string {
  return error instanceof Error
    ? error.message.replace(/[\r\n]+/g, ' ').slice(0, 500)
    : 'invalid-task'
}

class PayloadTooLargeError extends Error {}
