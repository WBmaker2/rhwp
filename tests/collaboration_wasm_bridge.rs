use rhwp::collaboration::CollaborationManifest;
use rhwp::model::document::{Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::serializer::hwpx::serialize_hwpx;
use rhwp::wasm_api::HwpDocument;

#[test]
fn wasm_bridge_builds_manifest_and_applies_json_text_patch() {
    let source = Document {
        sections: vec![Section {
            paragraphs: vec![Paragraph {
                text: "원본 문단".to_string(),
                ..Paragraph::default()
            }],
            ..Section::default()
        }],
        ..Document::default()
    };
    let bytes = serialize_hwpx(&source).expect("serialize source fixture");
    let mut document = HwpDocument::from_bytes(&bytes).expect("load source fixture");

    let manifest_json = document
        .get_collaboration_manifest_json("blake3:fixture")
        .expect("build collaboration manifest");
    let manifest: CollaborationManifest =
        serde_json::from_str(&manifest_json).expect("parse collaboration manifest");
    let paragraph_id = manifest.sections[0].paragraphs[0].id.clone();
    let patch_json = serde_json::json!({
        "paragraphs": [{
            "target_id": paragraph_id,
            "text": "원격 공동 편집 문단"
        }],
        "cells": [],
        "inserted_images": []
    })
    .to_string();

    let report_json = document
        .apply_collaboration_patch_json(&manifest_json, &patch_json)
        .expect("apply collaboration patch");
    let report: serde_json::Value =
        serde_json::from_str(&report_json).expect("parse apply report");

    assert_eq!(report["updatedParagraphs"], 1);
    let updated_manifest: CollaborationManifest = serde_json::from_str(
        &document
            .get_collaboration_manifest_json("blake3:fixture")
            .expect("rebuild collaboration manifest"),
    )
    .expect("parse updated collaboration manifest");
    assert_eq!(
        updated_manifest.sections[0].paragraphs[0].text,
        "원격 공동 편집 문단"
    );
}
