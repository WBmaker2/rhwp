import assert from 'node:assert/strict'
import test from 'node:test'

import { CloudTasksJobQueue } from '../src/firebase-adapters.js'
import { readDocumentApiRuntimeEnvironment } from '../src/runtime-environment.js'

function environment(overrides: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  return {
    PORT: '8092',
    GCP_PROJECT_ID: 'demo-rhwp-collaboration',
    GCP_LOCATION: 'asia-northeast3',
    FIREBASE_STORAGE_BUCKET: 'demo-rhwp-collaboration.appspot.com',
    PARSE_QUEUE: 'parse-documents',
    PARSE_WORKER_URL: 'https://worker.example/run/parse',
    EXPORT_QUEUE: 'export-documents',
    EXPORT_WORKER_URL: 'https://worker.example/run/export',
    TASKS_SERVICE_ACCOUNT_EMAIL: 'tasks@example.iam.gserviceaccount.com',
    COLLABORATION_FLUSH_URL: 'https://collaboration.example',
    ...overrides,
  }
}

test('Cloud Tasks queue sends the configured 900 second dispatch deadline', async () => {
  const calls: unknown[] = []
  const client = {
    queuePath: (project: string, location: string, queue: string) => `${project}/${location}/${queue}`,
    async createTask(input: unknown): Promise<[{ name: string }]> {
      calls.push(input)
      return [{ name: 'tasks/dispatch-deadline' }]
    },
  }
  const queue = new CloudTasksJobQueue(client as never, {
    projectId: 'staging-project',
    location: 'asia-northeast3',
    queue: 'rhwp-parse-staging',
    targetUrl: 'https://worker.example/run/parse',
    serviceAccountEmail: 'tasks@staging-project.iam.gserviceaccount.com',
    dispatchDeadlineSeconds: 900,
  } as never)

  await queue.enqueue({ documentId: 'doc-1' })

  const call = calls[0] as { task: { dispatchDeadline?: unknown } }
  assert.deepEqual(call.task.dispatchDeadline, { seconds: 900 })
})

test('document API runtime defaults both queues to a 900 second dispatch deadline', () => {
  const configuration = readDocumentApiRuntimeEnvironment(environment())

  assert.equal(configuration.parseQueue.dispatchDeadlineSeconds, 900)
  assert.equal(configuration.exportQueue.dispatchDeadlineSeconds, 900)
})

test('document API runtime accepts only Cloud Tasks HTTP deadline bounds', () => {
  assert.throws(
    () => readDocumentApiRuntimeEnvironment(environment({
      TASK_DISPATCH_DEADLINE_SECONDS: '14',
    })),
    /TASK_DISPATCH_DEADLINE_SECONDS/,
  )
  assert.throws(
    () => readDocumentApiRuntimeEnvironment(environment({
      TASK_DISPATCH_DEADLINE_SECONDS: '1801',
    })),
    /TASK_DISPATCH_DEADLINE_SECONDS/,
  )
})
