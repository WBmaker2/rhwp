import * as Y from 'yjs';

import type {
  CollaborationManifest,
  CollaborationPatch,
} from './wasm-adapter';

export const LOCAL_COLLABORATION_ORIGIN = Symbol('rhwp-local-collaboration');
const INITIALIZE_ORIGIN = Symbol('rhwp-collaboration-initialize');

export interface CollaborationWasmPort {
  getManifest(sourceFingerprint?: string): CollaborationManifest;
  applyPatch(manifest: CollaborationManifest, patch: CollaborationPatch): {
    updatedParagraphs: number;
    updatedCells: number;
    insertedImages: number;
  };
}

export interface CollaborationEventPort {
  on(event: string, listener: () => void): (() => void) | void;
  emit(event: string): void;
}

export interface RhwpYjsAdapterOptions {
  readOnly?: boolean;
}

export class RhwpYjsAdapter {
  private manifest: CollaborationManifest | null = null;
  private initialized = false;
  private applyingRemote = false;
  private readonly readOnly: boolean;
  private unsubscribeDocumentChanged: (() => void) | null = null;

  private readonly onDocumentChanged = (): void => {
    if (this.readOnly || !this.initialized || this.applyingRemote || !this.manifest) return;
    const current = this.bridge.getManifest(this.manifest.source_fingerprint);
    this.document.transact(() => this.writeManifestText(current), LOCAL_COLLABORATION_ORIGIN);
  };

  private readonly onAfterTransaction = (transaction: Y.Transaction): void => {
    if (
      !this.initialized
      || this.applyingRemote
      || !this.manifest
      || transaction.origin === LOCAL_COLLABORATION_ORIGIN
      || transaction.origin === INITIALIZE_ORIGIN
    ) {
      return;
    }

    const current = this.bridge.getManifest(this.manifest.source_fingerprint);
    const patch = this.buildPatch(current);
    if (patch.paragraphs.length === 0 && patch.cells.length === 0) return;

    this.applyingRemote = true;
    try {
      this.bridge.applyPatch(this.manifest, patch);
      this.events.emit('document-view-changed');
    } finally {
      this.applyingRemote = false;
    }
  };

  constructor(
    private readonly document: Y.Doc,
    private readonly bridge: CollaborationWasmPort,
    private readonly events: CollaborationEventPort,
    options: RhwpYjsAdapterOptions = {},
  ) {
    this.readOnly = options.readOnly === true;
  }

  initialize(manifest: CollaborationManifest): void {
    if (this.initialized) this.destroy();
    this.manifest = manifest;
    this.document.transact(() => this.writeManifestText(manifest), INITIALIZE_ORIGIN);
    this.document.on('afterTransaction', this.onAfterTransaction);
    if (!this.readOnly) {
      this.unsubscribeDocumentChanged = this.events.on(
        'document-changed',
        this.onDocumentChanged,
      ) ?? null;
    }
    this.initialized = true;
  }

  destroy(): void {
    this.document.off('afterTransaction', this.onAfterTransaction);
    this.unsubscribeDocumentChanged?.();
    this.unsubscribeDocumentChanged = null;
    this.initialized = false;
    this.applyingRemote = false;
    this.manifest = null;
  }

  private writeManifestText(manifest: CollaborationManifest): void {
    for (const section of manifest.sections) {
      for (const paragraph of section.paragraphs) {
        replaceText(this.document.getText(`paragraph:${paragraph.id}`), paragraph.text);
      }
      for (const table of section.tables) {
        for (const cell of table.cells) {
          replaceText(this.document.getText(`cell:${cell.id}`), cell.text);
        }
      }
    }
  }

  private buildPatch(current: CollaborationManifest): CollaborationPatch {
    const paragraphs: CollaborationPatch['paragraphs'] = [];
    const cells: CollaborationPatch['cells'] = [];

    for (const section of current.sections) {
      for (const paragraph of section.paragraphs) {
        const text = this.document.getText(`paragraph:${paragraph.id}`).toString();
        if (text !== paragraph.text) paragraphs.push({ target_id: paragraph.id, text });
      }
      for (const table of section.tables) {
        for (const cell of table.cells) {
          const text = this.document.getText(`cell:${cell.id}`).toString();
          if (text !== cell.text) cells.push({ target_id: cell.id, text });
        }
      }
    }

    return { paragraphs, cells, inserted_images: [] };
  }
}

function replaceText(target: Y.Text, value: string): void {
  const current = target.toString();
  if (current === value) return;
  if (target.length > 0) target.delete(0, target.length);
  if (value.length > 0) target.insert(0, value);
}
