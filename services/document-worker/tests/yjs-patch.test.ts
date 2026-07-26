import assert from 'node:assert/strict'
import test from 'node:test'
import * as Y from 'yjs'

import {
  buildPatchFromSnapshot,
  parseCollaborationManifest,
} from '../src/yjs-patch.js'

const paragraphId = 'a'.repeat(64)
const cellId = 'b'.repeat(64)
const manifest = parseCollaborationManifest({
  schema_version: 1,
  source_fingerprint: 'blake3:fixture',
  sections: [{
    paragraphs: [{ id: paragraphId, text: '원본 문단' }],
    tables: [{ cells: [{ id: cellId, text: '원본 셀' }] }],
  }],
})

function snapshot(input: {
  fingerprint?: string
  schemaVersion?: number
  paragraph?: string
  cell?: string
} = {}): Uint8Array {
  const document = new Y.Doc()
  const metadata = document.getMap<string | number>('collaboration:metadata')
  metadata.set('sourceFingerprint', input.fingerprint ?? manifest.source_fingerprint)
  metadata.set('schemaVersion', input.schemaVersion ?? 1)
  if (input.paragraph !== undefined) {
    document.getText(`paragraph:${paragraphId}`).insert(0, input.paragraph)
  }
  if (input.cell !== undefined) {
    document.getText(`cell:${cellId}`).insert(0, input.cell)
  }
  const update = Y.encodeStateAsUpdate(document)
  document.destroy()
  return update
}

test('extracts only changed paragraph and cell text', () => {
  assert.deepEqual(buildPatchFromSnapshot(manifest, snapshot({
    paragraph: '수정 문단',
    cell: '원본 셀',
  })), {
    paragraphs: [{ target_id: paragraphId, text: '수정 문단' }],
    cells: [],
  })
})

test('does not turn absent Yjs keys into empty text replacements', () => {
  assert.deepEqual(buildPatchFromSnapshot(manifest, snapshot()), {
    paragraphs: [],
    cells: [],
  })
})

test('rejects empty, mismatched, or unsupported snapshot state', () => {
  assert.throws(
    () => buildPatchFromSnapshot(manifest, new Uint8Array()),
    /empty/,
  )
  assert.throws(
    () => buildPatchFromSnapshot(manifest, snapshot({ fingerprint: 'blake3:other' })),
    /fingerprint mismatch/,
  )
  assert.throws(
    () => buildPatchFromSnapshot(manifest, snapshot({ schemaVersion: 2 })),
    /schema mismatch/,
  )
})

test('strictly validates manifest schema and stable IDs', () => {
  assert.throws(() => parseCollaborationManifest({
    schema_version: 2,
    source_fingerprint: 'blake3:fixture',
    sections: [],
  }), /unsupported/)
  assert.throws(() => parseCollaborationManifest({
    schema_version: 1,
    source_fingerprint: 'blake3:fixture',
    sections: [{ paragraphs: [{ id: 'bad', text: '' }], tables: [] }],
  }), /id is invalid/)
})
