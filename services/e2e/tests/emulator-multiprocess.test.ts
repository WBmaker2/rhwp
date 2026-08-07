import assert from 'node:assert/strict'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import test from 'node:test'

import { HocuspocusProvider } from '@hocuspocus/provider'
import * as Y from 'yjs'

const ROOT = resolve(import.meta.dirname, '../../..')
const PROJECT_ID = 'demo-rhwp-collaboration'
const BUCKET = `${PROJECT_ID}.appspot.com`
const DOCUMENT_ID = 'emulator-doc-1'
const INTERNAL_TOKEN = 'emulator-internal-token-only'
const COLLABORATION_PORT = 8091
const DOCUMENT_API_PORT = 8092
const WORKER_PORT = 8093
const COLLABORATION_URL = `ws://127.0.0.1:${COLLABORATION_PORT}`
const DOCUMENT_API_URL = `http://127.0.0.1:${DOCUMENT_API_PORT}`
const WORKER_URL = `http://127.0.0.1:${WORKER_PORT}`

interface EmulatorUser {
  uid: string
  idToken: string
  email: string
}

interface ManagedProcess {
  child: ChildProcess
  logs: string[]
  name: string
}

test('real emulators and three server processes complete collaboration recovery and export', {
  timeout: 180_000,
}, async () => {
  requireEmulatorEnvironment()
  const fixturePath = requiredEnvironment('E2E_SOURCE_PATH')
  const workerBinary = requiredEnvironment('E2E_RHWP_WORKER_BIN')
  const temporary = await mkdtemp(join(tmpdir(), 'rhwp-emulator-e2e-'))
  const processes: ManagedProcess[] = []
  const providers: HocuspocusProvider[] = []

  try {
    const owner = await createEmulatorUser('owner@example.test')
    const editor = await createEmulatorUser('editor@example.test')
    const { app, firestore, bucket } = await createAdminClients()
    await seedDocument(firestore, bucket, fixturePath, owner.uid, editor.uid)

    const worker = startService(
      'document-worker',
      'services/document-worker',
      {
        PORT: String(WORKER_PORT),
        FIREBASE_STORAGE_BUCKET: BUCKET,
        RHWP_COLLABORATION_WORKER_BIN: workerBinary,
        ALLOW_EMULATOR_TASKS: 'true',
      },
    )
    processes.push(worker)

    let collaboration = startCollaborationServer()
    processes.push(collaboration)

    const documentApi = startService(
      'document-api',
      'services/document-api',
      {
        PORT: String(DOCUMENT_API_PORT),
        FIREBASE_STORAGE_BUCKET: BUCKET,
        GCP_PROJECT_ID: PROJECT_ID,
        GCP_LOCATION: 'local',
        PARSE_QUEUE: 'parse-local',
        PARSE_WORKER_URL: `${WORKER_URL}/run/parse`,
        EXPORT_QUEUE: 'export-local',
        EXPORT_WORKER_URL: `${WORKER_URL}/run/export`,
        TASKS_SERVICE_ACCOUNT_EMAIL: 'emulator@example.test',
        COLLABORATION_FLUSH_URL: `http://127.0.0.1:${COLLABORATION_PORT}`,
        COLLABORATION_INTERNAL_TOKEN: INTERNAL_TOKEN,
        DIRECT_WORKER_DISPATCH: 'true',
      },
    )
    processes.push(documentApi)

    await Promise.all([
      waitForHealth(`${WORKER_URL}/healthz`),
      waitForHealth(`http://127.0.0.1:${COLLABORATION_PORT}/healthz`),
      waitForHealth(`${DOCUMENT_API_URL}/healthz`),
    ])

    const complete = await authorizedJson(
      `${DOCUMENT_API_URL}/v1/documents/${DOCUMENT_ID}/complete-upload`,
      owner.idToken,
      {},
    )
    assert.equal(complete.status, 202, JSON.stringify(complete.body))
    await waitForFirestoreValue(
      firestore,
      `documents/${DOCUMENT_ID}`,
      (value) => nestedValue(value, 'parseWorker.status') === 'ready',
      'parse worker ready',
    )

    const documentSnapshot = await firestore.doc(`documents/${DOCUMENT_ID}`).get()
    const manifestPath = String(documentSnapshot.get('collaborationManifestPath'))
    assert.equal(
      manifestPath,
      `documents/${DOCUMENT_ID}/derived/collaboration-manifest.json`,
    )
    const [manifestBytes] = await bucket.file(manifestPath).download()
    const manifest = JSON.parse(manifestBytes.toString('utf8')) as {
      source_fingerprint: string
      schema_version: number
      sections: Array<{ paragraphs: Array<{ id: string; text: string }> }>
    }
    const paragraph = manifest.sections[0]?.paragraphs[0]
    assert(paragraph, 'fixture manifest must have one paragraph')

    const ownerDoc = new Y.Doc()
    const editorDoc = new Y.Doc()
    const ownerProvider = createProvider(ownerDoc, owner.idToken)
    const editorProvider = createProvider(editorDoc, editor.idToken)
    providers.push(ownerProvider, editorProvider)
    await Promise.all([waitForProviderSync(ownerProvider), waitForProviderSync(editorProvider)])

    ownerDoc.transact(() => {
      const metadata = ownerDoc.getMap<string | number>('collaboration:metadata')
      metadata.set('sourceFingerprint', manifest.source_fingerprint)
      metadata.set('schemaVersion', manifest.schema_version)
      const text = ownerDoc.getText(`paragraph:${paragraph.id}`)
      text.insert(0, paragraph.text)
    }, 'emulator-initialization')
    await waitFor(() => (
      editorDoc.getText(`paragraph:${paragraph.id}`).toString() === paragraph.text
    ), 'initial source convergence')

    const editedText = 'Emulator 두 사용자 공동 편집 결과'
    editorDoc.transact(() => {
      const text = editorDoc.getText(`paragraph:${paragraph.id}`)
      text.delete(0, text.length)
      text.insert(0, editedText)
    }, 'editor-change')
    await waitFor(() => (
      ownerDoc.getText(`paragraph:${paragraph.id}`).toString() === editedText
    ), 'two-client edit convergence')

    const flushed = await fetch(
      `http://127.0.0.1:${COLLABORATION_PORT}/internal/documents/${DOCUMENT_ID}/flush`,
      {
        method: 'POST',
        headers: { 'X-Rhwp-Internal-Token': INTERNAL_TOKEN },
      },
    )
    assert.equal(flushed.status, 200, await flushed.text())

    ownerProvider.destroy()
    editorProvider.destroy()
    providers.length = 0
    await stopProcess(collaboration)
    processes.splice(processes.indexOf(collaboration), 1)

    collaboration = startCollaborationServer()
    processes.push(collaboration)
    await waitForHealth(`http://127.0.0.1:${COLLABORATION_PORT}/healthz`)

    const recoveredDoc = new Y.Doc()
    const recoveredProvider = createProvider(recoveredDoc, owner.idToken)
    providers.push(recoveredProvider)
    await waitForProviderSync(recoveredProvider)
    await waitFor(() => (
      recoveredDoc.getText(`paragraph:${paragraph.id}`).toString() === editedText
    ), 'snapshot recovery after server restart')

    const exported = await authorizedJson(
      `${DOCUMENT_API_URL}/v1/documents/${DOCUMENT_ID}/export-hwpx`,
      editor.idToken,
      {},
    )
    assert.equal(exported.status, 202, JSON.stringify(exported.body))
    const exportId = String(exported.body.exportId)
    const exportMetadataPath = `documents/${DOCUMENT_ID}/exports/${exportId}`
    const exportMetadata = await waitForFirestoreValue(
      firestore,
      exportMetadataPath,
      (value) => value.status === 'ready',
      'export worker ready',
    )
    const outputPath = String(exportMetadata.storagePath)
    assert.equal(outputPath, `documents/${DOCUMENT_ID}/exports/${exportId}.hwpx`)

    const exportedFile = join(temporary, 'exported.hwpx')
    const verifyManifest = join(temporary, 'verify-manifest.json')
    await bucket.file(outputPath).download({ destination: exportedFile })
    await runNativeWorker(workerBinary, [
      'import',
      exportedFile,
      '--manifest',
      verifyManifest,
    ])
    const verified = JSON.parse(await readFile(verifyManifest, 'utf8')) as {
      sections: Array<{ paragraphs: Array<{ text: string }> }>
    }
    assert.equal(verified.sections[0]?.paragraphs[0]?.text, editedText)

    await app.delete()
  } catch (error) {
    const logs = processes.flatMap((processInfo) => [
      `--- ${processInfo.name} ---`,
      ...processInfo.logs.slice(-100),
    ]).join('\n')
    throw new Error(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n${logs}`)
  } finally {
    for (const provider of providers) provider.destroy()
    await Promise.all(processes.map((processInfo) => stopProcess(processInfo)))
    await rm(temporary, { recursive: true, force: true })
  }
})

function startCollaborationServer(): ManagedProcess {
  return startService(
    'collaboration-server',
    'services/collaboration-server',
    {
      PORT: String(COLLABORATION_PORT),
      FIREBASE_STORAGE_BUCKET: BUCKET,
      INTERNAL_API_TOKEN: INTERNAL_TOKEN,
    },
  )
}

function startService(
  name: string,
  relativeDirectory: string,
  extraEnvironment: NodeJS.ProcessEnv,
): ManagedProcess {
  const logs: string[] = []
  const child = spawn(
    process.execPath,
    ['--import', 'tsx', 'src/main.ts'],
    {
      cwd: resolve(ROOT, relativeDirectory),
      env: {
        ...process.env,
        GCLOUD_PROJECT: PROJECT_ID,
        GOOGLE_CLOUD_PROJECT: PROJECT_ID,
        FIREBASE_CONFIG: JSON.stringify({
          projectId: PROJECT_ID,
          storageBucket: BUCKET,
        }),
        STORAGE_EMULATOR_HOST: 'http://127.0.0.1:9199',
        ...extraEnvironment,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  child.stdout?.on('data', (value) => logs.push(String(value).trimEnd()))
  child.stderr?.on('data', (value) => logs.push(String(value).trimEnd()))
  child.on('exit', (code, signal) => logs.push(`[exit code=${code} signal=${signal}]`))
  return { child, logs, name }
}

function createProvider(document: Y.Doc, idToken: string): HocuspocusProvider {
  return new HocuspocusProvider({
    url: COLLABORATION_URL,
    name: DOCUMENT_ID,
    document,
    token: idToken,
  })
}

function waitForProviderSync(provider: HocuspocusProvider): Promise<void> {
  return new Promise((resolvePromise, reject) => {
    const timeout = setTimeout(() => {
      cleanup()
      reject(new Error('Hocuspocus sync timed out'))
    }, 15_000)
    const onSynced = ({ state }: { state: boolean }) => {
      if (!state) return
      cleanup()
      resolvePromise()
    }
    const onAuthenticationFailed = ({ reason }: { reason: string }) => {
      cleanup()
      reject(new Error(`Hocuspocus authentication failed: ${reason}`))
    }
    const cleanup = () => {
      clearTimeout(timeout)
      provider.off('synced', onSynced)
      provider.off('authenticationFailed', onAuthenticationFailed)
    }
    provider.on('synced', onSynced)
    provider.on('authenticationFailed', onAuthenticationFailed)
    provider.connect()
  })
}

async function createEmulatorUser(email: string): Promise<EmulatorUser> {
  const response = await fetch(
    'http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: 'emulator-password', returnSecureToken: true }),
    },
  )
  const body = await response.json() as Record<string, unknown>
  if (!response.ok || typeof body.localId !== 'string' || typeof body.idToken !== 'string') {
    throw new Error(`Auth Emulator user creation failed: ${JSON.stringify(body)}`)
  }
  return { uid: body.localId, idToken: body.idToken, email }
}

async function createAdminClients() {
  const { initializeApp, getApps } = await import('firebase-admin/app')
  const { getFirestore } = await import('firebase-admin/firestore')
  const { getStorage } = await import('firebase-admin/storage')
  const app = getApps()[0] ?? initializeApp({ projectId: PROJECT_ID, storageBucket: BUCKET })
  return {
    app,
    firestore: getFirestore(app),
    bucket: getStorage(app).bucket(BUCKET),
  }
}

async function seedDocument(
  firestore: import('firebase-admin/firestore').Firestore,
  bucket: ReturnType<ReturnType<typeof import('firebase-admin/storage').getStorage>['bucket']>,
  fixturePath: string,
  ownerUid: string,
  editorUid: string,
): Promise<void> {
  const sourceStoragePath = `documents/${DOCUMENT_ID}/source/original.hwp`
  await bucket.upload(fixturePath, {
    destination: sourceStoragePath,
    resumable: false,
    metadata: { contentType: 'application/x-hwp' },
  })
  const now = new Date()
  await firestore.doc(`documents/${DOCUMENT_ID}`).set({
    ownerId: ownerUid,
    title: 'Emulator E2E 문서',
    sourceFilename: 'fixture.hwpx',
    sourceSize: 1,
    sourceStoragePath,
    status: 'uploading',
    parserVersion: null,
    createdAt: now,
    updatedAt: now,
    latestSnapshotPath: null,
    latestExportPath: null,
    maxParticipants: 10,
  })
  await Promise.all([
    firestore.doc(`documents/${DOCUMENT_ID}/members/${ownerUid}`).set({
      role: 'owner', invitedBy: ownerUid, createdAt: now,
    }),
    firestore.doc(`documents/${DOCUMENT_ID}/members/${editorUid}`).set({
      role: 'editor', invitedBy: ownerUid, createdAt: now,
    }),
  ])
}

async function authorizedJson(
  url: string,
  idToken: string,
  body: unknown,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${idToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  return {
    status: response.status,
    body: await response.json() as Record<string, unknown>,
  }
}

async function waitForHealth(url: string): Promise<void> {
  await waitFor(async () => {
    try {
      const response = await fetch(url)
      return response.ok
    } catch {
      return false
    }
  }, `health check ${url}`, 30_000)
}

async function waitForFirestoreValue(
  firestore: import('firebase-admin/firestore').Firestore,
  path: string,
  predicate: (value: Record<string, unknown>) => boolean,
  label: string,
): Promise<Record<string, unknown>> {
  let latest: Record<string, unknown> = {}
  await waitFor(async () => {
    const snapshot = await firestore.doc(path).get()
    latest = snapshot.exists ? snapshot.data() ?? {} : {}
    return predicate(latest)
  }, label, 30_000)
  return latest
}

async function waitFor(
  predicate: () => boolean | Promise<boolean>,
  label: string,
  timeoutMs = 15_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 50))
  }
  throw new Error(`timed out waiting for ${label}`)
}

async function runNativeWorker(binary: string, args: string[]): Promise<void> {
  await new Promise<void>((resolvePromise, reject) => {
    const child = spawn(binary, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    const stderr: Buffer[] = []
    child.stderr.on('data', (value) => stderr.push(Buffer.from(value)))
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) resolvePromise()
      else reject(new Error(`native verification failed: ${Buffer.concat(stderr).toString('utf8')}`))
    })
  })
}

async function stopProcess(processInfo: ManagedProcess): Promise<void> {
  const child = processInfo.child
  if (child.exitCode !== null || child.killed) return
  child.kill('SIGTERM')
  await new Promise<void>((resolvePromise) => {
    const timeout = setTimeout(() => {
      child.kill('SIGKILL')
      resolvePromise()
    }, 5_000)
    child.once('exit', () => {
      clearTimeout(timeout)
      resolvePromise()
    })
  })
}

function nestedValue(value: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((current, segment) => {
    return current && typeof current === 'object'
      ? (current as Record<string, unknown>)[segment]
      : undefined
  }, value)
}

function requireEmulatorEnvironment(): void {
  for (const name of [
    'FIREBASE_AUTH_EMULATOR_HOST',
    'FIRESTORE_EMULATOR_HOST',
    'FIREBASE_STORAGE_EMULATOR_HOST',
  ]) {
    if (!process.env[name]) throw new Error(`${name} is required`)
  }
  process.env.STORAGE_EMULATOR_HOST ??= `http://${process.env.FIREBASE_STORAGE_EMULATOR_HOST}`
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}
