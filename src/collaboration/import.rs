use crate::model::control::Control;
use crate::model::document::Document;
use crate::model::paragraph::Paragraph;
use crate::model::table::Table;

use super::{
    validate_source_fingerprint, CellLocation, CellManifest, CollaborationError,
    CollaborationManifest, NodeKind, ParagraphLocation, ParagraphManifest, ReadonlyObjectManifest,
    RowManifest, SectionManifest, StableId, TableManifest,
};

pub fn build_collaboration_manifest(
    document: &Document,
    source_fingerprint: &str,
) -> Result<CollaborationManifest, CollaborationError> {
    validate_source_fingerprint(source_fingerprint)?;

    let mut manifest = CollaborationManifest::empty(source_fingerprint);

    for (section_index, section) in document.sections.iter().enumerate() {
        let section_path = [section_index as u32];
        let mut section_manifest = SectionManifest {
            id: StableId::for_node(source_fingerprint, NodeKind::Section, &section_path),
            paragraphs: Vec::with_capacity(section.paragraphs.len()),
            tables: Vec::new(),
        };

        for (paragraph_index, paragraph) in section.paragraphs.iter().enumerate() {
            let paragraph_path = [section_index as u32, paragraph_index as u32];
            section_manifest.paragraphs.push(import_paragraph(
                paragraph,
                source_fingerprint,
                &paragraph_path,
                section_index as u32,
                paragraph_index as u32,
            ));

            for (control_index, control) in paragraph.controls.iter().enumerate() {
                let control_path = [
                    section_index as u32,
                    paragraph_index as u32,
                    control_index as u32,
                ];

                match control {
                    Control::Table(table) => section_manifest.tables.push(import_table(
                        table,
                        source_fingerprint,
                        &control_path,
                        &mut manifest.readonly_objects,
                        section_index as u32,
                        paragraph_index as u32,
                        control_index as u32,
                    )),
                    other => push_readonly_object(
                        other,
                        source_fingerprint,
                        &control_path,
                        &mut manifest.readonly_objects,
                    ),
                }
            }
        }

        manifest.sections.push(section_manifest);
    }

    Ok(manifest)
}

fn import_paragraph(
    paragraph: &Paragraph,
    source_fingerprint: &str,
    path: &[u32],
    section_index: u32,
    paragraph_index: u32,
) -> ParagraphManifest {
    ParagraphManifest {
        id: StableId::for_node(source_fingerprint, NodeKind::Paragraph, path),
        text: paragraph.text.clone(),
        style_ref: Some(u32::from(paragraph.style_id)),
        location: ParagraphLocation {
            section_index,
            paragraph_index,
        },
    }
}

fn import_table(
    table: &Table,
    source_fingerprint: &str,
    path: &[u32],
    readonly_objects: &mut Vec<ReadonlyObjectManifest>,
    section_index: u32,
    host_paragraph_index: u32,
    control_index: u32,
) -> TableManifest {
    let mut rows = Vec::with_capacity(table.row_count as usize);
    let mut cells = Vec::with_capacity(table.cells.len());

    for row_index in 0..table.row_count {
        let mut row_path = path.to_vec();
        row_path.push(u32::from(row_index));
        let mut cell_ids = Vec::new();

        for (cell_index, cell) in table.cells.iter().enumerate() {
            if cell.row != row_index {
                continue;
            }

            let mut cell_path = path.to_vec();
            cell_path.push(cell_index as u32);
            let cell_id = StableId::for_node(source_fingerprint, NodeKind::Cell, &cell_path);
            cell_ids.push(cell_id.clone());
            cells.push(CellManifest {
                id: cell_id,
                text: cell
                    .paragraphs
                    .iter()
                    .map(|paragraph| paragraph.text.as_str())
                    .collect::<Vec<_>>()
                    .join("\n"),
                style_ref: cell
                    .paragraphs
                    .first()
                    .map(|paragraph| u32::from(paragraph.style_id)),
                structure_readonly: true,
                location: CellLocation {
                    section_index,
                    host_paragraph_index,
                    control_index,
                    cell_index: cell_index as u32,
                    row_index: u32::from(cell.row),
                    column_index: u32::from(cell.col),
                },
            });

            for (paragraph_index, paragraph) in cell.paragraphs.iter().enumerate() {
                let mut paragraph_path = cell_path.clone();
                paragraph_path.push(paragraph_index as u32);
                collect_nested_readonly_controls(
                    paragraph,
                    source_fingerprint,
                    &paragraph_path,
                    readonly_objects,
                );
            }
        }

        rows.push(RowManifest {
            id: StableId::for_node(source_fingerprint, NodeKind::Row, &row_path),
            cell_ids,
        });
    }

    TableManifest {
        id: StableId::for_node(source_fingerprint, NodeKind::Table, path),
        rows,
        cells,
        structure_readonly: true,
    }
}

fn collect_nested_readonly_controls(
    paragraph: &Paragraph,
    source_fingerprint: &str,
    paragraph_path: &[u32],
    readonly_objects: &mut Vec<ReadonlyObjectManifest>,
) {
    for (control_index, control) in paragraph.controls.iter().enumerate() {
        let mut control_path = paragraph_path.to_vec();
        control_path.push(control_index as u32);
        push_readonly_object(control, source_fingerprint, &control_path, readonly_objects);

        if let Control::Table(table) = control {
            collect_nested_table_controls(
                table,
                source_fingerprint,
                &control_path,
                readonly_objects,
            );
        }
    }
}

fn collect_nested_table_controls(
    table: &Table,
    source_fingerprint: &str,
    table_path: &[u32],
    readonly_objects: &mut Vec<ReadonlyObjectManifest>,
) {
    for (cell_index, cell) in table.cells.iter().enumerate() {
        let mut cell_path = table_path.to_vec();
        cell_path.push(cell_index as u32);

        for (paragraph_index, paragraph) in cell.paragraphs.iter().enumerate() {
            let mut paragraph_path = cell_path.clone();
            paragraph_path.push(paragraph_index as u32);
            collect_nested_readonly_controls(
                paragraph,
                source_fingerprint,
                &paragraph_path,
                readonly_objects,
            );
        }
    }
}

fn push_readonly_object(
    control: &Control,
    source_fingerprint: &str,
    path: &[u32],
    readonly_objects: &mut Vec<ReadonlyObjectManifest>,
) {
    readonly_objects.push(ReadonlyObjectManifest {
        id: StableId::for_node(source_fingerprint, NodeKind::ReadonlyObject, path),
        kind: readonly_control_kind(control).to_string(),
    });
}

fn readonly_control_kind(control: &Control) -> &'static str {
    match control {
        Control::Table(_) => "table",
        Control::Shape(_) => "shape",
        Control::Picture(_) => "picture",
        Control::Equation(_) => "equation",
        Control::Header(_) => "header",
        Control::Footer(_) => "footer",
        Control::Footnote(_) => "footnote",
        Control::Endnote(_) => "endnote",
        Control::Form(_) => "form",
        Control::Unknown(_) => "unknown",
        _ => "control",
    }
}
