import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as Y from 'yjs';

import {
  LOCAL_COLLABORATION_ORIGIN,
  RhwpYjsAdapter,
} from '../src/collaboration/RhwpYjsAdapter.ts';
import type {
  CollaborationManifest,
  CollaborationPatch,
} from '../src/collaboration/wasm-adapter.ts';

class FakeEvents {
  private readonly listeners = new Map<string, Set<() => void>>();

  on(event: string, listener: () => void): void {
    const listeners = this.listeners.get(event) ?? new Set();
    listeners.add(listener);
    this.listeners.set(event, listeners);
  }

  off(event: string, listener: () => void): void {
    this.listeners.get(event)?.delete(listener);
  }

  emit(event: string): void {
    for (const listener of this.listeners.get(event) ?? []) listener();
  }
}

function manifest(paragraphText = '원본', cellText = '셀 원본'): CollaborationManifest {
  return {
    schema_version: 1,
    source_fingerprint: 'blake3:fixture',
    sections: [
      {
        id: 'section-1',
        paragraphs: [{ id: 'paragraph-1', text: paragraphText, style_ref: 0 }],
        tables: [
          {
            id: 'table-1',
            rows: [{ id: 'row-1', cell_ids: ['cell-1'] }],
            cells: [
              {
                id: 'cell-1',
                text: cellText,
                style_ref: 0,
                structure_readonly: true,
              },
            ],
            structure_readonly: true,
          },
        ],
      },
    ],
    readonly_objects: [],
  };
}

test('initializes paragraph and cell Y.Text values without applying a remote patch', () => {
  const document = new Y.Doc();
  const events = new FakeEvents();
  const patches: CollaborationPatch[] = [];
  const bridge = {
    getManifest: () => manifest(),
    applyPatch: (_manifest: CollaborationManifest, patch: CollaborationPatch) => {
      patches.push(patch);
      return { updatedParagraphs: 0, updatedCells: 0, insertedImages: 0 };
    },
  };
  const adapter = new RhwpYjsAdapter(document, bridge, events);

  adapter.initialize(manifest());

  assert.equal(document.getText('paragraph:paragraph-1').toString(), '원본');
  assert.equal(document.getText('cell:cell-1').toString(), '셀 원본');
  assert.deepEqual(patches, []);
  adapter.destroy();
});

test('local document changes use the local origin and do not echo back into WASM', () => {
  const document = new Y.Doc();
  const events = new FakeEvents();
  let current = manifest();
  const origins: unknown[] = [];
  const patches: CollaborationPatch[] = [];
  document.on('afterTransaction', (transaction) => origins.push(transaction.origin));
  const bridge = {
    getManifest: () => current,
    applyPatch: (_manifest: CollaborationManifest, patch: CollaborationPatch) => {
      patches.push(patch);
      return { updatedParagraphs: 0, updatedCells: 0, insertedImages: 0 };
    },
  };
  const adapter = new RhwpYjsAdapter(document, bridge, events);
  adapter.initialize(current);
  origins.length = 0;

  current = manifest('로컬 변경', '셀 로컬 변경');
  events.emit('document-changed');

  assert.equal(document.getText('paragraph:paragraph-1').toString(), '로컬 변경');
  assert.equal(document.getText('cell:cell-1').toString(), '셀 로컬 변경');
  assert(origins.includes(LOCAL_COLLABORATION_ORIGIN));
  assert.deepEqual(patches, []);
  adapter.destroy();
});

test('remote Yjs transaction applies one stable-id patch and emits a view refresh', () => {
  const document = new Y.Doc();
  const events = new FakeEvents();
  const patches: CollaborationPatch[] = [];
  let refreshes = 0;
  events.on('document-view-changed', () => refreshes += 1);
  const bridge = {
    getManifest: () => manifest(),
    applyPatch: (_manifest: CollaborationManifest, patch: CollaborationPatch) => {
      patches.push(patch);
      return {
        updatedParagraphs: patch.paragraphs.length,
        updatedCells: patch.cells.length,
        insertedImages: 0,
      };
    },
  };
  const adapter = new RhwpYjsAdapter(document, bridge, events);
  adapter.initialize(manifest());

  document.transact(() => {
    const paragraph = document.getText('paragraph:paragraph-1');
    paragraph.delete(0, paragraph.length);
    paragraph.insert(0, '원격 본문');
    const cell = document.getText('cell:cell-1');
    cell.delete(0, cell.length);
    cell.insert(0, '원격 셀');
  }, { remote: true });

  assert.equal(patches.length, 1);
  assert.deepEqual(patches[0], {
    paragraphs: [{ target_id: 'paragraph-1', text: '원격 본문' }],
    cells: [{ target_id: 'cell-1', text: '원격 셀' }],
    inserted_images: [],
  });
  assert.equal(refreshes, 1);
  adapter.destroy();
});
