import { pathToFileURL } from 'node:url'

import { HttpCollaborationFlushClient } from './collaboration-client.js'
import { DirectHttpJobQueue, type JobQueue } from './direct-job-queue.js'
import {
  createDocumentApiFirebaseAdapters,
  type DocumentApiFirebaseAdapters,
} from './firebase-adapters.js'
import { createDocumentApiHttpServer } from './http-server.js'
import { ParseLease } from './parse-lease.js'
import { createCompleteUploadHandler } from './routes/complete-upload.js'
import { createExportHwpxHandler } from './routes/export-hwpx.js'
import { createShareLinkHandlers } from './routes/share-links.js'
import { readDocumentApiRuntimeEnvironment } from './runtime-environment.js'
import { ShareLinkService } from './share-links.js'

export interface DocumentApiRuntime {
  listen(): Promise<void>
  shutdown(): Promise<void>
}

type RuntimeAdapters = Omit<DocumentApiFirebaseAdapters, 'parseQueue' | 'exportQueue'> & {
  parseQueue: JobQueue
  exportQueue: JobQueue
}

export function createDocumentApiRuntime(
  environment: NodeJS.ProcessEnv = process.env,
  adapters?: RuntimeAdapters,
): DocumentApiRuntime {
  const configuration = readDocumentApiRuntimeEnvironment(environment)
  const resolvedAdapters = adapters ?? createRuntimeAdapters(environment, configuration)
  const internalToken = required(environment, 'COLLABORATION_INTERNAL_TOKEN')
  const collaboration = new HttpCollaborationFlushClient(
    configuration.collaborationFlushUrl,
    internalToken,
    undefined,
    undefined,
    configuration.directWorkerDispatch,
  )
  const lease = new ParseLease(resolvedAdapters.leaseStore)
  const completeUpload = createCompleteUploadHandler({
    auth: resolvedAdapters.auth,
    members: resolvedAdapters.members,
    objects: resolvedAdapters.objects,
    lease,
    parseJobs: {
      async enqueue(input) {
        await resolvedAdapters.parseQueue.enqueue(input)
      },
    },
    now: () => new Date(),
  })
  const exportHwpx = createExportHwpxHandler({
    auth: resolvedAdapters.auth,
    members: resolvedAdapters.members,
    collaboration,
    exportJobs: {
      enqueue: (input) => resolvedAdapters.exportQueue.enqueue(input),
    },
  })
  const shareLinks = createShareLinkHandlers({
    auth: resolvedAdapters.auth,
    members: resolvedAdapters.members,
    shareLinks: new ShareLinkService(resolvedAdapters.shareLinks),
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

function createRuntimeAdapters(
  environment: NodeJS.ProcessEnv,
  configuration: ReturnType<typeof readDocumentApiRuntimeEnvironment>,
): RuntimeAdapters {
  const firebaseEnvironment = configuration.directWorkerDispatch
    ? {
        ...environment,
        PARSE_WORKER_URL: 'https://localhost.invalid/run/parse',
        EXPORT_WORKER_URL: 'https://localhost.invalid/run/export',
        COLLABORATION_FLUSH_URL: 'https://localhost.invalid',
      }
    : environment
  const firebaseAdapters = createDocumentApiFirebaseAdapters(firebaseEnvironment)
  if (!configuration.directWorkerDispatch) return firebaseAdapters
  return {
    ...firebaseAdapters,
    parseQueue: new DirectHttpJobQueue(configuration.parseQueue.targetUrl),
    exportQueue: new DirectHttpJobQueue(configuration.exportQueue.targetUrl),
  }
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}
