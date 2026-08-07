import type { TaskQueueConfiguration } from './firebase-adapters.js'

export interface DocumentApiRuntimeEnvironment {
  port: number
  storageBucket: string
  collaborationFlushUrl: string
  parseQueue: TaskQueueConfiguration
  exportQueue: TaskQueueConfiguration
  directWorkerDispatch: boolean
}

export function readDocumentApiRuntimeEnvironment(
  environment: NodeJS.ProcessEnv,
): DocumentApiRuntimeEnvironment {
  const directWorkerDispatch = parseBooleanFlag(
    environment.DIRECT_WORKER_DISPATCH,
    'DIRECT_WORKER_DISPATCH',
  )
  const projectId = required(environment, 'GCP_PROJECT_ID')
  const location = required(environment, 'GCP_LOCATION')
  const serviceAccountEmail = required(environment, 'TASKS_SERVICE_ACCOUNT_EMAIL')
  const dispatchDeadlineSeconds = parseDispatchDeadline(
    environment.TASK_DISPATCH_DEADLINE_SECONDS ?? '900',
  )
  const queue = (
    queueName: 'PARSE_QUEUE' | 'EXPORT_QUEUE',
    workerUrl: 'PARSE_WORKER_URL' | 'EXPORT_WORKER_URL',
  ): TaskQueueConfiguration => ({
    projectId,
    location,
    queue: required(environment, queueName),
    targetUrl: assertServiceUrl(
      required(environment, workerUrl),
      workerUrl,
      directWorkerDispatch,
    ),
    serviceAccountEmail,
    dispatchDeadlineSeconds,
  })

  return {
    port: parsePort(environment.PORT ?? '8080'),
    storageBucket: required(environment, 'FIREBASE_STORAGE_BUCKET'),
    collaborationFlushUrl: assertServiceUrl(
      required(environment, 'COLLABORATION_FLUSH_URL'),
      'COLLABORATION_FLUSH_URL',
      directWorkerDispatch,
    ),
    parseQueue: queue('PARSE_QUEUE', 'PARSE_WORKER_URL'),
    exportQueue: queue('EXPORT_QUEUE', 'EXPORT_WORKER_URL'),
    directWorkerDispatch,
  }
}

function required(environment: NodeJS.ProcessEnv, name: string): string {
  const value = environment[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}

function parsePort(value: string): number {
  const port = Number(value)
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer from 1 to 65535')
  }
  return port
}

function parseDispatchDeadline(value: string): number {
  const seconds = Number(value)
  if (!Number.isSafeInteger(seconds) || seconds < 15 || seconds > 1800) {
    throw new Error('TASK_DISPATCH_DEADLINE_SECONDS must be an integer from 15 to 1800')
  }
  return seconds
}

function parseBooleanFlag(value: string | undefined, name: string): boolean {
  const normalized = value?.trim().toLowerCase() ?? ''
  if (normalized === '' || normalized === 'false') return false
  if (normalized === 'true') return true
  throw new Error(`${name} must be true or false`)
}

function assertServiceUrl(value: string, name: string, allowLocalHttp: boolean): string {
  const url = new URL(value)
  const isLocalHttp = url.protocol === 'http:'
    && (url.hostname === '127.0.0.1' || url.hostname === 'localhost')
  if (url.protocol !== 'https:' && !(allowLocalHttp && isLocalHttp)) {
    throw new Error(`${name} must use https`)
  }
  return url.toString().replace(/\/$/, '')
}
