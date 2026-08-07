import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  MAX_SOURCE_BYTES,
  exportPath,
  exportTaskKey,
  manifestPath,
  parseExportTaskPayload,
  parseParseTaskPayload,
  parseTaskKey,
  sourcePath,
  type ExportTaskPayload,
  type ParseTaskPayload,
} from './contracts.js'
import type { NativeCollaborationRunner } from './runner.js'
import {
  buildPatchFromSnapshot,
  parseCollaborationManifest,
} from './yjs-patch.js'

const HWP_CONTENT_TYPES = new Set([
  'application/x-hwp',
  'application/haansofthwp',
  'application/vnd.hancom.hwp',
  'application/octet-stream',
])

export interface WorkerObjectMetadata {
  sizeBytes: number
  generation: string
  contentType: string
}

export interface WorkerObjectStore {
  stat(path: string): Promise<WorkerObjectMetadata | null>
  download(path: string, destination: string): Promise<void>
  upload(path: string, source: string, contentType: string): Promise<void>
}

export type TaskClaim = 'acquired' | 'already-ready' | 'already-processing'

export interface ParsedDocumentState {
  status: 'ready'
  sourceGeneration: string
  sourceFingerprint: string
  sourcePath: string
  manifestPath: string
}

export interface WorkerStateStore {
  claimParse(payload: ParseTaskPayload, taskKey: string, now: Date): Promise<TaskClaim>
  completeParse(payload: ParseTaskPayload, result: {
    taskKey: string
    sourceFingerprint: string
    manifestPath: string
    paragraphCount: number
    cellCount: number
    completedAt: Date
  }): Promise<void>
  failParse(payload: ParseTaskPayload, result: {
    taskKey: string
    message: string
    failedAt: Date
  }): Promise<void>
  getParsedDocument(documentId: string): Promise<ParsedDocumentState | null>
  claimExport(payload: ExportTaskPayload, taskKey: string, now: Date): Promise<TaskClaim>
  completeExport(payload: ExportTaskPayload, result: {
    taskKey: string
    outputPath: string
    outputBytes: number
    updatedParagraphs: number
    updatedCells: number
    completedAt: Date
  }): Promise<void>
  failExport(payload: ExportTaskPayload, result: {
    taskKey: string
    message: string
    failedAt: Date
  }): Promise<void>
}

export interface WorkerResult {
  status: 'ready' | 'already-ready' | 'already-processing'
  path?: string
}

export class DocumentWorker {
  constructor(
    private readonly objects: WorkerObjectStore,
    private readonly state: WorkerStateStore,
    private readonly runner: Pick<NativeCollaborationRunner, 'importDocument' | 'exportDocument'>,
    private readonly now: () => Date = () => new Date(),
    private readonly temporaryRoot = tmpdir(),
  ) {}

  async parse(value: unknown): Promise<WorkerResult> {
    const payload = parseParseTaskPayload(value)
    const taskKey = parseTaskKey(payload)
    const claim = await this.state.claimParse(payload, taskKey, this.now())
    if (claim !== 'acquired') return { status: claim }

    try {
      const metadata = await this.requireSource(payload)
      if (metadata.generation !== payload.sourceGeneration) {
        throw new Error('source generation changed before parse')
      }
      return await this.withTemporaryDirectory('rhwp-parse-', async (directory) => {
        const sourceFile = join(directory, 'source.hwp')
        const manifestFile = join(directory, 'collaboration-manifest.json')
        await this.objects.download(payload.sourcePath, sourceFile)
        const report = await this.runner.importDocument(sourceFile, manifestFile)
        const destination = manifestPath(payload.documentId)
        await this.objects.upload(destination, manifestFile, 'application/json')
        await this.state.completeParse(payload, {
          taskKey,
          sourceFingerprint: report.sourceFingerprint,
          manifestPath: destination,
          paragraphCount: report.paragraphCount,
          cellCount: report.cellCount,
          completedAt: this.now(),
        })
        return { status: 'ready', path: destination }
      })
    } catch (error) {
      await this.state.failParse(payload, {
        taskKey,
        message: safeErrorMessage(error),
        failedAt: this.now(),
      })
      throw error
    }
  }

