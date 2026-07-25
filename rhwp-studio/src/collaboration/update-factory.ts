import type { CollaborationTextUpdate } from './update.ts';
export class CollaborationUpdateFactory {
  private sequence = 0;
  private readonly clientId: string;
  private readonly documentFingerprint: string;
  constructor(clientId: string, documentFingerprint: string) {
    if (!clientId.trim()) throw new Error('clientId must be non-empty');
    this.clientId = clientId;
    this.documentFingerprint = documentFingerprint;
  }
  create(nodeId: string, nodeKind: 'paragraph' | 'cell', text: string): CollaborationTextUpdate {
    const sequence = this.sequence++;
    return { version: 1, updateId: `${this.clientId}:${sequence}`, documentFingerprint: this.documentFingerprint, nodeId, nodeKind, text, clientId: this.clientId, sequence };
  }
}
