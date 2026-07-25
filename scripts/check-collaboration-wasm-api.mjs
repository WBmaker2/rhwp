import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export const COLLABORATION_WASM_METHODS = [
  'getCollaborationManifest',
  'applyCollaborationParagraphText',
  'applyCollaborationCellText',
  'getCollaborationParagraphText',
  'getCollaborationCellText',
];

export function checkCollaborationWasmApi(packageDirectory = 'pkg') {
  const jsPath = resolve(packageDirectory, 'rhwp.js');
  const declarationPath = resolve(packageDirectory, 'rhwp.d.ts');
  const javascript = readFileSync(jsPath, 'utf8');
  const declarations = readFileSync(declarationPath, 'utf8');

  for (const method of COLLABORATION_WASM_METHODS) {
    assert.match(javascript, new RegExp(`\\b${method}\\b`), `${method} missing from ${jsPath}`);
    assert.match(declarations, new RegExp(`\\b${method}\\b`), `${method} missing from ${declarationPath}`);
  }

  return {
    javascript: jsPath,
    declarations: declarationPath,
    methods: [...COLLABORATION_WASM_METHODS],
  };
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  const result = checkCollaborationWasmApi(process.argv[2] ?? 'pkg');
  console.log(`verified ${result.methods.length} collaboration WASM methods`);
}
