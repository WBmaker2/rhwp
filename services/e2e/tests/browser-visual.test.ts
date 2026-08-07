import assert from 'node:assert/strict'
import { spawn, type ChildProcess } from 'node:child_process'
import { createServer, type Server } from 'node:http'
import { access, mkdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import test from 'node:test'

import { initializeApp, getApps } from 'firebase-admin/app'
import { getFirestore } from 'firebase-admin/firestore'
import puppeteer, { type Browser, type BrowserContext, type Page } from 'puppeteer-core'

const ROOT = resolve(import.meta.dirname, '../../..')
const PROJECT_ID = 'demo-rhwp-collaboration'
const BUCKET = `${PROJECT_ID}.appspot.com`
const DOCUMENT_ID = 'visual-browser-doc-1'
const INTERNAL_TOKEN = 'visual-e2e-internal-token'
const PASSWORD = 'visual-e2e-password'
const COLLABORATION_PORT = 8091
const STUDIO_PORT = 4173
const FIXTURE_PORT = 8094
const STUDIO_URL = `http://127.0.0.1:${STUDIO_PORT}`
const COLLABORATION_URL = `ws://127.0.0.1:${COLLABORATION_PORT}`
const OUTPUT_DIRECTORY = resolve(ROOT, 'output/collaboration-browser-visual')

interface EmulatorUser {
  uid: string
  email: string
}

interface ManagedProcess {
  child: ChildProcess
  name: string
  logs: string[]
}

test('two real Studio browser contexts show presence, remote cursor, viewer blocking, and reconnection', {
  timeout: 240_000,
}, async () => {
  requireEmulatorEnvironment()
  const fixturePath = requiredEnvironment('E2E_SOURCE_PATH')
  const fixtureBytes = await readFile(fixturePath)
  await mkdir(OUTPUT_DIRECTORY, { recursive: true })

  const processes: ManagedProcess[] = []
  let fixtureServer: Server | null = null
  let browser: Browser | null = null
  const contexts: BrowserContext[] = []
  const pages: Page[] = []

  try {
    const editor = await createEmulatorUser('visual-editor@example.test')
    const viewer = await createEmulatorUser('visual-viewer@example.test')
    await seedDocument(editor, viewer)

    fixtureServer = await startFixtureServer(fixtureBytes)
    const collaboration = startCollaborationServer()
    const studio = startStudioServer()
    processes.push(collaboration, studio)

    await Promise.all([
      waitForHealth(`http://127.0.0.1:${COLLABORATION_PORT}/healthz`),
      waitForHealth(STUDIO_URL),
    ])

    browser = await puppeteer.launch({
      executablePath: await findChromeExecutable(),
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    })

    const editorContext = await browser.createBrowserContext()
    const viewerContext = await browser.createBrowserContext()
    contexts.push(editorContext, viewerContext)
    const editorPage = await openStudioPage(editorContext, editor.email, 'editor')
    const viewerPage = await openStudioPage(viewerContext, viewer.email, 'viewer')
    pages.push(editorPage, viewerPage)

    await Promise.all([
      waitForConnected(editorPage, 'editor'),
      waitForConnected(viewerPage, 'viewer'),
    ])
    await Promise.all([
      waitForRemoteParticipant(editorPage, viewer.uid),
      waitForRemoteParticipant(viewerPage, editor.uid),
    ])

    const synchronizedText = '두 브라우저 실제 공동 편집 결과'
    await editorPage.evaluate((text) => {
      ;(window as any).__rhwpCollaborationDebug.applyLocalFirstParagraphText(text)
    }, synchronizedText)
    await waitForParagraphText(viewerPage, synchronizedText)

    await editorPage.evaluate(() => {
      const debug = (window as any).__rhwpCollaborationDebug
      const snapshot = {
        position: { sectionIndex: 0, paragraphIndex: 0, charOffset: 1 },
        selection: null,
      }
      ;(window as any).__visualCursorTimer = window.setInterval(
        () => debug.publishCursor(snapshot),
        20,
      )
    })
    await viewerPage.waitForSelector(
      `[data-testid="collaboration-remote-cursor"][data-user-id="${editor.uid}"]`,
      { timeout: 15_000 },
    )

    const readOnlyFlag = await viewerPage.evaluate(() => (
      document.documentElement.dataset.collaborationReadOnly
    ))
    assert.equal(readOnlyFlag, 'true')
    await viewerPage.evaluate(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>('textarea')
      if (!textarea) throw new Error('Studio hidden textarea not found')
      textarea.focus()
    })
    await viewerPage.keyboard.type('열람자 입력은 차단되어야 함')
    await viewerPage.keyboard.press('Backspace')
    await delay(800)
    assert.equal(await paragraphText(viewerPage), synchronizedText)
    assert.equal(await paragraphText(editorPage), synchronizedText)

    await Promise.all([
      editorPage.screenshot({ path: resolve(OUTPUT_DIRECTORY, 'editor.png'), fullPage: true }),
      viewerPage.screenshot({ path: resolve(OUTPUT_DIRECTORY, 'viewer.png'), fullPage: true }),
    ])

    await viewerContext.close()
    contexts.splice(contexts.indexOf(viewerContext), 1)
    const reconnectedContext = await browser.createBrowserContext()
    contexts.push(reconnectedContext)
    const reconnectedPage = await openStudioPage(reconnectedContext, viewer.email, 'viewer-reconnected')
    pages.push(reconnectedPage)
    await waitForConnected(reconnectedPage, 'viewer')
    await waitForParagraphText(reconnectedPage, synchronizedText)
    await waitForRemoteParticipant(reconnectedPage, editor.uid)
    await reconnectedPage.waitForSelector(
      `[data-testid="collaboration-remote-cursor"][data-user-id="${editor.uid}"]`,
      { timeout: 15_000 },
    )
    await reconnectedPage.screenshot({
      path: resolve(OUTPUT_DIRECTORY, 'viewer-reconnected.png'),
      fullPage: true,
    })
  } catch (error) {
    const diagnostics = [
      error instanceof Error ? error.stack ?? error.message : String(error),
      ...pages.flatMap((page, index) => [
        `--- browser page ${index + 1}: ${page.url()} ---`,
      ]),
      ...processes.flatMap((processInfo) => [
        `--- ${processInfo.name} ---`,
        ...processInfo.logs.slice(-120),
      ]),
    ].join('\n')
    throw new Error(diagnostics)
  } finally {
    for (const context of contexts) {
      await context.close().catch(() => undefined)
    }
    await browser?.close().catch(() => undefined)
    await Promise.all(processes.map((processInfo) => stopProcess(processInfo)))
    await new Promise<void>((resolvePromise) => fixtureServer?.close(() => resolvePromise()) ?? resolvePromise())
    for (const app of getApps()) await app.delete()
  }
})

