import { CollaborationManifestError } from './errors.ts';
import {
  COLLABORATION_SCHEMA_VERSION,
  type CollaborationManifest,
} from './types.ts';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new CollaborationManifestError(`${label}가 객체가 아닙니다.`);
  return value;
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new CollaborationManifestError(`${label}가 배열이 아닙니다.`);
  return value;
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new CollaborationManifestError(`${label}가 비어 있거나 문자열이 아닙니다.`);
  }
  return value;
}

function requireIndex(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new CollaborationManifestError(`유효하지 않은 ${label}입니다.`);
  }
  return value as number;
}

function registerId(ids: Set<string>, value: unknown): string {
  const id = requireString(value, 'StableId');
  if (ids.has(id)) throw new CollaborationManifestError(`중복 StableId: ${id}`);
  ids.add(id);
  return id;
}

export function parseCollaborationManifest(
  json: string,
  expectedFingerprint: string,
): CollaborationManifest {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch (error) {
    throw new CollaborationManifestError(`협업 manifest JSON을 파싱할 수 없습니다: ${String(error)}`);
  }

  const root = requireRecord(raw, 'manifest');
  if (root.schema_version !== COLLABORATION_SCHEMA_VERSION) {
    throw new CollaborationManifestError(
      `지원하지 않는 협업 schema version: ${String(root.schema_version)}`,
    );
  }
  const sourceFingerprint = requireString(root.source_fingerprint, 'source_fingerprint');
  if (sourceFingerprint !== expectedFingerprint) {
    throw new CollaborationManifestError('협업 manifest fingerprint가 일치하지 않습니다.');
  }

  const ids = new Set<string>();
  const sections = requireArray(root.sections, 'sections');
  for (const sectionValue of sections) {
    const section = requireRecord(sectionValue, 'section');
    registerId(ids, section.id);
    const paragraphs = requireArray(section.paragraphs, 'paragraphs');
    for (const paragraphValue of paragraphs) {
      const paragraph = requireRecord(paragraphValue, 'paragraph');
      registerId(ids, paragraph.id);
      requireString(paragraph.text === '' ? ' ' : paragraph.text, 'paragraph text');
      const location = requireRecord(paragraph.location, 'paragraph location');
      requireIndex(location.section_index, 'paragraph location');
      requireIndex(location.paragraph_index, 'paragraph location');
    }

    const tables = requireArray(section.tables, 'tables');
    for (const tableValue of tables) {
      const table = requireRecord(tableValue, 'table');
      registerId(ids, table.id);
      for (const rowValue of requireArray(table.rows, 'rows')) {
        const row = requireRecord(rowValue, 'row');
        registerId(ids, row.id);
        for (const cellId of requireArray(row.cell_ids, 'cell_ids')) requireString(cellId, 'cell id');
      }
      for (const cellValue of requireArray(table.cells, 'cells')) {
        const cell = requireRecord(cellValue, 'cell');
        registerId(ids, cell.id);
        if (typeof cell.text !== 'string') throw new CollaborationManifestError('cell text가 문자열이 아닙니다.');
        const location = requireRecord(cell.location, 'cell location');
        for (const key of [
          'section_index', 'host_paragraph_index', 'control_index',
          'cell_index', 'row_index', 'column_index',
        ]) requireIndex(location[key], 'cell location');
      }
    }
  }

  for (const readonlyValue of requireArray(root.readonly_objects, 'readonly_objects')) {
    const readonly = requireRecord(readonlyValue, 'readonly object');
    registerId(ids, readonly.id);
    requireString(readonly.kind, 'readonly kind');
  }

  return raw as CollaborationManifest;
}
