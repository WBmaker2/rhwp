import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import test from 'node:test'
import * as Y from 'yjs'

import {
  DocumentWorker,
  type ParsedDocumentState,
  type TaskClaim,
  type WorkerObjectMetadata,
  type WorkerObjectStore,
  type WorkerStateStore,
} from '../src/worker.js'
import type { ExportTaskPayload, ParseTaskPayload } from '../src/contracts.js'

const paragraphId = 'a'.repeat(64)
const cellId = 'b'.repeat(64)
const manifestValue = {
  schema_version: 1,
  source_fingerprint: 'blake3:fixture',
  sections: [{
    paragraphs: [{ id: paragraphId, text: '원본 문단' }],
    tables: [{ cells: [{ id: cellId, text: '원본 셀' }] }],
  }],
  readonly_objects: [],
}

class FakeObjects implements WorkerObjectStore {
  readonly values = new Map<string, Uint8Array>()
  readonly metadata = new Map<string, WorkerObjectMetadata>()
  readonly downloads: string[] = []
  readonly uploads: Array<{ path: string; contentType: string }> = []

  async stat(path: string): Promise<WorkerObjectMetadata | null> {
    return this.metadata.get(path) ?? null
  }
  async download(path: string, destination: string): Promise<void> {
    this.downloads.push(path)
    const value = this.values.get(path)
    if (!value) throw new Error(`missing object: ${path}`)
    await writeFile(destination, value)
  }
  async upload(path: string, source: string, contentType: string): Promise<void> {
    this.uploads.push({ path, contentType })
    this.values.set(path, new Uint8Array(await readFile(source)))
  }
}

class FakeState implements WorkerStateStore {
  parseClaim: TaskClaim = 'acquired'
  exportClaim: TaskClaim = 'acquired'
  parsed: ParsedDocumentState | null = {
    status: 'ready',
    sourceGeneration: 'generation-1',
    sourceFingerprint: 'blake3:fixture',
    sourcePath: 'documents/doc-1/source/original.hwp',
    manifestPath: 'documents/doc-1/derived/collaboration-manifest.json',
  }
  completedParse: unknown = null
  failedParse: unknown = null
  completedExport: unknown = null
  failedExport: unknown = null

  async claimParse(): Promise<TaskClaim> { return this.parseClaim }
  async completeParse(_payload: ParseTaskPayload, result: unknown): Promise<void> {
    this.completedParse = result
  }
  async failParse(_payload: ParseTaskPayload, result: unknown): Promise<void> {
    this.failedParse = result
  }
  async getParsedDocument(): Promise<ParsedDocumentState | null> { return this.parsed }
  async claimExport(): Promise<TaskClaim> { return this.exportClaim }
  async completeExport(_payload: ExportTaskPayload, result: unknown): Promise<void> {
    this.completedExport = result
  }
  async failExport(_payload: ExportTaskPayload, result: unknown): Promise<void> {
    this.failedExport = result
  }
}

class FakeRunner {
  readonly patches: unknown[] = []
  async importDocument(_sourceFile: string, manifestFile: string) {
    await writeFile(manifestFile, JSON.stringify(manifestValue))
    return {
      status: 'ready' as const,
      sourceFingerprint: 'blake3:fixture',
      manifestPath: manifestFile,
      paragraphCount: 1,
      cellCount: 1,
    }
  }
  async exportDocument(input: {
    patchFile: string
    outputFile: string
  }) {
    this.patches.push(JSON.parse(await readFile(input.patchFile, 'utf8')) as unknown)
    await writeFile(input.outputFile, Uint8Array.of(1, 2, 3, 4))
    return {
      status: 'ready' as const,
      outputPath: input.outputFile,
      outputBytes: 4,
      updatedParagraphs: 1,
      updatedCells: 0,
      insertedImages: 0,
    }
  }
}

function parsePayload(): ParseTaskPayload {
  return {
    schemaVersion: 1,
    documentId: 'doc-1',
    sourceGeneration: 'generation-1',
    sourcePath: 'documents/doc-1/source/original.hwp',
  }
}

function exportPayload(): ExportTaskPayload {
  return {
    schemaVersion: 1,
    documentId: 'doc-1',
    exportId: 'export-1',
    snapshotPath: 'documents/doc-1/collaboration/snapshots/100-checksum.bin',
  }
}

