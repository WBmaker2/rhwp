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
      documentId: string
      snapshotPath: string
    }): Promise<{ jobId: string }>
  }
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

    const job = await dependencies.exportJobs.enqueue({
      documentId,
      snapshotPath: snapshot.path,
    })

    return {
      status: 202,
      body: {
        status: 'queued',
        jobId: job.jobId,
        outputPath: exportPath(documentId, job.jobId),
      },
    }
  }
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
