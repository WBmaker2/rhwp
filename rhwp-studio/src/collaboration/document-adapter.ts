import type { CollaborationContext } from './collaboration-context.ts';
import { CollaborationContractError } from './errors.ts';
import { validateCollaborationTextUpdate, type CollaborationTextUpdate } from './update.ts';
export interface CollaborationMutableDocument {
  applyCollaborationParagraphText(fingerprint:string, section:number, paragraph:number, nodeId:string, text:string): string;
  applyCollaborationCellText(fingerprint:string, section:number, hostParagraph:number, control:number, cell:number, nodeId:string, text:string): string;
}
export class CollaborationDocumentAdapter {
  private readonly applied = new Set<string>();
  private applying = false;
  private readonly document: CollaborationMutableDocument;
  private readonly context: CollaborationContext;
  constructor(document: CollaborationMutableDocument, context: CollaborationContext) { this.document = document; this.context = context; }
  get isApplyingRemoteUpdate(): boolean { return this.applying; }
  applyRemoteUpdate(input: unknown): boolean {
    const update=validateCollaborationTextUpdate(input, this.context); if (this.applied.has(update.updateId)) return false;
    const location=this.context.registry.get(update.nodeId); if (!location) throw new CollaborationContractError('unknown collaboration node');
    this.applying=true;
    try {
      const raw=location.kind==='paragraph'
        ? this.document.applyCollaborationParagraphText(this.context.sourceFingerprint, location.sectionIndex, location.paragraphIndex, update.nodeId, update.text)
        : this.document.applyCollaborationCellText(this.context.sourceFingerprint, location.sectionIndex, location.hostParagraphIndex, location.controlIndex, location.cellIndex, update.nodeId, update.text);
      const report=JSON.parse(raw) as {updated?:unknown,node_id?:unknown};
      if (report.updated !== true || report.node_id !== update.nodeId) throw new CollaborationContractError('invalid collaboration apply report');
      this.applied.add(update.updateId); return true;
    } finally { this.applying=false; }
  }
}
