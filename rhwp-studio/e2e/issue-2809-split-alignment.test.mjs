#!/usr/bin/env node

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { assert, runTest, setTestCase, waitForCanvas } from './helpers.mjs';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(E2E_DIR, '..', '..');
const FIXTURE = path.join(REPO_ROOT, 'samples', 'issues', '2809', 'jubo_20260104.hwp');
const OUTPUT_DIR = path.join(REPO_ROOT, 'mydocs', 'pr', 'assets', 'task2809');
const OUTPUT_PNG = path.join(OUTPUT_DIR, 'jubo_p2_wasm_canvas_2x.png');

runTest('Issue #2809 Split 마지막 줄과 음수 자간 clip 회귀', async ({ page }) => {
  setTestCase('이슈 원본 HWP WASM 렌더');
  const input = await page.$('#file-input');
  if (!input) throw new Error('file-input not found');
  await input.uploadFile(FIXTURE);
  await page.waitForFunction(
    () => window.__wasm?.getSourceFormat?.() === 'hwp' && window.__wasm.pageCount === 6,
    { timeout: 30000 },
  );
  await waitForCanvas(page, 30000);

  const result = await page.evaluate(() => {
    const doc = window.__wasm?.doc;
    if (!doc || typeof doc.renderPageToCanvas !== 'function') {
      throw new Error('WASM Canvas 렌더러를 찾을 수 없습니다');
    }
    const canvas = document.createElement('canvas');
    doc.renderPageToCanvas(1, canvas, 2);
    const svg = window.__wasm.renderPageSvg(1);
    const topLabel = svg.match(
      /<text x="([0-9.]+)"[^>]*>다<\/text>\s*<text x="([0-9.]+)"[^>]*>같<\/text>\s*<text x="([0-9.]+)"[^>]*>이<\/text>/,
    );
    return {
      dataUrl: canvas.toDataURL('image/png'),
      width: canvas.width,
      height: canvas.height,
      topLabel: topLabel?.slice(1).map(Number) ?? [],
      hasSplitLabel: svg.includes('>다</text>') && svg.includes('>같</text>') && svg.includes('>이</text>'),
    };
  });

  mkdirSync(OUTPUT_DIR, { recursive: true });
  writeFileSync(OUTPUT_PNG, Buffer.from(result.dataUrl.split(',')[1], 'base64'));

  assert(result.width > 1000 && result.height > 1500, `2x canvas 생성 (${result.width}×${result.height})`);
  assert(result.hasSplitLabel, 'WASM SVG에 다/같/이 라벨 존재');
  assert(result.topLabel.length === 3, '첫 Split 라벨 문자 좌표 추출');
  assert(
    result.topLabel.length === 3 && result.topLabel[2] < 495,
    `음수 자간 마지막 글자가 clip 안쪽으로 보정됨 (${result.topLabel.join(' / ')})`,
  );
  console.log(`  Evidence: ${OUTPUT_PNG}`);
});
