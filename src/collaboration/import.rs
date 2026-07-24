use std::error::Error;
use std::fmt;

use crate::model::control::Control;
use crate::model::document::Document;
use crate::model::paragraph::Paragraph;
use crate::model::table::Table;

use super::{
    CellManifest, CollaborationManifest, NodeKind, ParagraphManifest, ReadonlyObjectManifest,
    RowManifest, SectionManifest, StableId, TableManifest,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CollaborationError {
    EmptySourceFingerprint,
}

impl fmt::Display for CollaborationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptySourceFingerprint => {
                formatter.write_str("source fingerprint must not be empty")
            }
        }
    }
}

impl Error for CollaborationError {}

pub fn build_collaboration_manifest(
    document: &Document,
    source_fingerprint: &str,
) -> Result<CollaborationManifest, CollaborationError> {
    if source_fingerprint.is_empty() {
        return Err(CollaborationError::EmptySourceFingerprint);
    }

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
                    )),
                    other => manifest.readonly_objects.push(ReadonlyObjectManifest {
                        id: StableId::for_node(
                            source_fingerprint,
                            NodeKind::ReadonlyObject,
                            &control_path,
                        ),
                        kind: readonly_control_kind(other).to_string(),
                    }),
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
) -> ParagraphManifest {
    ParagraphManifest {
        id: StableId::for_node(source_fingerprint, NodeKind::Paragraph, path),
        text: paragraph.text.clone(),
        style_ref: Some(u32::from(paragraph.style_id)),
    }
}

fn import_table(table: &Table, source_fingerprint: &str, path: &[u32]) -> TableManifest {
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
                text: join_paragraph_text(&cell.paragraphs),
                style_ref: cell
                    .paragraphs
                    .first()
                    .map(|paragraph| u32::from(paragraph.style_id)),
                structure_readonly: true,
            });
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

fn join_paragraph_text(paragraphs: &[Paragraph]) -> String {
    paragraphs
        .iter()
        .map(|paragraph| paragraph.text.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

fn readonly_control_kind(control: &Control) -> &'static str {
    match control {
        Control::SectionDef(_) => "section_definition",
        Control::ColumnDef(_) => "column_definition",
        Control::Table(_) => "table",
        Control::Shape(_) => "shape",
        Control::Picture(_) => "picture",
        Control::Header(_) => "header",
        Control::Footer(_) => "footer",
        Control::Footnote(_) => "footnote",
        Control::Endnote(_) => "endnote",
        Control::AutoNumber(_) => "auto_number",
        Control::NewNumber(_) => "new_number",
        Control::PageNumberPos(_) => "page_number_position",
        Control::Bookmark(_) => "bookmark",
        Control::Hyperlink(_) => "hyperlink",
        Control::Ruby(_) => "ruby",
        Control::CharOverlap(_) => "character_overlap",
        Control::PageHide(_) => "page_hide",
        Control::HiddenComment(_) => "hidden_comment",
        Control::Equation(_) => "equation",
        Control::Field(_) => "field",
        Control::Form(_) => "form",
        Control::Unknown(_) => "unknown",
    }
}
