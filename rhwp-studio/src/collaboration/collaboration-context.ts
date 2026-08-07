import { parseCollaborationManifest } from './manifest-parser.ts';
import { CollaborationNodeRegistry } from './node-registry.ts';
import type { CollaborationManifest } from './types.ts';

export interface CollaborationDocumentLike {
  getCollaborationManifest(sourceFingerprint: string): string;
}
export interface CollaborationContext {
  readonly sourceFingerprint: string;
  readonly manifest: CollaborationManifest;
  readonly registry: CollaborationNodeRegistry;
}
export function createCollaborationContext(document: CollaborationDocumentLike, sourceFingerprint: string): CollaborationContext {
  const manifest = parseCollaborationManifest(document.getCollaborationManifest(sourceFingerprint), sourceFingerprint);
  return Object.freeze({ sourceFingerprint, manifest, registry: CollaborationNodeRegistry.fromManifest(manifest) });
}
