use crate::model::control::Control;
use crate::model::document::Document;

use super::{validate_source_fingerprint, CollaborationError, NodeKind, StableId};

fn validate_id(
    source_fingerprint: &str,
    kind: NodeKind,
    path: &[u32],
    stable_id: &str,
) -> Result<(), CollaborationError> {
    validate_source_fingerprint(source_fingerprint)?;
    let expected = StableId::for_node(source_fingerprint, kind, path);
    if expected.0 != stable_id {
        return Err(CollaborationError::StableIdMismatch {
            expected: expected.0,
            actual: stable_id.to_string(),
        });
    }
    Ok(())
}

pub fn get_collaboration_paragraph_text(
    document: &Document,
    source_fingerprint: &str,
    section_index: u32,
    paragraph_index: u32,
    stable_id: &str,
) -> Result<String, CollaborationError> {
    validate_id(
        source_fingerprint,
        NodeKind::Paragraph,
        &[section_index, paragraph_index],
        stable_id,
    )?;
    document
        .sections
        .get(section_index as usize)
        .and_then(|section| section.paragraphs.get(paragraph_index as usize))
        .map(|paragraph| paragraph.text.clone())
        .ok_or(CollaborationError::TargetOutOfBounds {
            kind: "paragraph".to_string(),
        })
}

pub fn get_collaboration_cell_text(
    document: &Document,
    source_fingerprint: &str,
    section_index: u32,
    host_paragraph_index: u32,
    control_index: u32,
    cell_index: u32,
    stable_id: &str,
) -> Result<String, CollaborationError> {
    validate_id(
        source_fingerprint,
        NodeKind::Cell,
        &[
            section_index,
            host_paragraph_index,
            control_index,
            cell_index,
        ],
        stable_id,
    )?;
    let control = document
        .sections
        .get(section_index as usize)
        .and_then(|section| section.paragraphs.get(host_paragraph_index as usize))
        .and_then(|paragraph| paragraph.controls.get(control_index as usize))
        .ok_or(CollaborationError::TargetOutOfBounds {
            kind: "cell".to_string(),
        })?;
    let table = match control {
        Control::Table(table) => table.as_ref(),
        _ => {
            return Err(CollaborationError::TargetKindMismatch {
                expected: "table".to_string(),
            })
        }
    };
    let cell =
        table
            .cells
            .get(cell_index as usize)
            .ok_or(CollaborationError::TargetOutOfBounds {
                kind: "cell".to_string(),
            })?;
    if cell.paragraphs.len() != 1 {
        return Err(CollaborationError::UnsupportedCellParagraphStructure {
            paragraph_count: cell.paragraphs.len(),
        });
    }
    Ok(cell.paragraphs[0].text.clone())
}