  async export(value: unknown): Promise<WorkerResult> {
    const payload = parseExportTaskPayload(value)
    const taskKey = exportTaskKey(payload)
    const claim = await this.state.claimExport(payload, taskKey, this.now())
    if (claim !== 'acquired') return { status: claim }

    try {
      const parsed = await this.state.getParsedDocument(payload.documentId)
      if (!parsed || parsed.status !== 'ready') {
        throw new Error('document parse state is not ready')
      }
      if (
        parsed.sourcePath !== sourcePath(payload.documentId)
        || parsed.manifestPath !== manifestPath(payload.documentId)
      ) {
        throw new Error('parsed document paths are not canonical')
      }
      const metadata = await this.requireSource({
        schemaVersion: 1,
        documentId: payload.documentId,
        sourceGeneration: parsed.sourceGeneration,
        sourcePath: parsed.sourcePath,
      })
      if (metadata.generation !== parsed.sourceGeneration) {
        throw new Error('source generation changed before export')
      }

      return await this.withTemporaryDirectory('rhwp-export-', async (directory) => {
        const sourceFile = join(directory, 'source.hwp')
        const manifestFile = join(directory, 'collaboration-manifest.json')
        const snapshotFile = join(directory, 'snapshot.bin')
        const patchFile = join(directory, 'patch.json')
        const outputFile = join(directory, 'export.hwpx')
        await Promise.all([
          this.objects.download(parsed.sourcePath, sourceFile),
          this.objects.download(parsed.manifestPath, manifestFile),
          this.objects.download(payload.snapshotPath, snapshotFile),
        ])
        const manifest = parseCollaborationManifest(
          JSON.parse(await readFile(manifestFile, 'utf8')) as unknown,
        )
        if (manifest.source_fingerprint !== parsed.sourceFingerprint) {
          throw new Error('stored manifest fingerprint does not match parsed document state')
        }
        const patch = buildPatchFromSnapshot(
          manifest,
          new Uint8Array(await readFile(snapshotFile)),
        )
        await writeFile(patchFile, JSON.stringify(patch))
        const report = await this.runner.exportDocument({
          sourceFile,
          manifestFile,
          patchFile,
          outputFile,
        })
        const destination = exportPath(payload.documentId, payload.exportId)
        await this.objects.upload(
          destination,
          outputFile,
          'application/vnd.hancom.hwpx+zip',
        )
        await this.state.completeExport(payload, {
          taskKey,
          outputPath: destination,
          outputBytes: report.outputBytes,
          updatedParagraphs: report.updatedParagraphs,
          updatedCells: report.updatedCells,
          completedAt: this.now(),
        })
        return { status: 'ready', path: destination }
      })
    } catch (error) {
      await this.state.failExport(payload, {
        taskKey,
        message: safeErrorMessage(error),
        failedAt: this.now(),
      })
      throw error
    }
  }

  private async requireSource(payload: ParseTaskPayload): Promise<WorkerObjectMetadata> {
    const metadata = await this.objects.stat(payload.sourcePath)
    if (!metadata) throw new Error('source object does not exist')
    if (!Number.isSafeInteger(metadata.sizeBytes) || metadata.sizeBytes <= 0) {
      throw new Error('source object is empty')
    }
    if (metadata.sizeBytes > MAX_SOURCE_BYTES) {
      throw new Error('source object exceeds 200 MiB')
    }
    const contentType = metadata.contentType.split(';', 1)[0]?.trim().toLowerCase() ?? ''
    if (!HWP_CONTENT_TYPES.has(contentType)) throw new Error('source object type is not HWP')
    return metadata
  }

  private async withTemporaryDirectory<T>(
    prefix: string,
    operation: (directory: string) => Promise<T>,
  ): Promise<T> {
    const directory = await mkdtemp(join(this.temporaryRoot, prefix))
    try {
      return await operation(directory)
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  }
}

function safeErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  return message.replace(/[\r\n]+/g, ' ').slice(0, 1_000)
}
