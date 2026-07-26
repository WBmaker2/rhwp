import * as Y from 'yjs'

const METADATA_KEY = 'collaboration:metadata'
const SOURCE_FINGERPRINT_KEY = 'sourceFingerprint'
const SCHEMA_VERSION_KEY = 'schemaVersion'

export interface CollaborationManifest {
  schema_version: number
  source_fingerprint: string
  sections: Array<{
    paragraphs: Array<{ id: string; text: string }>
    tables: Array<{
      cells: Array<{ id: string; text: string }>
    }>
  }>
}

export interface CollaborationTextPatch {
  paragraphs: Array<{ target_id: string; text: string }>
  cells: Array<{ target_id: string; text: string }>
}

export function parseCollaborationManifest(value: unknown): CollaborationManifest {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('collaboration manifest must be an object')
  }
  const input = value as Record<string, unknown>
  if (input.schema_version !== 1) throw new Error('unsupported collaboration manifest schema')
  if (typeof input.source_fingerprint !== 'string' || !input.source_fingerprint) {
    throw new Error('collaboration manifest fingerprint is missing')
  }
  if (!Array.isArray(input.sections)) throw new Error('collaboration manifest sections are missing')

  const sections = input.sections.map((section, sectionIndex) => {
    const sectionObject = requireObject(section, `sections[${sectionIndex}]`)
    if (!Array.isArray(sectionObject.paragraphs) || !Array.isArray(sectionObject.tables)) {
      throw new Error(`sections[${sectionIndex}] has invalid node lists`)
    }
    return {
      paragraphs: sectionObject.paragraphs.map((paragraph, paragraphIndex) => (
        parseTextNode(paragraph, `sections[${sectionIndex}].paragraphs[${paragraphIndex}]`)
      )),
      tables: sectionObject.tables.map((table, tableIndex) => {
        const tableObject = requireObject(table, `sections[${sectionIndex}].tables[${tableIndex}]`)
        if (!Array.isArray(tableObject.cells)) {
          throw new Error(`sections[${sectionIndex}].tables[${tableIndex}].cells is invalid`)
        }
        return {
          cells: tableObject.cells.map((cell, cellIndex) => (
            parseTextNode(
              cell,
              `sections[${sectionIndex}].tables[${tableIndex}].cells[${cellIndex}]`,
            )
          )),
        }
      }),
    }
  })

  return {
    schema_version: 1,
    source_fingerprint: input.source_fingerprint,
    sections,
  }
}

export function buildPatchFromSnapshot(
  manifest: CollaborationManifest,
  snapshotUpdate: Uint8Array,
): CollaborationTextPatch {
  if (snapshotUpdate.byteLength === 0) throw new Error('collaboration snapshot is empty')
  const document = new Y.Doc()
  try {
    Y.applyUpdate(document, snapshotUpdate)
    const metadata = document.getMap<string | number>(METADATA_KEY)
    const fingerprint = metadata.get(SOURCE_FINGERPRINT_KEY)
    const schemaVersion = metadata.get(SCHEMA_VERSION_KEY)
    if (fingerprint !== manifest.source_fingerprint) {
      throw new Error('collaboration snapshot fingerprint mismatch')
    }
    if (schemaVersion !== manifest.schema_version) {
      throw new Error('collaboration snapshot schema mismatch')
    }

    const paragraphs: CollaborationTextPatch['paragraphs'] = []
    const cells: CollaborationTextPatch['cells'] = []
    for (const section of manifest.sections) {
      for (const paragraph of section.paragraphs) {
        appendChangedText(document, 'paragraph', paragraph, paragraphs)
      }
      for (const table of section.tables) {
        for (const cell of table.cells) appendChangedText(document, 'cell', cell, cells)
      }
    }
    return { paragraphs, cells }
  } finally {
    document.destroy()
  }
}

function appendChangedText(
  document: Y.Doc,
  kind: 'paragraph' | 'cell',
  source: { id: string; text: string },
  output: Array<{ target_id: string; text: string }>,
): void {
  const key = `${kind}:${source.id}`
  if (!document.share.has(key)) return
  const text = document.getText(key).toString()
  if (text !== source.text) output.push({ target_id: source.id, text })
}

function parseTextNode(value: unknown, path: string): { id: string; text: string } {
  const input = requireObject(value, path)
  if (typeof input.id !== 'string' || !/^[a-f0-9]{64}$/.test(input.id)) {
    throw new Error(`${path}.id is invalid`)
  }
  if (typeof input.text !== 'string') throw new Error(`${path}.text is invalid`)
  return { id: input.id, text: input.text }
}

function requireObject(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${path} must be an object`)
  }
  return value as Record<string, unknown>
}
