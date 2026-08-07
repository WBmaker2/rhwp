import assert from 'node:assert/strict'
import test from 'node:test'

import {
  NativeCollaborationRunner,
  type NativeProcessExecutor,
} from '../src/runner.js'

class FakeExecutor implements NativeProcessExecutor {
  readonly calls: Array<{ file: string; args: string[]; options: unknown }> = []
  stdout = '{}'
  stderr = ''
  error: unknown = null

  async execute(file: string, args: string[], options: unknown): Promise<{
    stdout: string
    stderr: string
  }> {
    this.calls.push({ file, args, options })
    if (this.error) throw this.error
    return { stdout: this.stdout, stderr: this.stderr }
  }
}

test('runs native import with fixed arguments and parses its report', async () => {
  const executor = new FakeExecutor()
  executor.stdout = JSON.stringify({
    status: 'ready',
    sourceFingerprint: 'blake3:fixture',
    manifestPath: '/tmp/manifest.json',
    paragraphCount: 2,
    cellCount: 3,
  })
  const runner = new NativeCollaborationRunner('/app/rhwp-worker', executor, 5_000)

  const result = await runner.importDocument('/tmp/source.hwp', '/tmp/manifest.json')

  assert.equal(result.sourceFingerprint, 'blake3:fixture')
  assert.deepEqual(executor.calls[0]?.args, [
    'import', '/tmp/source.hwp', '--manifest', '/tmp/manifest.json',
  ])
  assert.equal((executor.calls[0]?.options as { shell: boolean }).shell, false)
})

test('runs native export and rejects malformed reports', async () => {
  const executor = new FakeExecutor()
  executor.stdout = JSON.stringify({
    status: 'ready',
    outputPath: '/tmp/export.hwpx',
    outputBytes: 400,
    updatedParagraphs: 1,
    updatedCells: 2,
    insertedImages: 0,
  })
  const runner = new NativeCollaborationRunner('/app/rhwp-worker', executor)

  const result = await runner.exportDocument({
    sourceFile: '/tmp/source.hwp',
    manifestFile: '/tmp/manifest.json',
    patchFile: '/tmp/patch.json',
    outputFile: '/tmp/export.hwpx',
  })
  assert.equal(result.updatedCells, 2)

  executor.stdout = '{not-json'
  await assert.rejects(
    runner.importDocument('/tmp/source.hwp', '/tmp/manifest.json'),
    /invalid JSON/,
  )
})

test('redacts process failures to bounded stderr details', async () => {
  const executor = new FakeExecutor()
  executor.error = { stderr: 'fingerprint mismatch' }
  const runner = new NativeCollaborationRunner('/app/rhwp-worker', executor)

  await assert.rejects(
    runner.importDocument('/tmp/source.hwp', '/tmp/manifest.json'),
    /fingerprint mismatch/,
  )
})
