use rhwp::collaboration::{
    apply_collaboration_patch, build_collaboration_manifest, CollaborationError,
    CollaborationPatch, ImageMediaType, InsertedImagePatch, NodeKind, StableId, TextReplacement,
};
use rhwp::model::control::{Control, Equation};
use rhwp::model::document::{Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::table::{Cell, Table};

#[test]
fn stable_id_is_deterministic_for_same_source_and_path() {
    let first = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);
    let second = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);

    assert_eq!(first, second);
}

#[test]
fn stable_id_changes_when_node_path_changes() {
    let first = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 1]);
    let second = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 2]);

    assert_ne!(first, second);
}

#[test]
fn import_marks_text_editable_and_complex_objects_readonly() {
    let document = sample_document();
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();

    assert_eq!(manifest.sections.len(), 1);
    assert_eq!(manifest.sections[0].paragraphs[0].text, "원본 본문");
    assert_eq!(manifest.sections[0].paragraphs[0].style_ref, Some(3));

    let imported_table = &manifest.sections[0].tables[0];
    assert!(imported_table.structure_readonly);
    assert_eq!(imported_table.rows.len(), 1);
    assert_eq!(imported_table.cells.len(), 1);
    assert_eq!(imported_table.cells[0].text, "원본 셀");
    assert_eq!(imported_table.cells[0].style_ref, Some(4));
    assert!(imported_table.cells[0].structure_readonly);

    assert_eq!(manifest.readonly_objects.len(), 1);
    assert_eq!(manifest.readonly_objects[0].kind, "equation");
}

#[test]
fn import_is_deterministic_for_same_document_and_fingerprint() {
    let document = Document {
        sections: vec![Section {
            paragraphs: vec![Paragraph {
                text: "재현 가능한 문단".to_string(),
                ..Paragraph::default()
            }],
            ..Section::default()
        }],
        ..Document::default()
    };

    let first = build_collaboration_manifest(&document, "sha256:fixture").unwrap();
    let second = build_collaboration_manifest(&document, "sha256:fixture").unwrap();

    assert_eq!(first, second);
}

#[test]
fn apply_updates_supported_paragraph_and_cell_targets() {
    let mut document = sample_document();
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();
    let paragraph_id = manifest.sections[0].paragraphs[0].id.clone();
    let cell_id = manifest.sections[0].tables[0].cells[0].id.clone();
    let patch = CollaborationPatch {
        paragraphs: vec![TextReplacement {
            target_id: paragraph_id,
            text: "공동 편집 본문".to_string(),
        }],
        cells: vec![TextReplacement {
            target_id: cell_id,
            text: "공동 편집 셀".to_string(),
        }],
        inserted_images: Vec::new(),
    };

    let report = apply_collaboration_patch(&mut document, &manifest, &patch).unwrap();

    assert_eq!(report.updated_paragraphs, 1);
    assert_eq!(report.updated_cells, 1);
    assert_eq!(report.inserted_images, 0);
    assert_eq!(document.sections[0].paragraphs[0].text, "공동 편집 본문");

    let Control::Table(table) = &document.sections[0].paragraphs[1].controls[0] else {
        panic!("expected table control");
    };
    assert_eq!(table.cells[0].paragraphs[0].text, "공동 편집 셀");
}

#[test]
fn apply_inserts_resolved_image_at_paragraph_anchor() {
    let mut document = sample_document();
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();
    let anchor_paragraph_id = manifest.sections[0].paragraphs[0].id.clone();
    let image_bytes = test_png();
    let patch = CollaborationPatch {
        paragraphs: Vec::new(),
        cells: Vec::new(),
        inserted_images: vec![InsertedImagePatch {
            id: StableId::for_node("sha256:fixture", NodeKind::Image, &[0, 0, 0]),
            anchor_paragraph_id,
            asset_path: "documents/doc-1/assets/user/image-1/pixel.png".to_string(),
            bytes: image_bytes.clone(),
            media_type: ImageMediaType::Png,
            width: 2_400,
            height: 1_200,
            natural_width_px: 1,
            natural_height_px: 1,
            description: "공동 편집 이미지".to_string(),
        }],
    };

    let report = apply_collaboration_patch(&mut document, &manifest, &patch).unwrap();

    assert_eq!(report.inserted_images, 1);
    let picture = document.sections[0].paragraphs[0]
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Picture(picture) => Some(picture.as_ref()),
            _ => None,
        })
        .expect("expected inserted picture control");
    assert_eq!(picture.common.width, 2_400);
    assert_eq!(picture.common.height, 1_200);
    assert_eq!(picture.common.description, "공동 편집 이미지");
    assert_eq!(picture.image_attr.bin_data_id, 1);

    assert_eq!(document.doc_info.bin_data_list.len(), 1);
    assert_eq!(document.bin_data_content.len(), 1);
    assert_eq!(document.bin_data_content[0].extension, "png");
    assert_eq!(document.bin_data_content[0].data.load(), image_bytes);
}

#[test]
fn apply_rejects_readonly_object_target() {
    let mut document = sample_document();
    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();
    let readonly_id = manifest.readonly_objects[0].id.clone();
    let patch = CollaborationPatch {
        paragraphs: vec![TextReplacement {
            target_id: readonly_id.clone(),
            text: "수정하면 안 됨".to_string(),
        }],
        cells: Vec::new(),
        inserted_images: Vec::new(),
    };

    let error = apply_collaboration_patch(&mut document, &manifest, &patch).unwrap_err();

    assert_eq!(error, CollaborationError::ReadonlyTarget(readonly_id));
}

fn sample_document() -> Document {
    let body = Paragraph {
        text: "원본 본문".to_string(),
        style_id: 3,
        ..Paragraph::default()
    };

    let cell = Cell {
        row: 0,
        col: 0,
        col_span: 1,
        row_span: 1,
        paragraphs: vec![Paragraph {
            text: "원본 셀".to_string(),
            style_id: 4,
            ..Paragraph::default()
        }],
        ..Cell::default()
    };

    let table = Table {
        row_count: 1,
        col_count: 1,
        row_sizes: vec![1],
        cells: vec![cell],
        ..Table::default()
    };

    let host = Paragraph {
        controls: vec![
            Control::Table(Box::new(table)),
            Control::Equation(Box::new(Equation {
                script: "1 over 2".to_string(),
                ..Equation::default()
            })),
        ],
        ..Paragraph::default()
    };

    Document {
        sections: vec![Section {
            paragraphs: vec![body, host],
            ..Section::default()
        }],
        ..Document::default()
    }
}

fn test_png() -> Vec<u8> {
    vec![
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48,
        0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00,
        0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41, 0x54, 0x08,
        0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0xf0, 0x1f, 0x00, 0x05, 0x00, 0x01, 0xff, 0x89, 0x99,
        0x3d, 0x1d, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ]
}
