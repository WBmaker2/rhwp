use std::collections::{HashMap, HashSet};

use crate::model::bin_data::{
    BinData, BinDataCompression, BinDataContent, BinDataStatus, BinDataType,
};
use crate::model::control::Control;
use crate::model::document::Document;
use crate::model::image::{CropInfo, ImageAttr, ImageEffect, Picture};
use crate::model::paragraph::Paragraph;
use crate::model::shape::{CommonObjAttr, HorzRelTo, ShapeComponentAttr, TextWrap, VertRelTo};

use super::import::CollaborationError;
use super::{CollaborationManifest, NodeKind, StableId};

pub const MAX_INSERTED_IMAGE_BYTES: usize = 20 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TextReplacement {
    pub target_id: StableId,
    pub text: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImageMediaType {
    Png,
    Jpeg,
    Webp,
}

impl ImageMediaType {
    fn extension(self) -> &'static str {
        match self {
            Self::Png => "png",
            Self::Jpeg => "jpg",
            Self::Webp => "webp",
        }
    }
}

/// A server-resolved image insertion.
///
/// The collaboration model persists `asset_path`, dimensions, and the paragraph
/// anchor. The document export worker resolves that asset to `bytes` before
/// calling `apply_collaboration_patch`; image bytes are never stored in Yjs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InsertedImagePatch {
    pub id: StableId,
    pub anchor_paragraph_id: StableId,
    pub asset_path: String,
    pub bytes: Vec<u8>,
    pub media_type: ImageMediaType,
    pub width: u32,
    pub height: u32,
    pub natural_width_px: u32,
    pub natural_height_px: u32,
    pub description: String,
}

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
    let (document_paragraph_locations, document_cell_ids) =
        collect_document_targets(document, &manifest.source_fingerprint);
    let document_paragraph_ids: HashSet<StableId> =
        document_paragraph_locations.keys().cloned().collect();

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
    validate_inserted_images(
        document,
        &patch.inserted_images,
        &manifest_paragraph_ids,
        &document_paragraph_locations,
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
    let image_locations: Vec<(usize, usize)> = patch
        .inserted_images
        .iter()
        .map(|image| {
            document_paragraph_locations
                .get(&image.anchor_paragraph_id)
                .copied()
                .expect("validated image anchor must exist")
        })
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

    for (image, location) in patch.inserted_images.iter().zip(image_locations) {
        insert_resolved_image(document, image, location);
        report.inserted_images += 1;
    }

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

fn validate_inserted_images(
    document: &Document,
    images: &[InsertedImagePatch],
    manifest_paragraphs: &HashSet<StableId>,
    document_paragraphs: &HashMap<StableId, (usize, usize)>,
    readonly_targets: &HashSet<StableId>,
) -> Result<(), CollaborationError> {
    if images.is_empty() {
        return Ok(());
    }

    let final_position_count = document
        .bin_data_content
        .len()
        .checked_add(images.len())
        .filter(|count| *count <= usize::from(u16::MAX));
    let max_storage_id = document
        .bin_data_content
        .iter()
        .map(|content| content.id)
        .chain(
            document
                .doc_info
                .bin_data_list
                .iter()
                .map(|bin_data| bin_data.storage_id),
        )
        .max()
        .unwrap_or(0);
    let final_storage_id = usize::from(max_storage_id).checked_add(images.len());

    if final_position_count.is_none()
        || final_storage_id.is_none_or(|storage_id| storage_id > usize::from(u16::MAX))
    {
        return Err(invalid_image(
            &images[0],
            "document embedded-image capacity exceeded",
        ));
    }

    let mut image_ids = HashSet::with_capacity(images.len());
    for image in images {
        if !image_ids.insert(image.id.clone()) {
            return Err(invalid_image(image, "duplicate image id in patch"));
        }
        if readonly_targets.contains(&image.anchor_paragraph_id) {
            return Err(CollaborationError::ReadonlyTarget(
                image.anchor_paragraph_id.clone(),
            ));
        }
        if !manifest_paragraphs.contains(&image.anchor_paragraph_id)
            || !document_paragraphs.contains_key(&image.anchor_paragraph_id)
        {
            return Err(CollaborationError::UnknownTarget(
                image.anchor_paragraph_id.clone(),
            ));
        }
        if image.asset_path.trim().is_empty() {
            return Err(invalid_image(image, "asset path must not be empty"));
        }
        if image.bytes.is_empty() {
            return Err(invalid_image(
                image,
                "resolved image bytes must not be empty",
            ));
        }
        if image.bytes.len() > MAX_INSERTED_IMAGE_BYTES {
            return Err(invalid_image(
                image,
                "resolved image exceeds the 20 MiB limit",
            ));
        }
        if image.width == 0 || image.height == 0 {
            return Err(invalid_image(image, "display dimensions must be positive"));
        }
        if image.natural_width_px == 0 || image.natural_height_px == 0 {
            return Err(invalid_image(
                image,
                "natural pixel dimensions must be positive",
            ));
        }
    }

    Ok(())
}

fn invalid_image(image: &InsertedImagePatch, reason: &str) -> CollaborationError {
    CollaborationError::InvalidImage {
        image_id: image.id.clone(),
        reason: reason.to_string(),
    }
}

fn collect_document_targets(
    document: &Document,
    source_fingerprint: &str,
) -> (HashMap<StableId, (usize, usize)>, HashSet<StableId>) {
    let mut paragraph_locations = HashMap::new();
    let mut cell_ids = HashSet::new();

    for (section_index, section) in document.sections.iter().enumerate() {
        for (paragraph_index, paragraph) in section.paragraphs.iter().enumerate() {
            let paragraph_path = [section_index as u32, paragraph_index as u32];
            paragraph_locations.insert(
                StableId::for_node(source_fingerprint, NodeKind::Paragraph, &paragraph_path),
                (section_index, paragraph_index),
            );

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

    (paragraph_locations, cell_ids)
}

fn insert_resolved_image(
    document: &mut Document,
    image: &InsertedImagePatch,
    (section_index, paragraph_index): (usize, usize),
) {
    let position_id = u16::try_from(document.bin_data_content.len() + 1)
        .expect("validated image position must fit in u16");
    let storage_id = document.next_bin_data_storage_id();
    let extension = image.media_type.extension();

    document.bin_data_content.push(BinDataContent {
        id: storage_id,
        data: image.bytes.clone().into(),
        extension: extension.to_string(),
    });
    document.doc_info.bin_data_list.push(BinData {
        raw_data: None,
        attr: 0x0101,
        data_type: BinDataType::Embedding,
        compression: BinDataCompression::Default,
        status: BinDataStatus::Success,
        abs_path: None,
        rel_path: None,
        storage_id,
        extension: Some(extension.to_string()),
    });
    document.doc_info.raw_stream = None;

    let width_i32 = i32::try_from(image.width).unwrap_or(i32::MAX);
    let height_i32 = i32::try_from(image.height).unwrap_or(i32::MAX);
    let crop_right = pixel_extent_to_hwpunit(image.natural_width_px);
    let crop_bottom = pixel_extent_to_hwpunit(image.natural_height_px);
    let common_attr: u32 = (2 << 3) | (3 << 8) | (4 << 15) | (2 << 18);
    let picture = Picture {
        common: CommonObjAttr {
            ctrl_id: 0x6773_6f20,
            attr: common_attr,
            treat_as_char: false,
            vert_rel_to: VertRelTo::Para,
            horz_rel_to: HorzRelTo::Para,
            text_wrap: TextWrap::Square,
            width: image.width,
            height: image.height,
            z_order: 1,
            description: image.description.clone(),
            ..CommonObjAttr::default()
        },
        shape_attr: ShapeComponentAttr {
            original_width: image.width,
            original_height: image.height,
            current_width: image.width,
            current_height: image.height,
            local_file_version: 1,
            render_sx: 1.0,
            render_sy: 1.0,
            ..ShapeComponentAttr::default()
        },
        border_x: [0, 0, width_i32, 0],
        border_y: [width_i32, height_i32, 0, height_i32],
        crop: CropInfo {
            left: 0,
            top: 0,
            right: crop_right,
            bottom: crop_bottom,
        },
        image_attr: ImageAttr {
            brightness: 0,
            contrast: 0,
            effect: ImageEffect::RealPic,
            bin_data_id: position_id,
            transparency: 0,
            external_path: None,
        },
        ..Picture::default()
    };

    let section = &mut document.sections[section_index];
    section.raw_stream = None;
    let paragraph = &mut section.paragraphs[paragraph_index];
    paragraph.controls.push(Control::Picture(Box::new(picture)));
    paragraph.ctrl_data_records.push(None);
    paragraph.control_mask |= 0x0000_0800;
}

fn pixel_extent_to_hwpunit(pixels: u32) -> i32 {
    i32::try_from(u64::from(pixels) * 75).unwrap_or(i32::MAX)
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
