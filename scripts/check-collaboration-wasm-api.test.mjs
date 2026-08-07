import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  COLLABORATION_WASM_METHODS,
  checkCollaborationWasmApi,
} from './check-collaboration-wasm-api.mjs';

test('accepts generated JavaScript and declarations containing all collaboration methods', () => {
  const directory = mkdtempSync(join(tmpdir(), 'rhwp-wasm-api-'));
  try {
    const content = COLLABORATION_WASM_METHODS.join('\n');
    writeFileSync(join(directory, 'rhwp.js'), content);
    writeFileSync(join(directory, 'rhwp.d.ts'), content);

    const result = checkCollaborationWasmApi(directory);
    assert.deepEqual(result.methods, COLLABORATION_WASM_METHODS);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('reports the missing method and target file', () => {
  const directory = mkdtempSync(join(tmpdir(), 'rhwp-wasm-api-'));
  try {
    const incomplete = COLLABORATION_WASM_METHODS.slice(0, -1).join('\n');
    writeFileSync(join(directory, 'rhwp.js'), incomplete);
    writeFileSync(join(directory, 'rhwp.d.ts'), incomplete);

    assert.throws(
      () => checkCollaborationWasmApi(directory),
      /getCollaborationCellText missing from/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
