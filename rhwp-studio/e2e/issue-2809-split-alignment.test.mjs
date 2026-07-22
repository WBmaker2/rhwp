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
const OUTPUT_EDITOR_PNG = path.join(OUTPUT_DIR, 'jubo_p2_rhwp_editor_100.png');

runTest('Issue #2809 위·아래 Split 문단 속성 차이 회귀', async ({ page }) => {
  setTestCase('이슈 원본 HWP WASM 렌더');
  const input = await page.$('#file-input');
  if (!input) throw new Error('file-input not found');
  await input.uploadFile(FIXTURE);
  await page.waitForFunction(
    () => window.__wasm?.getSourceFormat?.() === 'hwp' && window.__wasm.pageCount === 6,
    { timeout: 30000 },
  );
  await waitForCanvas(page, 30000);

  await page.waitForFunction(
    () => Array.from(document.querySelectorAll('button')).some(
      (candidate) => candidate.textContent?.includes('대체 글꼴로 보기'),
    ),
    { timeout: 5000 },
  ).catch(() => {});
  const dismissedFontDialog = await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('button')).find(
      (candidate) => candidate.textContent?.includes('대체 글꼴로 보기'),
    );
    if (!(button instanceof HTMLButtonElement)) return false;
    button.click();
    return true;
  });
  if (dismissedFontDialog) {
    await new Promise((resolve) => setTimeout(resolve, 300));
  }

  const result = await page.evaluate(() => {
    const doc = window.__wasm?.doc;
    if (!doc || typeof doc.renderPageToCanvas !== 'function') {
      throw new Error('WASM Canvas 렌더러를 찾을 수 없습니다');
    }
    const canvas = document.createElement('canvas');
    doc.renderPageToCanvas(1, canvas, 2);
    const svg = window.__wasm.renderPageSvg(1);
    const labels = Array.from(svg.matchAll(
      /<text x="([0-9.]+)"[^>]*>다<\/text>\s*<text x="([0-9.]+)"[^>]*>같<\/text>\s*<text x="([0-9.]+)"[^>]*>이<\/text>/g,
    ), (match) => match.slice(1).map(Number));
    const layerTree = JSON.parse(window.__wasm.getPageLayerTree(1));
    const layerLabelPositions = [];
    const visit = (value) => {
      if (!value || typeof value !== 'object') return;
      if (value.type === 'textRun' && value.text === '다 같 이') {
        layerLabelPositions.push(value.positions ?? []);
      }
      for (const child of Object.values(value)) visit(child);
    };
    visit(layerTree);
    return {
      dataUrl: canvas.toDataURL('image/png'),
      width: canvas.width,
      height: canvas.height,
      labels,
      layerLabelPositions,
      hasSplitLabel: svg.includes('>다</text>') && svg.includes('>같</text>') && svg.includes('>이</text>'),
    };
  });

  mkdirSync(OUTPUT_DIR, { recursive: true });
  writeFileSync(OUTPUT_PNG, Buffer.from(result.dataUrl.split(',')[1], 'base64'));

  await page.evaluate(() => {
    const view = window.__canvasView;
    view.viewportManager.setZoom(1.0);
    view.container.scrollTop = view.virtualScroll.getPageOffset(1);
    view.updateVisiblePages();
  });
  await page.waitForFunction(() => !!window.__canvasView?.canvasPool?.getCanvas(1), {
    timeout: 30000,
  });
  await new Promise((resolve) => setTimeout(resolve, 500));
  await page.screenshot({ path: OUTPUT_EDITOR_PNG });

  assert(result.width > 1000 && result.height > 1500, `2x canvas 생성 (${result.width}×${result.height})`);
  assert(result.hasSplitLabel, 'WASM SVG에 다/같/이 라벨 존재');
  assert(result.labels.length >= 6, '위·아래 Split 라벨 좌표 추출');
  const topSpan = result.labels[0]?.[2] - result.labels[0]?.[0];
  const bottomSpan = result.labels.at(-1)?.[2] - result.labels.at(-1)?.[0];
  assert(
    Number.isFinite(topSpan) && Number.isFinite(bottomSpan) && topSpan - bottomSpan > 6,
    `위쪽 음수 자간/6972HU와 아래쪽 자간 0%/6872HU의 분배 폭 차이 유지 (${topSpan} / ${bottomSpan})`,
  );
  const topLayerSpan = result.layerLabelPositions[0]?.[4] - result.layerLabelPositions[0]?.[0];
  const bottomLayerSpan = result.layerLabelPositions.at(-1)?.[4]
    - result.layerLabelPositions.at(-1)?.[0];
  assert(
    Number.isFinite(topLayerSpan)
      && Number.isFinite(bottomLayerSpan)
      && topLayerSpan - bottomLayerSpan > 6,
    `WASM 페이지 레이어 트리의 위·아래 분배 폭 차이 유지 (${topLayerSpan} / ${bottomLayerSpan})`,
  );
  console.log(`  Evidence: ${OUTPUT_PNG}`);
  console.log(`  Editor evidence: ${OUTPUT_EDITOR_PNG}`);
});
