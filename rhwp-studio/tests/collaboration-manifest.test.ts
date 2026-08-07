import test from 'node:test';
import assert from 'node:assert/strict';

import { parseCollaborationManifest } from '../src/collaboration/manifest-parser.ts';
import { CollaborationNodeRegistry } from '../src/collaboration/node-registry.ts';

const fingerprint = 'sha256:fixture';

function manifest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: 1,
    source_fingerprint: fingerprint,
    sections: [
      {
        id: 'section-0',
        paragraphs: [
          {
            id: 'paragraph-0',
            text: '본문',
            style_ref: 0,
            location: { section_index: 0, paragraph_index: 0 },
          },
        ],
        tables: [
          {
            id: 'table-0',
            rows: [{ id: 'row-0', cell_ids: ['cell-0'] }],
            cells: [
              {
                id: 'cell-0',
                text: '셀',
                style_ref: null,
                structure_readonly: true,
                location: {
                  section_index: 0,
                  host_paragraph_index: 1,
                  control_index: 0,
                  cell_index: 0,
                  row_index: 0,
                  column_index: 0,
                },
              },
            ],
            structure_readonly: true,
          },
        ],
      },
    ],
    readonly_objects: [{ id: 'readonly-0', kind: 'equation' }],
    ...overrides,
  };
}

test('manifest parser validates schema and fingerprint', () => {
  const parsed = parseCollaborationManifest(JSON.stringify(manifest()), fingerprint);
  assert.equal(parsed.schema_version, 1);
  assert.equal(parsed.sections[0].paragraphs[0].location.paragraph_index, 0);
});

test('manifest parser rejects unsupported schema', () => {
  assert.throws(
    () => parseCollaborationManifest(JSON.stringify(manifest({ schema_version: 2 })), fingerprint),
    /지원하지 않는 협업 schema version/,
  );
});

test('manifest parser rejects fingerprint mismatch', () => {
  assert.throws(
    () => parseCollaborationManifest(JSON.stringify(manifest()), 'sha256:other'),
    /fingerprint가 일치하지 않습니다/,
  );
});

test('manifest parser rejects duplicate stable IDs across editable and readonly nodes', () => {
  const duplicated = manifest({ readonly_objects: [{ id: 'paragraph-0', kind: 'equation' }] });
  assert.throws(
    () => parseCollaborationManifest(JSON.stringify(duplicated), fingerprint),
    /중복 StableId/,
  );
});

test('node registry maps paragraph and cell IDs and excludes readonly objects', () => {
  const parsed = parseCollaborationManifest(JSON.stringify(manifest()), fingerprint);
  const registry = CollaborationNodeRegistry.fromManifest(parsed);

  assert.deepEqual(registry.get('paragraph-0'), {
    kind: 'paragraph',
    sectionIndex: 0,
    paragraphIndex: 0,
  });
  assert.deepEqual(registry.get('cell-0'), {
    kind: 'cell',
    sectionIndex: 0,
    hostParagraphIndex: 1,
    controlIndex: 0,
    cellIndex: 0,
    rowIndex: 0,
    columnIndex: 0,
  });
  assert.equal(registry.has('readonly-0'), false);
  assert.equal(registry.size, 2);
});

test('manifest parser rejects negative source locations', () => {
  const invalid = manifest();
  const sections = invalid.sections as Array<any>;
  sections[0].paragraphs[0].location.paragraph_index = -1;
  assert.throws(
    () => parseCollaborationManifest(JSON.stringify(invalid), fingerprint),
    /유효하지 않은 paragraph location/,
  );
});
