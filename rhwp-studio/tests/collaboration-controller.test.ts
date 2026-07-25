import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as Y from 'yjs';

import { CollaborationController } from '../src/collaboration/CollaborationController.ts';
import type { CollaborationManifest } from '../src/collaboration/wasm-adapter.ts';

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

class FakeAwareness {
  readonly clientID = 1;
  readonly states = new Map<number, Record<string, unknown>>();
  private readonly listeners = new Set<() => void>();
  setLocalStateField(field: string, value: unknown): void {
    this.states.set(1, { ...(this.states.get(1) ?? {}), [field]: value });
    for (const listener of this.listeners) listener();
  }
  getStates(): Map<number, Record<string, unknown>> { return this.states; }
  on(_event: 'change', listener: () => void): void { this.listeners.add(listener); }
  off(_event: 'change', listener: () => void): void { this.listeners.delete(listener); }
}

function manifest(): CollaborationManifest {
  return {
    schema_version: 1,
    source_fingerprint: 'blake3:fixture',
    sections: [{
      id: 'section-1',
      paragraphs: [{ id: 'paragraph-1', text: '원본', style_ref: 0 }],
      tables: [],
    }],
    readonly_objects: [],
  };
}

test('connects with a Firebase token, publishes cursor presence, and destroys resources', async () => {
  const events = new FakeEvents();
  const awareness = new FakeAwareness();
  let providerDestroyed = 0;
  let receivedToken: string | null = null;
  const cursorListeners = new Set<(value: {
    targetId: string;
    targetKind: 'paragraph' | 'cell';
    anchorOffset: number;
    headOffset: number;
  } | null) => void>();
  const controller = new CollaborationController({
    documentId: 'doc-1',
    collaborationUrl: 'ws://localhost:1234',
    auth: {
      requireSession: async () => ({
        identity: { userId: 'editor-1', displayName: '편집자', photoURL: null },
        role: 'editor',
        idToken: 'firebase-token',
      }),
    },
    bridge: {
      getManifest: () => manifest(),
      applyPatch: () => ({ updatedParagraphs: 0, updatedCells: 0, insertedImages: 0 }),
    },
    events,
    cursor: {
      subscribe(listener) {
        cursorListeners.add(listener);
        return () => cursorListeners.delete(listener);
      },
    },
    providerFactory: (input) => {
      receivedToken = input.token;
      return {
        document: input.document,
        awareness,
        destroy: () => { providerDestroyed += 1; },
      };
    },
  });

  const state = await controller.connect();
  for (const listener of cursorListeners) {
    listener({ targetId: 'paragraph-1', targetKind: 'paragraph', anchorOffset: 2, headOffset: 4 });
  }

  assert.equal(receivedToken, 'firebase-token');
  assert.equal(state.role, 'editor');
  assert.equal((awareness.states.get(1)?.presence as { targetId: string }).targetId, 'paragraph-1');
  controller.destroy();
  assert.equal(providerDestroyed, 1);
  assert.equal(cursorListeners.size, 0);
});

test('viewer sessions receive remote state but local document changes are not written to Yjs', async () => {
  const events = new FakeEvents();
  const awareness = new FakeAwareness();
  const ydoc = new Y.Doc();
  let current = manifest();
  const controller = new CollaborationController({
    documentId: 'doc-1',
    collaborationUrl: 'ws://localhost:1234',
    auth: {
      requireSession: async () => ({
        identity: { userId: 'viewer-1', displayName: '열람자', photoURL: null },
        role: 'viewer',
        idToken: 'viewer-token',
      }),
    },
    bridge: {
      getManifest: () => current,
      applyPatch: () => ({ updatedParagraphs: 0, updatedCells: 0, insertedImages: 0 }),
    },
    events,
    cursor: { subscribe: () => () => undefined },
    providerFactory: (input) => ({
      document: ydoc,
      awareness,
      destroy: () => undefined,
    }),
  });

  await controller.connect();
  current = {
    ...current,
    sections: [{ ...current.sections[0], paragraphs: [{ ...current.sections[0].paragraphs[0], text: '로컬 탈취' }] }],
  };
  events.emit('document-changed');

  assert.equal(ydoc.getText('paragraph:paragraph-1').toString(), '원본');
  controller.destroy();
});
