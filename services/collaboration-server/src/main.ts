import { pathToFileURL } from 'node:url'

import {
  createCollaborationFirebaseAdapters,
  readCollaborationServerEnvironment,
  type CollaborationFirebaseAdapters,
} from './firebase-adapters.js'
import { createCollaborationInternalRequestHandler } from './internal-http.js'
import {
  SnapshotStore,
  YjsSnapshotPersistence,
} from './persistence.js'
import { createCollaborationHooks, createCollaborationServer } from './server.js'

export interface CollaborationRuntime {
  listen(): Promise<void>
  shutdown(): Promise<void>
}

export function createCollaborationRuntime(
  environment: NodeJS.ProcessEnv = process.env,
  adapters: CollaborationFirebaseAdapters = createCollaborationFirebaseAdapters(environment),
): CollaborationRuntime {
  const configuration = readCollaborationServerEnvironment(environment)
  const snapshots = new SnapshotStore(adapters.objects, adapters.metadata)
  const persistence = new YjsSnapshotPersistence(snapshots)
  const hookDependencies = {
    port: configuration.port,
    tokenVerifier: adapters.tokenVerifier,
    membershipStore: adapters.membershipStore,
    persistence,
  }
  const hooks = createCollaborationHooks(hookDependencies)
  const server = createCollaborationServer({
    ...hookDependencies,
    internalRequestHandler: createCollaborationInternalRequestHandler({
      internalApiToken: configuration.internalApiToken,
      flushForExport: (documentId) => hooks.flushForExport(documentId),
    }),
  })
  let listening = false
  let shuttingDown: Promise<void> | null = null

  return {
    async listen() {
      if (listening) return
      await server.listen()
      listening = true
    },
    async shutdown() {
      if (shuttingDown) return shuttingDown
      shuttingDown = (async () => {
        await persistence.flushForShutdown()
        if (listening) await server.destroy()
        listening = false
      })()
      return shuttingDown
    },
  }
}

export async function runCollaborationServer(
  environment: NodeJS.ProcessEnv = process.env,
): Promise<CollaborationRuntime> {
  const runtime = createCollaborationRuntime(environment)
  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    console.info(`[collaboration-server] received ${signal}; flushing snapshots`)
    await runtime.shutdown()
  }
  process.once('SIGTERM', () => void shutdown('SIGTERM'))
  process.once('SIGINT', () => void shutdown('SIGINT'))
  await runtime.listen()
  return runtime
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runCollaborationServer().catch((error) => {
    console.error('[collaboration-server] fatal startup error', error)
    process.exitCode = 1
  })
}
