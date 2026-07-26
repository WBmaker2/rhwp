import type { ApiResponse, DocumentRole } from './complete-upload.js'
import type {
  ShareLinkRecord,
  ShareLinkRole,
  ShareLinkService,
} from '../share-links.js'

export interface ShareLinkRequest {
  headers: Record<string, string | undefined>
  body: unknown
}

export interface ShareLinkManagementRequest extends ShareLinkRequest {
  params: { documentId: string }
}

export interface ShareLinkHandlerDependencies {
  auth: {
    verifyIdToken(token: string): Promise<{ uid: string }>
  }
  members: {
    getRole(documentId: string, uid: string): Promise<DocumentRole | null>
  }
  shareLinks: Pick<ShareLinkService, 'create' | 'list' | 'disable' | 'redeem'>
}

export interface ShareLinkHandlers {
  create(request: ShareLinkManagementRequest): Promise<ApiResponse>
  list(request: ShareLinkManagementRequest): Promise<ApiResponse>
  disable(request: ShareLinkManagementRequest, shareId: string): Promise<ApiResponse>
  redeem(request: ShareLinkRequest): Promise<ApiResponse>
}

export function createShareLinkHandlers(
  dependencies: ShareLinkHandlerDependencies,
): ShareLinkHandlers {
  return {
    async create(request) {
      if (!isJsonRequest(request)) return response(415, 'unsupported-media-type')
      const authenticated = await authenticate(dependencies.auth, request.headers)
      if ('response' in authenticated) return authenticated.response
      if (!await isOwner(dependencies, request.params.documentId, authenticated.uid)) {
        return response(403, 'forbidden')
      }
      const input = parseCreateBody(request.body)
      if (input === null) return response(400, 'invalid-share-link')
      try {
        const created = await dependencies.shareLinks.create(
          request.params.documentId,
          authenticated.uid,
          input.role,
          input.expiresAt,
        )
        return {
          status: 201,
          body: created,
        }
      } catch (error) {
        return response(400, validationMessage(error, 'invalid-share-link'))
      }
    },

    async list(request) {
      const authenticated = await authenticate(dependencies.auth, request.headers)
      if ('response' in authenticated) return authenticated.response
      if (!await isOwner(dependencies, request.params.documentId, authenticated.uid)) {
        return response(403, 'forbidden')
      }
      const links = await dependencies.shareLinks.list(
        request.params.documentId,
        authenticated.uid,
      )
      return {
        status: 200,
        body: { links: links.map(publicLinkMetadata) },
      }
    },

    async disable(request, shareId) {
      const authenticated = await authenticate(dependencies.auth, request.headers)
      if ('response' in authenticated) return authenticated.response
      if (!await isOwner(dependencies, request.params.documentId, authenticated.uid)) {
        return response(403, 'forbidden')
      }
      try {
        const disabled = await dependencies.shareLinks.disable(
          request.params.documentId,
          authenticated.uid,
          shareId,
        )
        return disabled
          ? { status: 200, body: { status: 'disabled' } }
          : response(404, 'share-link-not-found')
      } catch (error) {
        return response(400, validationMessage(error, 'invalid-share-link'))
      }
    },

    async redeem(request) {
      if (!isJsonRequest(request)) return response(415, 'unsupported-media-type')
      const authenticated = await authenticate(dependencies.auth, request.headers)
      if ('response' in authenticated) return authenticated.response
      const token = parseRedeemBody(request.body)
      if (token === null) return response(400, 'invalid-share-token')
      try {
        const result = await dependencies.shareLinks.redeem(token, authenticated.uid)
        if (result.status === 'accepted') {
          return {
            status: 200,
            body: {
              status: 'accepted',
              documentId: result.documentId,
              role: result.role,
            },
          }
        }
        if (result.status === 'not-found') return response(404, 'share-link-not-found')
        return response(410, `share-link-${result.status}`)
      } catch (error) {
        return response(400, validationMessage(error, 'invalid-share-token'))
      }
    },
  }
}

async function authenticate(
  auth: ShareLinkHandlerDependencies['auth'],
  headers: Record<string, string | undefined>,
): Promise<{ uid: string } | { response: ApiResponse }> {
  const token = bearerToken(headers.authorization)
  if (!token) return { response: response(401, 'missing-token') }
  try {
    return await auth.verifyIdToken(token)
  } catch {
    return { response: response(401, 'invalid-token') }
  }
}

async function isOwner(
  dependencies: ShareLinkHandlerDependencies,
  documentId: string,
  uid: string,
): Promise<boolean> {
  return await dependencies.members.getRole(documentId, uid) === 'owner'
}

function parseCreateBody(body: unknown): {
  role: ShareLinkRole
  expiresAt: string | null
} | null {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null
  const input = body as Record<string, unknown>
  if (input.role !== 'editor' && input.role !== 'viewer') return null
  const expiresAt = input.expiresAt ?? null
  if (expiresAt !== null && typeof expiresAt !== 'string') return null
  if (Object.keys(input).some((key) => key !== 'role' && key !== 'expiresAt')) return null
  return { role: input.role, expiresAt }
}

function parseRedeemBody(body: unknown): string | null {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null
  const input = body as Record<string, unknown>
  if (typeof input.token !== 'string') return null
  if (Object.keys(input).some((key) => key !== 'token')) return null
  return input.token
}

function publicLinkMetadata(record: ShareLinkRecord): Record<string, unknown> {
  return {
    shareId: record.shareId,
    role: record.role,
    enabled: record.enabled,
    expiresAt: record.expiresAt,
    createdAt: record.createdAt,
  }
}

function isJsonRequest(request: ShareLinkRequest): boolean {
  return normalizeContentType(request.headers['content-type']) === 'application/json'
}

function normalizeContentType(value: string | undefined): string {
  return value?.split(';', 1)[0]?.trim().toLowerCase() ?? ''
}

function bearerToken(value: string | undefined): string | null {
  const match = /^Bearer\s+(.+)$/i.exec(value?.trim() ?? '')
  return match?.[1]?.trim() || null
}

function validationMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function response(status: number, error: string): ApiResponse {
  return { status, body: { error } }
}
