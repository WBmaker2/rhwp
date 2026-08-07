import { pathToFileURL } from 'node:url'

import {
  createDocumentWorkerFirebaseAdapters,
  readDocumentWorkerEnvironment,
  type DocumentWorkerFirebaseAdapters,
} from './firebase-adapters.js'
import { createDocumentWorkerHttpServer } from './http-server.js'
import { NativeCollaborationRunner } from './runner.js'
import { DocumentWorker } from './worker.js'

export interface DocumentWorkerRuntime {
  listen(): Promise<void>
  shutdown(): Promise<void>
}

export function createDocumentWorkerRuntime(
  environment: NodeJS.ProcessEnv = process.env,
  adapters: DocumentWorkerFirebaseAdapters = createDocumentWorkerFirebaseAdapters(environment),
): DocumentWorkerRuntime {
  const configuration = readDocumentWorkerEnvironment(environment)
  const worker = new DocumentWorker(
    adapters.objects,
    adapters.state,
    new NativeCollaborationRunner(configuration.nativeBinaryPath),
  )
  const server = createDocumentWorkerHttpServer(worker, {
    allowEmulatorTasks: configuration.allowEmulatorTasks,
  })
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

export async function runDocumentWorker(
  environment: NodeJS.ProcessEnv = process.env,
): Promise<DocumentWorkerRuntime> {
  const runtime = createDocumentWorkerRuntime(environment)
  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    console.info(`[document-worker] received ${signal}; stopping HTTP server`)
    await runtime.shutdown()
  }
  process.once('SIGTERM', () => void shutdown('SIGTERM'))
  process.once('SIGINT', () => void shutdown('SIGINT'))
  await runtime.listen()
  return runtime
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runDocumentWorker().catch((error) => {
    console.error('[document-worker] fatal startup error', error)
    process.exitCode = 1
  })
}
