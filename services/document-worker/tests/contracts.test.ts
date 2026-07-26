import assert from 'node:assert/strict'
import test from 'node:test'

import {
  exportPath,
  exportTaskKey,
  manifestPath,
  parseExportTaskPayload,
  parseParseTaskPayload,
  parseTaskKey,
} from '../src/contracts.js'

test('parses canonical parse and export task payloads', () => {
  const parse = parseParseTaskPayload({
    schemaVersion: 1,
    documentId: 'doc-1',
    sourceGeneration: 'generation:7',
    sourcePath: 'documents/doc-1/source/original.hwp',
  })
  assert.equal(parseTaskKey(parse), 'parse:doc-1:generation:7')

  const exportTask = parseExportTaskPayload({
    schemaVersion: 1,
    documentId: 'doc-1',
    exportId: 'export-1',
    snapshotPath: 'documents/doc-1/collaboration/snapshots/100-checksum.bin',
  })
  assert.equal(exportTaskKey(exportTask), 'export:doc-1:export-1')
  assert.equal(manifestPath('doc-1'), 'documents/doc-1/derived/collaboration-manifest.json')
  assert.equal(exportPath('doc-1', 'export-1'), 'documents/doc-1/exports/export-1.hwpx')
})

test('rejects mismatched paths, unknown fields, and unsafe identifiers', () => {
  assert.throws(() => parseParseTaskPayload({
    schemaVersion: 1,
    documentId: 'doc-1',
    sourceGeneration: '7',
    sourcePath: 'documents/another/source/original.hwp',
  }), /canonical/)
  assert.throws(() => parseExportTaskPayload({
    schemaVersion: 1,
    documentId: 'doc-1',
    exportId: '../bad',
    snapshotPath: 'documents/doc-1/collaboration/snapshots/a.bin',
  }), /safe identifier/)
  assert.throws(() => parseParseTaskPayload({
    schemaVersion: 1,
    documentId: 'doc-1',
    sourceGeneration: '7',
    sourcePath: 'documents/doc-1/source/original.hwp',
    extra: true,
  }), /unexpected/)
  assert.throws(() => parseExportTaskPayload({
    schemaVersion: 2,
    documentId: 'doc-1',
    exportId: 'export-1',
    snapshotPath: 'documents/doc-1/collaboration/snapshots/a.bin',
  }), /schemaVersion/)
})
