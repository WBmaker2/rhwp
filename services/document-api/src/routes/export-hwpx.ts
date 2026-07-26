import { randomUUID } from 'node:crypto'

import type { ApiRequest, ApiResponse, DocumentRole } from './complete-upload.js'
import { exportPath } from '../storage-paths.js'

export interface ExportHwpxDependencies {
  auth: {
    verifyIdToken(token: string): Promise<{ uid: string }>
  }
  members: {
    getRole(documentId: string, uid: string): Promise<DocumentRole | null>
  }
  collaboration: {
    flushForExport(documentId: string): Promise<{ path: string } | null>
  }
  exportJobs: {
    enqueue(input: {
      schemaVersion: 1
      documentId: string
      exportId: string
      snapshotPath: string
    }): Promise<{ jobId: string }>
  }
  createExportId?: () => string
}

export function createExportHwpxHandler(
  dependencies: ExportHwpxDependencies,
): (request: ApiRequest) => Promise<ApiResponse> {
  return async (request) => {
    if (normalizeContentType(request.headers['content-type']) !== 'application/json') {
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

    const snapshot = await dependencies.collaboration.flushForExport(documentId)
    if (!snapshot) {
      return response(409, 'collaboration-state-unavailable')
    }

    const exportId = assertExportId((dependencies.createExportId ?? randomUUID)())
    const job = await dependencies.exportJobs.enqueue({
      schemaVersion: 1,
      documentId,
      exportId,
      snapshotPath: snapshot.path,
    })

    return {
      status: 202,
      body: {
        status: 'queued',
        jobId: job.jobId,
        exportId,
        outputPath: exportPath(documentId, exportId),
      },
    }
  }
}

function assertExportId(value: string): string {
  const normalized = value.trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(normalized)) {
    throw new Error('generated export ID is invalid')
  }
  return normalized
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
