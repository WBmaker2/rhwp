use serde::Deserialize;
use wasm_bindgen::prelude::*;

use crate::collaboration::{
    apply_collaboration_patch, build_collaboration_manifest, CollaborationManifest,
    CollaborationPatch, ImageMediaType, InsertedImagePatch, StableId, TextReplacement,
};
use crate::wasm_api::HwpDocument;

#[derive(Deserialize)]
struct TextReplacementDto {
    target_id: StableId,
    text: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum ImageMediaTypeDto {
    Png,
    Jpeg,
    Webp,
}

#[derive(Deserialize)]
struct InsertedImagePatchDto {
    id: StableId,
    anchor_paragraph_id: StableId,
    asset_path: String,
    bytes: Vec<u8>,
    media_type: ImageMediaTypeDto,
    width: u32,
    height: u32,
    natural_width_px: u32,
    natural_height_px: u32,
    description: String,
}

#[derive(Default, Deserialize)]
struct CollaborationPatchDto {
    #[serde(default)]
    paragraphs: Vec<TextReplacementDto>,
    #[serde(default)]
    cells: Vec<TextReplacementDto>,
    #[serde(default)]
    inserted_images: Vec<InsertedImagePatchDto>,
}

impl From<TextReplacementDto> for TextReplacement {
    fn from(value: TextReplacementDto) -> Self {
        Self {
            target_id: value.target_id,
            text: value.text,
        }
    }
}

impl From<ImageMediaTypeDto> for ImageMediaType {
    fn from(value: ImageMediaTypeDto) -> Self {
        match value {
            ImageMediaTypeDto::Png => Self::Png,
            ImageMediaTypeDto::Jpeg => Self::Jpeg,
            ImageMediaTypeDto::Webp => Self::Webp,
        }
    }
}

impl From<InsertedImagePatchDto> for InsertedImagePatch {
    fn from(value: InsertedImagePatchDto) -> Self {
        Self {
            id: value.id,
            anchor_paragraph_id: value.anchor_paragraph_id,
            asset_path: value.asset_path,
            bytes: value.bytes,
            media_type: value.media_type.into(),
            width: value.width,
            height: value.height,
            natural_width_px: value.natural_width_px,
            natural_height_px: value.natural_height_px,
            description: value.description,
        }
    }
}

impl From<CollaborationPatchDto> for CollaborationPatch {
    fn from(value: CollaborationPatchDto) -> Self {
        Self {
            paragraphs: value.paragraphs.into_iter().map(Into::into).collect(),
            cells: value.cells.into_iter().map(Into::into).collect(),
            inserted_images: value.inserted_images.into_iter().map(Into::into).collect(),
        }
    }
}

#[wasm_bindgen]
impl HwpDocument {
    /// Convert the current Document IR to a stable-ID collaboration manifest.
    #[wasm_bindgen(js_name = getCollaborationManifest)]
    pub fn get_collaboration_manifest_json(
        &self,
        source_fingerprint: &str,
    ) -> Result<String, JsValue> {
        let manifest = build_collaboration_manifest(self.document(), source_fingerprint)
            .map_err(|error| JsValue::from_str(&error.to_string()))?;
        serde_json::to_string(&manifest)
            .map_err(|error| JsValue::from_str(&format!("manifest serialization failed: {error}")))
    }

    /// Apply a Yjs-derived collaboration patch and rebuild layout state.
    #[wasm_bindgen(js_name = applyCollaborationPatch)]
    pub fn apply_collaboration_patch_json(
        &mut self,
        manifest_json: &str,
        patch_json: &str,
    ) -> Result<String, JsValue> {
        let manifest: CollaborationManifest =
            serde_json::from_str(manifest_json).map_err(|error| {
                JsValue::from_str(&format!("invalid collaboration manifest: {error}"))
            })?;
        let patch: CollaborationPatchDto = serde_json::from_str(patch_json)
            .map_err(|error| JsValue::from_str(&format!("invalid collaboration patch: {error}")))?;
        let mut document = self.document().clone();
        let report = apply_collaboration_patch(&mut document, &manifest, &patch.into())
            .map_err(|error| JsValue::from_str(&error.to_string()))?;
        self.set_document(document);

        Ok(serde_json::json!({
            "updatedParagraphs": report.updated_paragraphs,
            "updatedCells": report.updated_cells,
            "insertedImages": report.inserted_images,
        })
        .to_string())
    }
}
