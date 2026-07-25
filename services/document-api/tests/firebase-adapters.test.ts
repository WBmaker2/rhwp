import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  CloudTasksJobQueue,
  FirestoreParseLeaseStore,
  readDocumentApiEnvironment,
} from '../src/firebase-adapters.js'

class FakeTransaction {
  readonly writes: Array<{ path: string; value: unknown }> = []
  constructor(private readonly data: Map<string, unknown>) {}
  async get(reference: { path: string }): Promise<{ exists: boolean; data(): unknown }> {
    return {
      exists: this.data.has(reference.path),
      data: () => this.data.get(reference.path),
    }
  }
  set(reference: { path: string }, value: unknown): void {
    this.data.set(reference.path, value)
    this.writes.push({ path: reference.path, value })
  }
}

class FakeFirestore {
  readonly data = new Map<string, unknown>()
  doc(path: string): { path: string } { return { path } }
  async runTransaction<T>(operation: (transaction: FakeTransaction) => Promise<T>): Promise<T> {
    return operation(new FakeTransaction(this.data))
  }
}

test('parse lease store performs the callback inside one Firestore transaction', async () => {
  const firestore = new FakeFirestore()
  const store = new FirestoreParseLeaseStore(firestore as never)

  const result = await store.runTransaction('doc-1', async (state) => {
    assert.equal(state, null)
    return {
      state: {
        sourceGeneration: 'generation-1',
        status: 'processing' as const,
        leaseExpiresAt: '2026-07-25T06:15:00.000Z',
      },
      result: 'acquired',
    }
  })

  assert.equal(result, 'acquired')
  assert.deepEqual(firestore.data.get('documents/doc-1'), {
    parseLease: {
      sourceGeneration: 'generation-1',
      status: 'processing',
      leaseExpiresAt: '2026-07-25T06:15:00.000Z',
    },
  })
})

test('Cloud Tasks queue creates an OIDC-authenticated JSON task', async () => {
  const calls: unknown[] = []
  const client = {
    queuePath: (project: string, location: string, queue: string) => `${project}/${location}/${queue}`,
    async createTask(input: unknown): Promise<[{ name: string }]> {
      calls.push(input)
      return [{ name: 'tasks/123' }]
    },
  }
  const queue = new CloudTasksJobQueue(client as never, {
    projectId: 'staging-project',
    location: 'asia-northeast3',
    queue: 'parse-documents',
    targetUrl: 'https://worker.example/parse',
    serviceAccountEmail: 'tasks@staging-project.iam.gserviceaccount.com',
  })

  const job = await queue.enqueue({ documentId: 'doc-1', sourceGeneration: 'generation-1' })

  assert.equal(job.jobId, 'tasks/123')
  const call = calls[0] as { task: { httpRequest: { headers: Record<string, string>; oidcToken: unknown } } }
  assert.equal(call.task.httpRequest.headers['Content-Type'], 'application/json')
  assert.deepEqual(call.task.httpRequest.oidcToken, {
    serviceAccountEmail: 'tasks@staging-project.iam.gserviceaccount.com',
    audience: 'https://worker.example/parse',
  })
})

test('document API environment requires private service URLs and queue configuration', () => {
  const configuration = readDocumentApiEnvironment({
    PORT: '8080',
    GCP_PROJECT_ID: 'staging-project',
    GCP_LOCATION: 'asia-northeast3',
    FIREBASE_STORAGE_BUCKET: 'staging-project.appspot.com',
    PARSE_QUEUE: 'parse-documents',
    PARSE_WORKER_URL: 'https://parse-worker.example/run',
    EXPORT_QUEUE: 'export-documents',
    EXPORT_WORKER_URL: 'https://export-worker.example/run',
    TASKS_SERVICE_ACCOUNT_EMAIL: 'tasks@staging-project.iam.gserviceaccount.com',
    COLLABORATION_FLUSH_URL: 'https://collaboration.example/internal/flush',
  })
  assert.equal(configuration.port, 8080)
  assert.equal(configuration.parseQueue.queue, 'parse-documents')
  assert.throws(() => readDocumentApiEnvironment({}), /GCP_PROJECT_ID/)
})
