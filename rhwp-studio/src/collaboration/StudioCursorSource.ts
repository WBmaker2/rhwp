import { blake3 } from '@noble/hashes/blake3.js';
import { bytesToHex } from '@noble/hashes/utils.js';

import type { CursorRect, DocumentPosition } from '@/core/types';
import type { CursorPresenceSource } from './CollaborationController';
import type { PresenceCursor, RemoteParticipant } from './PresenceController';
import type { CollaborationManifest } from './wasm-adapter';

export interface StudioCursorSnapshot {
  position: DocumentPosition;
  selection: {
    anchor: DocumentPosition;
    focus: DocumentPosition;
  } | null;
}

export interface RemoteGeometryPort {
  getCursorRect(position: DocumentPosition): CursorRect | null;
}

export interface RemoteLayoutPort {
  getPageOffset(pageIndex: number): number;
  getPageLeft(pageIndex: number): number;
  getPageWidth(pageIndex: number): number;
  getZoom(): number;
  getContentWidth(): number;
}

export class StudioCursorSource implements CursorPresenceSource {
  private readonly listeners = new Set<(cursor: PresenceCursor | null) => void>();
  private snapshot: StudioCursorSnapshot | null = null;

  constructor(private readonly sourceFingerprint: string) {}

  publish(snapshot: StudioCursorSnapshot | null): void {
    this.snapshot = snapshot;
    const cursor = snapshot ? cursorFromSnapshot(this.sourceFingerprint, snapshot) : null;
    for (const listener of this.listeners) listener(cursor);
  }

  subscribe(listener: (cursor: PresenceCursor | null) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot ? cursorFromSnapshot(this.sourceFingerprint, this.snapshot) : null);
    return () => this.listeners.delete(listener);
  }
}

export function cursorFromSnapshot(
  sourceFingerprint: string,
  snapshot: StudioCursorSnapshot,
): PresenceCursor | null {
  const focus = targetForPosition(sourceFingerprint, snapshot.position);
  if (!focus) return null;
  const anchorPosition = snapshot.selection?.anchor;
  const anchor = anchorPosition
    ? targetForPosition(sourceFingerprint, anchorPosition)
    : focus;

  return {
    targetId: focus.targetId,
    targetKind: focus.targetKind,
    anchorOffset: anchor?.targetId === focus.targetId
      ? anchorPosition?.charOffset ?? snapshot.position.charOffset
      : snapshot.position.charOffset,
    headOffset: snapshot.position.charOffset,
  };
}

export function targetForPosition(
  sourceFingerprint: string,
  position: DocumentPosition,
): { targetId: string; targetKind: 'paragraph' | 'cell' } | null {
  const cellPath = position.cellPath;
  if (position.parentParaIndex !== undefined) {
    const outer = cellPath?.[0];
    const controlIndex = outer?.controlIndex ?? position.controlIndex;
    const cellIndex = outer?.cellIndex ?? position.cellIndex;
    if (controlIndex === undefined || cellIndex === undefined) return null;
    return {
      targetId: stableIdForNode(sourceFingerprint, 'cell', [
        position.sectionIndex,
        position.parentParaIndex,
        controlIndex,
        cellIndex,
      ]),
      targetKind: 'cell',
    };
  }

  return {
    targetId: stableIdForNode(sourceFingerprint, 'paragraph', [
      position.sectionIndex,
      position.paragraphIndex,
    ]),
    targetKind: 'paragraph',
  };
}

export function createRemoteCursorResolver(
  manifest: CollaborationManifest,
  geometry: RemoteGeometryPort,
  layout: RemoteLayoutPort,
): (participant: RemoteParticipant) => {
  left: number;
  top: number;
  height: number;
} | null {
  const targets = buildTargetIndex(manifest);
  return (participant) => {
    const target = targets.get(participant.state.targetId);
    if (!target) return null;
    const rect = geometry.getCursorRect({
      ...target,
      charOffset: participant.state.headOffset,
    });
    if (!rect) return null;

    const zoom = Math.max(0.01, layout.getZoom());
    const gridLeft = layout.getPageLeft(rect.pageIndex);
    const pageLeft = gridLeft >= 0
      ? gridLeft
      : (layout.getContentWidth() - layout.getPageWidth(rect.pageIndex)) / 2;
    return {
      left: pageLeft + rect.x * zoom,
      top: layout.getPageOffset(rect.pageIndex) + rect.y * zoom,
      height: rect.height * zoom,
    };
  };
}

export function stableIdForNode(
  sourceFingerprint: string,
  kind: 'section' | 'paragraph' | 'table' | 'row' | 'cell' | 'image' | 'readonly_object',
  path: number[],
): string {
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [
    encoder.encode('rhwp-collaboration-id-v1\0'),
    encoder.encode(sourceFingerprint),
    Uint8Array.of(0),
    encoder.encode(kind),
    Uint8Array.of(0),
  ];
  for (const value of path) {
    const bytes = new Uint8Array(4);
    new DataView(bytes.buffer).setUint32(0, value >>> 0, true);
    parts.push(bytes);
  }
  const length = parts.reduce((sum, part) => sum + part.length, 0);
  const input = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    input.set(part, offset);
    offset += part.length;
  }
  return bytesToHex(blake3(input));
}

function buildTargetIndex(
  manifest: CollaborationManifest,
): Map<string, Omit<DocumentPosition, 'charOffset'>> {
  const index = new Map<string, Omit<DocumentPosition, 'charOffset'>>();
  manifest.sections.forEach((section, sectionIndex) => {
    section.paragraphs.forEach((paragraph, paragraphIndex) => {
      index.set(paragraph.id, { sectionIndex, paragraphIndex });
    });
    for (const table of section.tables) {
      const host = findTableHost(manifest.source_fingerprint, sectionIndex, section.paragraphs.length, table.id);
      if (!host) continue;
      table.cells.forEach((cell, cellIndex) => {
        index.set(cell.id, {
          sectionIndex,
          paragraphIndex: host.paragraphIndex,
          parentParaIndex: host.paragraphIndex,
          controlIndex: host.controlIndex,
          cellIndex,
          cellParaIndex: 0,
        });
      });
    }
  });
  return index;
}

function findTableHost(
  fingerprint: string,
  sectionIndex: number,
  paragraphCount: number,
  tableId: string,
): { paragraphIndex: number; controlIndex: number } | null {
  for (let paragraphIndex = 0; paragraphIndex < paragraphCount; paragraphIndex += 1) {
    for (let controlIndex = 0; controlIndex < 256; controlIndex += 1) {
      if (stableIdForNode(fingerprint, 'table', [sectionIndex, paragraphIndex, controlIndex]) === tableId) {
        return { paragraphIndex, controlIndex };
      }
    }
  }
  return null;
}
