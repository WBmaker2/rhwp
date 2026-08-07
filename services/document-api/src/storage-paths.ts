const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/

export function sourcePath(documentId: string): string {
  return `documents/${assertId(documentId, 'documentId')}/source/original.hwp`
}

export function exportPath(documentId: string, exportId: string): string {
  return `documents/${assertId(documentId, 'documentId')}/exports/${assertId(exportId, 'exportId')}.hwpx`
}

export function assertId(value: string, name: string): string {
  const normalized = value.trim()
  if (!SAFE_ID.test(normalized) || normalized === '.' || normalized === '..') {
    throw new TypeError(`${name} must be a safe non-empty path segment`)
  }
  return normalized
}
