import type { CollaborationManifest } from './types.ts';

export type CollaborationNodeLocation =
  | { kind: 'paragraph'; sectionIndex: number; paragraphIndex: number }
  | {
      kind: 'cell';
      sectionIndex: number;
      hostParagraphIndex: number;
      controlIndex: number;
      cellIndex: number;
      rowIndex: number;
      columnIndex: number;
    };

export class CollaborationNodeRegistry {
  readonly #nodes: Map<string, CollaborationNodeLocation>;

  private constructor(nodes: Map<string, CollaborationNodeLocation>) {
    this.#nodes = nodes;
  }

  static fromManifest(manifest: CollaborationManifest): CollaborationNodeRegistry {
    const nodes = new Map<string, CollaborationNodeLocation>();
    for (const section of manifest.sections) {
      for (const paragraph of section.paragraphs) {
        nodes.set(paragraph.id, {
          kind: 'paragraph',
          sectionIndex: paragraph.location.section_index,
          paragraphIndex: paragraph.location.paragraph_index,
        });
      }
      for (const table of section.tables) {
        for (const cell of table.cells) {
          nodes.set(cell.id, {
            kind: 'cell',
            sectionIndex: cell.location.section_index,
            hostParagraphIndex: cell.location.host_paragraph_index,
            controlIndex: cell.location.control_index,
            cellIndex: cell.location.cell_index,
            rowIndex: cell.location.row_index,
            columnIndex: cell.location.column_index,
          });
        }
      }
    }
    return new CollaborationNodeRegistry(nodes);
  }

  entries(): IterableIterator<[string, CollaborationNodeLocation]> { return this.#nodes.entries(); }
  get(id: string): CollaborationNodeLocation | undefined { return this.#nodes.get(id); }
  has(id: string): boolean { return this.#nodes.has(id); }
  get size(): number { return this.#nodes.size; }
}
