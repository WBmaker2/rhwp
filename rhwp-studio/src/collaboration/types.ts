export const COLLABORATION_SCHEMA_VERSION = 1;

export interface ParagraphLocation {
  section_index: number;
  paragraph_index: number;
}

export interface CellLocation {
  section_index: number;
  host_paragraph_index: number;
  control_index: number;
  cell_index: number;
  row_index: number;
  column_index: number;
}

export interface ParagraphManifest {
  id: string;
  text: string;
  style_ref: number | null;
  location: ParagraphLocation;
}

export interface CellManifest {
  id: string;
  text: string;
  style_ref: number | null;
  structure_readonly: boolean;
  location: CellLocation;
}

export interface RowManifest {
  id: string;
  cell_ids: string[];
}

export interface TableManifest {
  id: string;
  rows: RowManifest[];
  cells: CellManifest[];
  structure_readonly: boolean;
}

export interface SectionManifest {
  id: string;
  paragraphs: ParagraphManifest[];
  tables: TableManifest[];
}

export interface ReadonlyObjectManifest {
  id: string;
  kind: string;
}

export interface CollaborationManifest {
  schema_version: number;
  source_fingerprint: string;
  sections: SectionManifest[];
  readonly_objects: ReadonlyObjectManifest[];
}
