import type { WasmBridge } from '@/core/wasm-bridge';

export type CollaborationStableId = string;

export interface CollaborationParagraphManifest {
  id: CollaborationStableId;
  text: string;
  style_ref: number | null;
}

export interface CollaborationCellManifest {
  id: CollaborationStableId;
  text: string;
  style_ref: number | null;
  structure_readonly: boolean;
}

export interface CollaborationManifest {
  schema_version: number;
  source_fingerprint: string;
  sections: Array<{
    id: CollaborationStableId;
    paragraphs: CollaborationParagraphManifest[];
    tables: Array<{
      id: CollaborationStableId;
      cells: CollaborationCellManifest[];
      rows: Array<{
        id: CollaborationStableId;
        cell_ids: CollaborationStableId[];
      }>;
      structure_readonly: boolean;
    }>;
  }>;
  readonly_objects: Array<{
    id: CollaborationStableId;
    kind: string;
  }>;
}

export interface CollaborationTextReplacement {
  target_id: CollaborationStableId;
  text: string;
}

export interface CollaborationImagePatch {
  id: CollaborationStableId;
  anchor_paragraph_id: CollaborationStableId;
  asset_path: string;
  bytes: number[];
  media_type: 'png' | 'jpeg' | 'webp';
  width: number;
  height: number;
  natural_width_px: number;
  natural_height_px: number;
  description: string;
}

export interface CollaborationPatch {
  paragraphs: CollaborationTextReplacement[];
  cells: CollaborationTextReplacement[];
  inserted_images: CollaborationImagePatch[];
}

export interface CollaborationApplyReport {
  updatedParagraphs: number;
  updatedCells: number;
  insertedImages: number;
}

interface RawCollaborationDocument {
  getCollaborationManifest(sourceFingerprint: string): string;
  applyCollaborationPatch(manifestJson: string, patchJson: string): string;
}

interface WasmBridgePrivateBoundary {
  doc: RawCollaborationDocument | null;
  documentDigest: string | null;
}

/**
 * Keeps the generated wasm-bindgen surface behind one typed boundary.
 * `WasmBridge.doc` is TypeScript-private but is a normal runtime field; no
 * application module outside this adapter reaches into it.
 */
export class RhwpCollaborationWasmAdapter {
  constructor(private readonly wasm: WasmBridge) {}

  getManifest(sourceFingerprint?: string): CollaborationManifest {
    const boundary = this.boundary();
    const fingerprint = sourceFingerprint ?? boundary.documentDigest ?? '';
    if (!fingerprint) {
      throw new Error('협업 source fingerprint가 필요합니다.');
    }

    return JSON.parse(
      boundary.doc!.getCollaborationManifest(fingerprint),
    ) as CollaborationManifest;
  }

  applyPatch(
    manifest: CollaborationManifest,
    patch: CollaborationPatch,
  ): CollaborationApplyReport {
    const boundary = this.boundary();
    return JSON.parse(
      boundary.doc!.applyCollaborationPatch(
        JSON.stringify(manifest),
        JSON.stringify(patch),
      ),
    ) as CollaborationApplyReport;
  }

  private boundary(): WasmBridgePrivateBoundary {
    const boundary = this.wasm as unknown as WasmBridgePrivateBoundary;
    if (!boundary.doc) {
      throw new Error('문서가 로드되지 않았습니다.');
    }
    return boundary;
  }
}