async function openStudioPage(
  context: BrowserContext,
  email: string,
  label: string,
): Promise<Page> {
  const page = await context.newPage()
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 })
  page.on('console', (message) => console.log(`[${label}:console] ${message.type()}: ${message.text()}`))
  page.on('pageerror', (error) => console.error(`[${label}:pageerror]`, error))
  const sourceUrl = `http://127.0.0.1:${FIXTURE_PORT}/source.hwpx`
  const params = new URLSearchParams({
    url: sourceUrl,
    collabDocument: DOCUMENT_ID,
    collabE2EEmail: email,
    collabE2EPassword: PASSWORD,
  })
  await page.goto(`${STUDIO_URL}/?${params}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  return page
}

async function waitForConnected(page: Page, role: 'editor' | 'viewer'): Promise<void> {
  await page.waitForFunction((expectedRole) => {
    const debug = (window as any).__rhwpCollaborationDebug
    const status = document.querySelector('[data-testid="collaboration-status"]')
    return debug?.role?.() === expectedRole && !status?.textContent?.includes('오류')
  }, { timeout: 45_000 }, role)
  await page.waitForSelector(`[data-testid="collaboration-presence"][data-role="${role}"]`, {
    timeout: 5_000,
  })
}

async function waitForRemoteParticipant(page: Page, userId: string): Promise<void> {
  await page.waitForSelector(
    `[data-testid="collaboration-participant"][data-user-id="${userId}"]`,
    { timeout: 15_000 },
  )
}

async function paragraphText(page: Page): Promise<string> {
  return page.evaluate(() => (window as any).__rhwpCollaborationDebug.firstParagraphText())
}

async function waitForParagraphText(page: Page, expected: string): Promise<void> {
  await page.waitForFunction((value) => (
    (window as any).__rhwpCollaborationDebug?.firstParagraphText?.() === value
  ), { timeout: 20_000 }, expected)
}

function startCollaborationServer(): ManagedProcess {
  return startProcess(
    'collaboration-server',
    'services/collaboration-server',
    ['--import', 'tsx', 'src/main.ts'],
    {
      PORT: String(COLLABORATION_PORT),
      FIREBASE_STORAGE_BUCKET: BUCKET,
      INTERNAL_API_TOKEN: INTERNAL_TOKEN,
    },
  )
}

function startStudioServer(): ManagedProcess {
  return startProcess(
    'rhwp-studio',
    'rhwp-studio',
    ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(STUDIO_PORT), '--strictPort'],
    {
      VITE_COLLABORATION_URL: COLLABORATION_URL,
      VITE_FIREBASE_API_KEY: 'fake-api-key',
      VITE_FIREBASE_AUTH_DOMAIN: `${PROJECT_ID}.firebaseapp.com`,
      VITE_FIREBASE_PROJECT_ID: PROJECT_ID,
      VITE_FIREBASE_STORAGE_BUCKET: BUCKET,
      VITE_FIREBASE_APP_ID: '1:123:web:visual-e2e',
      VITE_AUTH_EMULATOR_URL: 'http://127.0.0.1:9099',
      VITE_FIRESTORE_EMULATOR_HOST: '127.0.0.1',
      VITE_FIRESTORE_EMULATOR_PORT: '8080',
    },
  )
}

function startProcess(
  name: string,
  relativeDirectory: string,
  args: string[],
  extraEnvironment: NodeJS.ProcessEnv,
): ManagedProcess {
  const logs: string[] = []
  const child = spawn(process.execPath, args, {
    cwd: resolve(ROOT, relativeDirectory),
    env: {
      ...process.env,
      GCLOUD_PROJECT: PROJECT_ID,
      GOOGLE_CLOUD_PROJECT: PROJECT_ID,
      FIREBASE_CONFIG: JSON.stringify({ projectId: PROJECT_ID, storageBucket: BUCKET }),
      STORAGE_EMULATOR_HOST: 'http://127.0.0.1:9199',
      ...extraEnvironment,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout?.on('data', (value) => logs.push(String(value).trimEnd()))
  child.stderr?.on('data', (value) => logs.push(String(value).trimEnd()))
  child.on('exit', (code, signal) => logs.push(`[exit code=${code} signal=${signal}]`))
  return { child, name, logs }
}

async function startFixtureServer(bytes: Buffer): Promise<Server> {
  return new Promise((resolvePromise, reject) => {
    const server = createServer((request, response) => {
      if (request.url !== '/source.hwpx') {
        response.writeHead(404).end()
        return
      }
      response.writeHead(200, {
        'Content-Type': 'application/x-hwp',
        'Content-Length': String(bytes.byteLength),
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      })
      response.end(bytes)
    })
    server.once('error', reject)
    server.listen(FIXTURE_PORT, '127.0.0.1', () => {
      server.off('error', reject)
      resolvePromise(server)
    })
  })
}

async function seedDocument(editor: EmulatorUser, viewer: EmulatorUser): Promise<void> {
  process.env.STORAGE_EMULATOR_HOST ??= 'http://127.0.0.1:9199'
  const app = getApps()[0] ?? initializeApp({ projectId: PROJECT_ID, storageBucket: BUCKET })
  const firestore = getFirestore(app)
  const now = new Date()
  await firestore.doc(`documents/${DOCUMENT_ID}`).set({
    ownerId: editor.uid,
    title: '두 브라우저 시각 검증 문서',
    createdAt: now,
    updatedAt: now,
  })
  await firestore.doc(`documents/${DOCUMENT_ID}/members/${editor.uid}`).set({
    role: 'editor',
    createdAt: now,
  })
  await firestore.doc(`documents/${DOCUMENT_ID}/members/${viewer.uid}`).set({
    role: 'viewer',
    createdAt: now,
  })
}

async function createEmulatorUser(email: string): Promise<EmulatorUser> {
  const response = await fetch(
    'http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: PASSWORD, returnSecureToken: true }),
    },
  )
  const body = await response.json() as Record<string, unknown>
  if (!response.ok || typeof body.localId !== 'string') {
    throw new Error(`Auth Emulator user creation failed: ${JSON.stringify(body)}`)
  }
  return { uid: body.localId, email }
}

async function findChromeExecutable(): Promise<string> {
  const candidates = [
    process.env.CHROME_PATH,
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter((candidate): candidate is string => Boolean(candidate))
  for (const candidate of candidates) {
    try {
      await access(candidate)
      return candidate
    } catch {
      // Continue to the next candidate.
    }
  }
  throw new Error(`Chrome executable not found; checked: ${candidates.join(', ')}`)
}

async function waitForHealth(url: string): Promise<void> {
  const deadline = Date.now() + 30_000
  let lastError = ''
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
      lastError = `HTTP ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await delay(250)
  }
  throw new Error(`service health timed out for ${url}: ${lastError}`)
}

async function stopProcess(processInfo: ManagedProcess): Promise<void> {
  if (processInfo.child.exitCode !== null || processInfo.child.signalCode !== null) return
  processInfo.child.kill('SIGTERM')
  await Promise.race([
    new Promise<void>((resolvePromise) => processInfo.child.once('exit', () => resolvePromise())),
    delay(5_000).then(() => {
      if (processInfo.child.exitCode === null) processInfo.child.kill('SIGKILL')
    }),
  ])
}

function requireEmulatorEnvironment(): void {
  for (const name of ['FIRESTORE_EMULATOR_HOST', 'FIREBASE_AUTH_EMULATOR_HOST']) {
    if (!process.env[name]) throw new Error(`${name} is required`)
  }
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim() ?? ''
  if (!value) throw new Error(`${name} is required`)
  return value
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds))
}
