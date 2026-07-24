use std::collections::{HashMap, HashSet};

use crate::model::control::Control;
use crate::model::document::Document;
use crate::model::paragraph::Paragraph;

use super::import::CollaborationError;
use super::{CollaborationManifest, NodeKind, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TextReplacement {
    pub target_id: StableId,
    pub text: String,
}

/// Placeholder for the separate image-insertion RED-GREEN cycle.
///
/// The uninhabited type makes it impossible for callers to submit an image
/// patch before that contract is implemented, while preserving the planned
/// `inserted_images` field on `CollaborationPatch`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InsertedImagePatch {}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CollaborationPatch {
    pub paragraphs: Vec<TextReplacement>,
    pub cells: Vec<TextReplacement>,
    pub inserted_images: Vec<InsertedImagePatch>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ApplyReport {
    pub updated_paragraphs: usize,
    pub updated_cells: usize,
    pub inserted_images: usize,
}

pub fn apply_collaboration_patch(
    document: &mut Document,
    manifest: &CollaborationManifest,
    patch: &CollaborationPatch,
) -> Result<ApplyReport, CollaborationError> {
    let manifest_paragraph_ids: HashSet<StableId> = manifest
        .sections
        .iter()
        .flat_map(|section| section.paragraphs.iter())
        .map(|paragraph| paragraph.id.clone())
        .collect();
    let manifest_cell_ids: HashSet<StableId> = manifest
        .sections
        .iter()
        .flat_map(|section| section.tables.iter())
        .flat_map(|table| table.cells.iter())
        .map(|cell| cell.id.clone())
        .collect();
    let readonly_ids: HashSet<StableId> = manifest
        .readonly_objects
        .iter()
        .map(|object| object.id.clone())
        .collect();
    let (document_paragraph_ids, document_cell_ids) =
        collect_document_target_ids(document, &manifest.source_fingerprint);

    validate_replacements(
        &patch.paragraphs,
        &manifest_paragraph_ids,
        &document_paragraph_ids,
        &readonly_ids,
    )?;
    validate_replacements(
        &patch.cells,
        &manifest_cell_ids,
        &document_cell_ids,
        &readonly_ids,
    )?;

    let paragraph_updates: HashMap<StableId, &str> = patch
        .paragraphs
        .iter()
        .map(|replacement| (replacement.target_id.clone(), replacement.text.as_str()))
        .collect();
    let cell_updates: HashMap<StableId, &str> = patch
        .cells
        .iter()
        .map(|replacement| (replacement.target_id.clone(), replacement.text.as_str()))
        .collect();

    let mut report = ApplyReport::default();

    for (section_index, section) in document.sections.iter_mut().enumerate() {
        let mut section_changed = false;

        for (paragraph_index, paragraph) in section.paragraphs.iter_mut().enumerate() {
            let paragraph_path = [section_index as u32, paragraph_index as u32];
            let paragraph_id = StableId::for_node(
                &manifest.source_fingerprint,
                NodeKind::Paragraph,
                &paragraph_path,
            );

            if let Some(text) = paragraph_updates.get(&paragraph_id) {
                replace_paragraph_text(paragraph, text);
                report.updated_paragraphs += 1;
                section_changed = true;
            }

            for (control_index, control) in paragraph.controls.iter_mut().enumerate() {
                let Control::Table(table) = control else {
                    continue;
                };
                let mut table_changed = false;

                for (cell_index, cell) in table.cells.iter_mut().enumerate() {
                    let cell_path = [
                        section_index as u32,
                        paragraph_index as u32,
                        control_index as u32,
                        cell_index as u32,
                    ];
                    let cell_id = StableId::for_node(
                        &manifest.source_fingerprint,
                        NodeKind::Cell,
                        &cell_path,
                    );

                    let Some(text) = cell_updates.get(&cell_id) else {
                        continue;
                    };

                    if let Some(cell_paragraph) = cell.paragraphs.first_mut() {
                        replace_paragraph_text(cell_paragraph, text);
                    } else {
                        let mut cell_paragraph = Paragraph::new_empty();
                        replace_paragraph_text(&mut cell_paragraph, text);
                        cell.paragraphs.push(cell_paragraph);
                    }
                    cell.dirty_flag = true;
                    table_changed = true;
                    report.updated_cells += 1;
                }

                if table_changed {
                    table.dirty = true;
                    section_changed = true;
                }
            }
        }

        if section_changed {
            section.raw_stream = None;
        }
    }

    report.inserted_images = patch.inserted_images.len();
    Ok(report)
}

fn validate_replacements(
    replacements: &[TextReplacement],
    manifest_targets: &HashSet<StableId>,
    document_targets: &HashSet<StableId>,
    readonly_targets: &HashSet<StableId>,
) -> Result<(), CollaborationError> {
    for replacement in replacements {
        if readonly_targets.contains(&replacement.target_id) {
            return Err(CollaborationError::ReadonlyTarget(
                replacement.target_id.clone(),
            ));
        }
        if !manifest_targets.contains(&replacement.target_id)
            || !document_targets.contains(&replacement.target_id)
        {
            return Err(CollaborationError::UnknownTarget(
                replacement.target_id.clone(),
            ));
        }
    }

    Ok(())
}

fn collect_document_target_ids(
    document: &Document,
    source_fingerprint: &str,
) -> (HashSet<StableId>, HashSet<StableId>) {
    let mut paragraph_ids = HashSet::new();
    let mut cell_ids = HashSet::new();

    for (section_index, section) in document.sections.iter().enumerate() {
        for (paragraph_index, paragraph) in section.paragraphs.iter().enumerate() {
            let paragraph_path = [section_index as u32, paragraph_index as u32];
            paragraph_ids.insert(StableId::for_node(
                source_fingerprint,
                NodeKind::Paragraph,
                &paragraph_path,
            ));

            for (control_index, control) in paragraph.controls.iter().enumerate() {
                let Control::Table(table) = control else {
                    continue;
                };

                for cell_index in 0..table.cells.len() {
                    let cell_path = [
                        section_index as u32,
                        paragraph_index as u32,
                        control_index as u32,
                        cell_index as u32,
                    ];
                    cell_ids.insert(StableId::for_node(
                        source_fingerprint,
                        NodeKind::Cell,
                        &cell_path,
                    ));
                }
            }
        }
    }

    (paragraph_ids, cell_ids)
}

fn replace_paragraph_text(paragraph: &mut Paragraph, text: &str) {
    normalize_text_metadata(paragraph);
    let old_len = paragraph.text.chars().count();
    paragraph.delete_text_at(0, old_len);
    paragraph.insert_text_at(0, text);
    if !text.is_empty() {
        paragraph.has_para_text = true;
    }
}

fn normalize_text_metadata(paragraph: &mut Paragraph) {
    let characters: Vec<char> = paragraph.text.chars().collect();
    if paragraph.char_offsets.len() != characters.len() {
        let mut position = 0_u32;
        paragraph.char_offsets = characters
            .iter()
            .map(|character| {
                let offset = position;
                position += character.len_utf16() as u32;
                offset
            })
            .collect();
    }

    paragraph.char_count = paragraph.char_count.max(characters.len() as u32);
}
