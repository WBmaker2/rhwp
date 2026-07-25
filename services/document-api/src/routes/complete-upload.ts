import type { LeaseResult } from '../parse-lease.js'
import { sourcePath } from '../storage-paths.js'

const MIB = 1024 * 1024
const MIN_SOURCE_BYTES = 100 * MIB
const MAX_SOURCE_BYTES = 200 * MIB
const HWP_CONTENT_TYPES = new Set([
  'application/x-hwp',
  'application/vnd.hancom.hwp',
  'application/octet-stream',
])

export type DocumentRole = 'owner' | 'editor' | 'viewer'

export interface ApiRequest {
  params: { documentId: string }
  headers: Record<string, string | undefined>
  body: unknown
}

export interface ApiResponse {
  status: number
  body: Record<string, unknown>
}

export interface CompleteUploadDependencies {
  auth: {
    verifyIdToken(token: string): Promise<{ uid: string }>
  }
  members: {
    getRole(documentId: string, uid: string): Promise<DocumentRole | null>
  }
  objects: {
    stat(path: string): Promise<{
      sizeBytes: number
      generation: string
      contentType: string
    } | null>
  }
  lease: {
    acquire(
      documentId: string,
      sourceGeneration: string,
      now: Date,
    ): Promise<LeaseResult>
  }
  parseJobs: {
    enqueue(input: {
      documentId: string
      sourceGeneration: string
      sourcePath: string
    }): Promise<void>
  }
  now: () => Date
}

export function createCompleteUploadHandler(
  dependencies: CompleteUploadDependencies,
): (request: ApiRequest) => Promise<ApiResponse> {
  return async (request) => {
    if (!isJsonRequest(request)) {
      return response(415, 'unsupported-media-type')
    }

    const token = bearerToken(request.headers.authorization)
    if (!token) {
      return response(401, 'missing-token')
    }

    let identity: { uid: string }
    try {
      identity = await dependencies.auth.verifyIdToken(token)
    } catch {
      return response(401, 'invalid-token')
    }

    const documentId = request.params.documentId
    const role = await dependencies.members.getRole(documentId, identity.uid)
    if (role !== 'owner' && role !== 'editor') {
      return response(403, 'forbidden')
    }

    const path = sourcePath(documentId)
    const source = await dependencies.objects.stat(path)
    if (!source) {
      return response(404, 'source-not-found')
    }

    if (!HWP_CONTENT_TYPES.has(normalizeContentType(source.contentType))) {
      return response(415, 'unsupported-source-type')
    }

    if (
      source.sizeBytes < MIN_SOURCE_BYTES ||
      source.sizeBytes > MAX_SOURCE_BYTES
    ) {
      return response(422, 'source-size-out-of-range')
    }

    const lease = await dependencies.lease.acquire(
      documentId,
      source.generation,
      dependencies.now(),
    )
    if (!lease.acquired) {
      return {
        status: 202,
        body: {
          status: lease.reason,
          sourceGeneration: source.generation,
        },
      }
    }

    await dependencies.parseJobs.enqueue({
      documentId,
      sourceGeneration: source.generation,
      sourcePath: path,
    })

    return {
      status: 202,
      body: {
        status: 'processing',
        sourceGeneration: source.generation,
        leaseExpiresAt: lease.expiresAt,
      },
    }
  }
}

function isJsonRequest(request: ApiRequest): boolean {
  return normalizeContentType(request.headers['content-type']) === 'application/json'
}

function normalizeContentType(value: string | undefined): string {
  return value?.split(';', 1)[0]?.trim().toLowerCase() ?? ''
}

function bearerToken(value: string | undefined): string | null {
  const match = /^Bearer\s+(.+)$/i.exec(value?.trim() ?? '')
  return match?.[1]?.trim() || null
}

function response(status: number, error: string): ApiResponse {
  return { status, body: { error } }
}