function fixture() {
  const objects = new FakeObjects()
  const state = new FakeState()
  const runner = new FakeRunner()
  objects.values.set(parsePayload().sourcePath, Uint8Array.of(1, 2, 3))
  objects.metadata.set(parsePayload().sourcePath, {
    sizeBytes: 3,
    generation: 'generation-1',
    contentType: 'application/x-hwp',
  })
  const worker = new DocumentWorker(
    objects,
    state,
    runner as never,
    () => new Date('2026-07-26T02:00:00.000Z'),
    tmpdir(),
  )
  return { objects, state, runner, worker }
}

function collaborationSnapshot(): Uint8Array {
  const document = new Y.Doc()
  const metadata = document.getMap<string | number>('collaboration:metadata')
  metadata.set('sourceFingerprint', 'blake3:fixture')
  metadata.set('schemaVersion', 1)
  document.getText(`paragraph:${paragraphId}`).insert(0, '수정 문단')
  document.getText(`cell:${cellId}`).insert(0, '원본 셀')
  const update = Y.encodeStateAsUpdate(document)
  document.destroy()
  return update
}

test('parse validates source generation, publishes manifest, and marks ready', async () => {
  const value = fixture()

  const result = await value.worker.parse(parsePayload())

  assert.deepEqual(result, {
    status: 'ready',
    path: 'documents/doc-1/derived/collaboration-manifest.json',
  })
  assert.deepEqual(value.objects.uploads, [{
    path: 'documents/doc-1/derived/collaboration-manifest.json',
    contentType: 'application/json',
  }])
  assert(value.state.completedParse)
  assert.equal(value.state.failedParse, null)
})

test('parse idempotency skips storage and native work when already ready', async () => {
  const value = fixture()
  value.state.parseClaim = 'already-ready'

  assert.deepEqual(await value.worker.parse(parsePayload()), { status: 'already-ready' })
  assert.deepEqual(value.objects.downloads, [])
  assert.deepEqual(value.objects.uploads, [])
})

test('parse rejects source generation changes and records a bounded failure', async () => {
  const value = fixture()
  value.objects.metadata.get(parsePayload().sourcePath)!.generation = 'generation-2'

  await assert.rejects(value.worker.parse(parsePayload()), /generation changed/)
  assert(value.state.failedParse)
  assert.equal(value.state.completedParse, null)
})

test('export converts Yjs state to a stable-ID patch and publishes HWPX', async () => {
  const value = fixture()
  value.objects.values.set(
    'documents/doc-1/derived/collaboration-manifest.json',
    new TextEncoder().encode(JSON.stringify(manifestValue)),
  )
  value.objects.values.set(exportPayload().snapshotPath, collaborationSnapshot())

  const result = await value.worker.export(exportPayload())

  assert.deepEqual(result, {
    status: 'ready',
    path: 'documents/doc-1/exports/export-1.hwpx',
  })
  assert.deepEqual(value.runner.patches, [{
    paragraphs: [{ target_id: paragraphId, text: '수정 문단' }],
    cells: [],
  }])
  assert.deepEqual(value.objects.uploads, [{
    path: 'documents/doc-1/exports/export-1.hwpx',
    contentType: 'application/vnd.hancom.hwpx+zip',
  }])
  assert(value.state.completedExport)
  assert.equal(value.state.failedExport, null)
})

test('export rejects mismatched snapshot metadata before native execution', async () => {
  const value = fixture()
  value.objects.values.set(
    'documents/doc-1/derived/collaboration-manifest.json',
    new TextEncoder().encode(JSON.stringify(manifestValue)),
  )
  const document = new Y.Doc()
  const metadata = document.getMap<string | number>('collaboration:metadata')
  metadata.set('sourceFingerprint', 'blake3:other')
  metadata.set('schemaVersion', 1)
  value.objects.values.set(exportPayload().snapshotPath, Y.encodeStateAsUpdate(document))
  document.destroy()

  await assert.rejects(value.worker.export(exportPayload()), /fingerprint mismatch/)
  assert.deepEqual(value.runner.patches, [])
  assert(value.state.failedExport)
})
