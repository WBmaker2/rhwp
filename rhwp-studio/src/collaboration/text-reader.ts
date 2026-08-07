import type { CollaborationContext } from './collaboration-context.ts';
export interface CollaborationTextReadableDocument {
  getCollaborationParagraphText(fingerprint: string, section: number, paragraph: number, nodeId: string): string;
  getCollaborationCellText(fingerprint: string, section: number, hostParagraph: number, control: number, cell: number, nodeId: string): string;
}
export interface CollaborationTextReader { getParagraphText(nodeId: string): string; getCellText(nodeId: string): string; }
export class WasmCollaborationTextReader implements CollaborationTextReader {
  private readonly document: CollaborationTextReadableDocument;
  private readonly context: CollaborationContext;
  constructor(document: CollaborationTextReadableDocument, context: CollaborationContext) { this.document = document; this.context = context; }
  getParagraphText(nodeId: string): string {
    const loc = this.context.registry.get(nodeId); if (!loc || loc.kind !== 'paragraph') throw new Error('paragraph node not found');
    return this.document.getCollaborationParagraphText(this.context.sourceFingerprint, loc.sectionIndex, loc.paragraphIndex, nodeId);
  }
  getCellText(nodeId: string): string {
    const loc = this.context.registry.get(nodeId); if (!loc || loc.kind !== 'cell') throw new Error('cell node not found');
    return this.document.getCollaborationCellText(this.context.sourceFingerprint, loc.sectionIndex, loc.hostParagraphIndex, loc.controlIndex, loc.cellIndex, nodeId);
  }
}
