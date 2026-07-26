import { execFile, type ExecFileOptions } from 'node:child_process'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export interface NativeImportReport {
  status: 'ready'
  sourceFingerprint: string
  manifestPath: string
  paragraphCount: number
  cellCount: number
}

export interface NativeExportReport {
  status: 'ready'
  outputPath: string
  outputBytes: number
  updatedParagraphs: number
  updatedCells: number
  insertedImages: number
}

export interface NativeProcessExecutor {
  execute(file: string, args: string[], options: ExecFileOptions): Promise<{
    stdout: string
    stderr: string
  }>
}

export class NativeCollaborationRunner {
  constructor(
    private readonly binaryPath: string,
    private readonly executor: NativeProcessExecutor = defaultExecutor,
    private readonly timeoutMs = 15 * 60 * 1_000,
  ) {
    if (!binaryPath.trim()) throw new Error('native worker binary path is required')
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
      throw new Error('native worker timeout must be positive')
    }
  }

  async importDocument(sourceFile: string, manifestFile: string): Promise<NativeImportReport> {
    const output = await this.run([
      'import',
      sourceFile,
      '--manifest',
      manifestFile,
    ])
    return parseImportReport(output)
  }

  async exportDocument(input: {
    sourceFile: string
    manifestFile: string
    patchFile: string
    outputFile: string
  }): Promise<NativeExportReport> {
    const output = await this.run([
      'export',
      input.sourceFile,
      '--manifest',
      input.manifestFile,
      '--patch',
      input.patchFile,
      '--output',
      input.outputFile,
    ])
    return parseExportReport(output)
  }

  private async run(args: string[]): Promise<unknown> {
    try {
      const result = await this.executor.execute(this.binaryPath, args, {
        timeout: this.timeoutMs,
        maxBuffer: 1024 * 1024,
        windowsHide: true,
        shell: false,
        encoding: 'utf8',
      })
      try {
        return JSON.parse(result.stdout) as unknown
      } catch {
        throw new Error('native worker returned invalid JSON')
      }
    } catch (error) {
      if (error instanceof Error && error.message === 'native worker returned invalid JSON') {
        throw error
      }
      const details = processErrorDetails(error)
      throw new Error(`native collaboration worker failed${details ? `: ${details}` : ''}`)
    }
  }
}

const defaultExecutor: NativeProcessExecutor = {
  async execute(file, args, options) {
    const result = await execFileAsync(file, args, options)
    return {
      stdout: String(result.stdout),
      stderr: String(result.stderr),
    }
  },
}

function parseImportReport(value: unknown): NativeImportReport {
  const input = reportObject(value)
  if (
    input.status !== 'ready'
    || typeof input.sourceFingerprint !== 'string'
    || typeof input.manifestPath !== 'string'
    || !isNonNegativeInteger(input.paragraphCount)
    || !isNonNegativeInteger(input.cellCount)
  ) {
    throw new Error('native import report is invalid')
  }
  return {
    status: 'ready',
    sourceFingerprint: input.sourceFingerprint,
    manifestPath: input.manifestPath,
    paragraphCount: input.paragraphCount,
    cellCount: input.cellCount,
  }
}

function parseExportReport(value: unknown): NativeExportReport {
  const input = reportObject(value)
  if (
    input.status !== 'ready'
    || typeof input.outputPath !== 'string'
    || !isNonNegativeInteger(input.outputBytes)
    || !isNonNegativeInteger(input.updatedParagraphs)
    || !isNonNegativeInteger(input.updatedCells)
    || !isNonNegativeInteger(input.insertedImages)
  ) {
    throw new Error('native export report is invalid')
  }
  return {
    status: 'ready',
    outputPath: input.outputPath,
    outputBytes: input.outputBytes,
    updatedParagraphs: input.updatedParagraphs,
    updatedCells: input.updatedCells,
    insertedImages: input.insertedImages,
  }
}

function reportObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('native worker report must be an object')
  }
  return value as Record<string, unknown>
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function processErrorDetails(error: unknown): string {
  if (!error || typeof error !== 'object') return String(error)
  const stderr = (error as { stderr?: unknown }).stderr
  if (typeof stderr === 'string' && stderr.trim()) return stderr.trim().slice(0, 2_000)
  const message = (error as { message?: unknown }).message
  return typeof message === 'string' ? message : ''
}
