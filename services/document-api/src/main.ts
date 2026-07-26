import { pathToFileURL } from 'node:url'

import { HttpCollaborationFlushClient } from './collaboration-client.js'
import {
  createDocumentApiFirebaseAdapters,
  readDocumentApiEnvironment,
  type DocumentApiFirebaseAdapters,
} from './firebase-adapters.js'
import { createDocumentApiHttpServer } from './http-server.js'
import { ParseLease } from './parse-lease.js'
import { createCompleteUploadHandler } from './routes/complete-upload.js'
import { createExportHwpxHandler } from './routes/export-hwpx.js'
import { createShareLinkHandlers } from './routes/share-links.js'
import { ShareLinkService } from './share-links.js'

export interface DocumentApiRuntime {
  listen(): Promise<void>
  shutdown(): Promise<void>
}

export function createDocumentApiRuntime(
  environment: NodeJS.ProcessEnv = process.env,
  adapters: DocumentApiFirebaseAdapters = createDocumentApiFirebaseAdapters(environment),
): DocumentApiRuntime {
  const configuration = readDocumentApiEnvironment(environment)
  const internalToken = required(environment, 'COLLABORATION_INTERNAL_TOKEN')
  const collaboration = new HttpCollaborationFlushClient(
    configuration.collaborationFlushUrl,
    internalToken,
  )
  const lease = new ParseLease(adapters.leaseStore)
  const completeUpload = createCompleteUploadHandler({
    auth: adapters.auth,
    members: adapters.members,
    objects: adapters.objects,
    lease,
    parseJobs: {
      async enqueue(input) {
        await adapters.parseQueue.enqueue(input)
      },
    },
    now: () => new Date(),
  })
  const exportHwpx = createExportHwpxHandler({
    auth: adapters.auth,
    members: adapters.members,
    collaboration,
    exportJobs: {
      enqueue: (input) => adapters.exportQueue.enqueue(input),
    },
  })
  const shareLinks = createShareLinkHandlers({
    auth: adapters.auth,
    members: adapters.members,
    shareLinks: new ShareLinkService(adapters.shareLinks),
  })
  const server = createDocumentApiHttpServer({ completeUpload, exportHwpx, shareLinks })
  let listening = false

  return {
    async listen() {
      if (listening) return
      await new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(configuration.port, '0.0.0.0', () => {
          server.off('error', reject)
          listening = true
          resolve()
        })
      })
    },
    async shutdown() {
      if (!listening) return
      await new Promise<void>((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve())
      })
      listening = false
    },
  }
}

export async function runDocumentApi(
  environment: NodeJS.ProcessEnv = process.env,
): Promise<DocumentApiRuntime> {
  const runtime = createDocumentApiRuntime(environment)
  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    console.info(`[document-api] received ${signal}; stopping HTTP server`)
    await runtime.shutdown()
  }
  process.once('SIGTERM', () => void shutdown('SIGTERM'))
  process.once('SIGINT', () => void shutdown('SIGINT'))
  await runtime.listen()
  return runtime
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runDocumentApi().catch((error) => {
    console.error('[document-api] fatal startup error', error)
    process.exitCode = 1
  })
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}
