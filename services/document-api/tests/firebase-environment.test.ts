import assert from 'node:assert/strict'
import test from 'node:test'

import { readDocumentApiRuntimeEnvironment } from '../src/runtime-environment.js'

function environment(overrides: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  return {
    PORT: '8092',
    GCP_PROJECT_ID: 'demo-rhwp-collaboration',
    GCP_LOCATION: 'asia-northeast3',
    FIREBASE_STORAGE_BUCKET: 'demo-rhwp-collaboration.appspot.com',
    PARSE_QUEUE: 'parse-documents',
    PARSE_WORKER_URL: 'https://parse.example/run/parse',
    EXPORT_QUEUE: 'export-documents',
    EXPORT_WORKER_URL: 'https://export.example/run/export',
    TASKS_SERVICE_ACCOUNT_EMAIL: 'tasks@example.iam.gserviceaccount.com',
    COLLABORATION_FLUSH_URL: 'https://collaboration.example',
    ...overrides,
  }
}

test('production environment requires HTTPS service URLs', () => {
  const result = readDocumentApiRuntimeEnvironment(environment())
  assert.equal(result.directWorkerDispatch, false)
  assert.throws(() => readDocumentApiRuntimeEnvironment(environment({
    PARSE_WORKER_URL: 'http://127.0.0.1:8093/run/parse',
  })), /must use https/)
})

test('emulator direct dispatch accepts localhost HTTP only', () => {
  const result = readDocumentApiRuntimeEnvironment(environment({
    DIRECT_WORKER_DISPATCH: 'true',
    PARSE_WORKER_URL: 'http://127.0.0.1:8093/run/parse',
    EXPORT_WORKER_URL: 'http://localhost:8093/run/export',
    COLLABORATION_FLUSH_URL: 'http://127.0.0.1:8091',
  }))
  assert.equal(result.directWorkerDispatch, true)
  assert.equal(result.parseQueue.targetUrl, 'http://127.0.0.1:8093/run/parse')
  assert.throws(() => readDocumentApiRuntimeEnvironment(environment({
    DIRECT_WORKER_DISPATCH: 'true',
    PARSE_WORKER_URL: 'http://worker.internal/run/parse',
  })), /must use https/)
})
