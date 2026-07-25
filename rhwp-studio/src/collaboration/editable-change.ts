export type CollaborationEditableChange =
  | { kind: 'paragraph'; sectionIndex: number; paragraphIndex: number }
  | { kind: 'cell'; sectionIndex: number; hostParagraphIndex: number; controlIndex: number; cellIndex: number }
  | { kind: 'structure'; reason: string };
export interface CollaborationEditSource { subscribe(handler: (change: CollaborationEditableChange) => void): () => void; }
