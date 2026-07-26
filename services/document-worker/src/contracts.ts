const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/
const SOURCE_PATH = /^documents\/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\/source\/original\.hwp$/
const SNAPSHOT_PATH = /^documents\/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\/collaboration\/snapshots\/[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/

export const WORKER_SCHEMA_VERSION = 1 as const
export const MAX_SOURCE_BYTES = 200 * 1024 * 1024

export interface ParseTaskPayload {
  schemaVersion: typeof WORKER_SCHEMA_VERSION
  documentId: string
  sourceGeneration: string
  sourcePath: string
}

export interface ExportTaskPayload {
  schemaVersion: typeof WORKER_SCHEMA_VERSION
  documentId: string
  exportId: string
  snapshotPath: string
}

export function parseParseTaskPayload(value: unknown): ParseTaskPayload {
  const input = objectValue(value, 'parse payload')
  assertOnlyKeys(input, ['schemaVersion', 'documentId', 'sourceGeneration', 'sourcePath'])
  const documentId = safeId(input.documentId, 'documentId')
  const sourceGeneration = safeGeneration(input.sourceGeneration)
  const sourcePath = stringValue(input.sourcePath, 'sourcePath')
  const match = SOURCE_PATH.exec(sourcePath)
  if (!match || match[1] !== documentId) {
    throw new Error('sourcePath must be the canonical path for documentId')
  }
  return {
    schemaVersion: schemaVersion(input.schemaVersion),
    documentId,
    sourceGeneration,
    sourcePath,
  }
}

export function parseExportTaskPayload(value: unknown): ExportTaskPayload {
  const input = objectValue(value, 'export payload')
  assertOnlyKeys(input, ['schemaVersion', 'documentId', 'exportId', 'snapshotPath'])
  const documentId = safeId(input.documentId, 'documentId')
  const exportId = safeId(input.exportId, 'exportId')
  const snapshotPath = stringValue(input.snapshotPath, 'snapshotPath')
  const match = SNAPSHOT_PATH.exec(snapshotPath)
  if (!match || match[1] !== documentId || snapshotPath.includes('..')) {
    throw new Error('snapshotPath must be a canonical snapshot path for documentId')
  }
  return {
    schemaVersion: schemaVersion(input.schemaVersion),
    documentId,
    exportId,
    snapshotPath,
  }
}

export function manifestPath(documentId: string): string {
  return `documents/${safeId(documentId, 'documentId')}/derived/collaboration-manifest.json`
}

export function sourcePath(documentId: string): string {
  return `documents/${safeId(documentId, 'documentId')}/source/original.hwp`
}

export function exportPath(documentId: string, exportId: string): string {
  return `documents/${safeId(documentId, 'documentId')}/exports/${safeId(exportId, 'exportId')}.hwpx`
}

export function parseTaskKey(payload: ParseTaskPayload): string {
  return `parse:${payload.documentId}:${payload.sourceGeneration}`
}

export function exportTaskKey(payload: ExportTaskPayload): string {
  return `export:${payload.documentId}:${payload.exportId}`
}

function schemaVersion(value: unknown): typeof WORKER_SCHEMA_VERSION {
  if (value !== WORKER_SCHEMA_VERSION) throw new Error('schemaVersion must be 1')
  return WORKER_SCHEMA_VERSION
}

function safeId(value: unknown, name: string): string {
  const normalized = stringValue(value, name).trim()
  if (!SAFE_ID.test(normalized) || normalized === '.' || normalized === '..') {
    throw new Error(`${name} must be a safe identifier`)
  }
  return normalized
}

function safeGeneration(value: unknown): string {
  const normalized = stringValue(value, 'sourceGeneration').trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(normalized)) {
    throw new Error('sourceGeneration must be a safe non-empty value')
  }
  return normalized
}

function stringValue(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${name} must be a string`)
  return value
}

function objectValue(value: unknown, name: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${name} must be an object`)
  }
  return value as Record<string, unknown>
}

function assertOnlyKeys(input: Record<string, unknown>, allowed: string[]): void {
  const allowedSet = new Set(allowed)
  const unexpected = Object.keys(input).find((key) => !allowedSet.has(key))
  if (unexpected) throw new Error(`unexpected payload field: ${unexpected}`)
  for (const key of allowed) {
    if (!(key in input)) throw new Error(`missing payload field: ${key}`)
  }
}
