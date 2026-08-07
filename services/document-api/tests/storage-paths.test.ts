import assert from 'node:assert/strict'
import test from 'node:test'

import { exportPath, sourcePath } from '../src/storage-paths.js'

test('builds canonical source and HWPX export paths', () => {
  assert.equal(
    sourcePath('doc-1'),
    'documents/doc-1/source/original.hwp',
  )
  assert.equal(
    exportPath('doc-1', 'export-7'),
    'documents/doc-1/exports/export-7.hwpx',
  )
})

test('rejects path traversal and unsafe identifiers', () => {
  assert.throws(() => sourcePath('../doc-1'), TypeError)
  assert.throws(() => exportPath('doc-1', '../../secret'), TypeError)
  assert.throws(() => sourcePath(''), TypeError)
})
