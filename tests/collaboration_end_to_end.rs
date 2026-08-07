use rhwp::collaboration::{
    apply_collaboration_patch, build_collaboration_manifest, CollaborationPatch, ImageMediaType,
    InsertedImagePatch, NodeKind, StableId, TextReplacement,
};
use rhwp::model::control::{Control, Equation};
use rhwp::model::document::{DocInfo, Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::style::{BorderFill, CharShape, Font, ParaShape, Style, TabDef};
use rhwp::model::table::{Cell, Table};
use rhwp::parser::parse_document;
use rhwp::serializer::hwpx::serialize_hwpx;

#[test]
fn imported_document_edits_recover_and_export_to_reparseable_hwpx() {
    let source_hwpx = serialize_hwpx(&source_document()).expect("serialize import source");
    let mut recovered_document = parse_document(&source_hwpx).expect("parse import source");
    let fingerprint = "sha256:end-to-end-fixture";
    let manifest = build_collaboration_manifest(&recovered_document, fingerprint)
        .expect("build collaboration manifest");

    let paragraph_id = manifest.sections[0].paragraphs[0].id.clone();
    let cell_id = manifest.sections[0].tables[0].cells[0].id.clone();
    let nested_equation_id =
        StableId::for_node(fingerprint, NodeKind::ReadonlyObject, &[0, 1, 0, 0, 0, 0]);
    assert!(manifest
        .readonly_objects
        .iter()
        .any(|object| object.id == nested_equation_id && object.kind == "equation"));

    let image_bytes = test_png();
    let patch = CollaborationPatch {
        paragraphs: vec![TextReplacement {
            target_id: paragraph_id.clone(),
            text: "복구된 공동 편집 본문".to_string(),
        }],
        cells: vec![TextReplacement {
            target_id: cell_id,
            text: "복구된 공동 편집 셀".to_string(),
        }],
        inserted_images: vec![InsertedImagePatch {
            id: StableId::for_node(fingerprint, NodeKind::Image, &[0, 0, 0]),
            anchor_paragraph_id: paragraph_id,
            asset_path: "documents/doc-1/assets/user/image-1/pixel.png".to_string(),
            bytes: image_bytes.clone(),
            media_type: ImageMediaType::Png,
            width: 2_400,
            height: 1_200,
            natural_width_px: 1,
            natural_height_px: 1,
            description: "복구된 공동 편집 이미지".to_string(),
        }],
    };

    let report = apply_collaboration_patch(&mut recovered_document, &manifest, &patch)
        .expect("apply recovered collaboration state");
    assert_eq!(report.updated_paragraphs, 1);
    assert_eq!(report.updated_cells, 1);
    assert_eq!(report.inserted_images, 1);

    let exported_hwpx = serialize_hwpx(&recovered_document).expect("export collaboration HWPX");
    let reparsed = parse_document(&exported_hwpx).expect("reparse exported collaboration HWPX");

    assert_eq!(
        reparsed.sections[0].paragraphs[0].text,
        "복구된 공동 편집 본문"
    );

    let table = reparsed.sections[0].paragraphs[1]
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Table(table) => Some(table.as_ref()),
            _ => None,
        })
        .expect("exported table");
    let cell_paragraph = &table.cells[0].paragraphs[0];
    assert_eq!(cell_paragraph.text, "복구된 공동 편집 셀");
    let equation = cell_paragraph
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Equation(equation) => Some(equation.as_ref()),
            _ => None,
        })
        .expect("readonly nested equation after export");
    assert_eq!(equation.script, "x over y");

    let picture = reparsed.sections[0].paragraphs[0]
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Picture(picture) => Some(picture.as_ref()),
            _ => None,
        })
        .expect("inserted collaboration picture after export");
    assert_eq!(picture.common.width, 2_400);
    assert_eq!(picture.common.height, 1_200);
    assert_eq!(picture.common.description, "복구된 공동 편집 이미지");
    assert!(reparsed.bin_data_content.iter().any(|content| {
        content.extension.eq_ignore_ascii_case("png") && content.data.load() == image_bytes
    }));
}

fn source_document() -> Document {
    let body = Paragraph {
        text: "원본 본문".to_string(),
        ..Paragraph::default()
    };
    let cell_paragraph = Paragraph {
        text: "원본 셀".to_string(),
        controls: vec![Control::Equation(Box::new(Equation {
            script: "x over y".to_string(),
            ..Equation::default()
        }))],
        ..Paragraph::default()
    };
    let cell = Cell {
        row: 0,
        col: 0,
        col_span: 1,
        row_span: 1,
        border_fill_id: 1,
        paragraphs: vec![cell_paragraph],
        ..Cell::default()
    };
    let table = Table {
        row_count: 1,
        col_count: 1,
        row_sizes: vec![1],
        cells: vec![cell],
        border_fill_id: 1,
        ..Table::default()
    };
    let table_host = Paragraph {
        controls: vec![Control::Table(Box::new(table))],
        ..Paragraph::default()
    };

    Document {
        doc_info: serializable_doc_info(),
        sections: vec![Section {
            paragraphs: vec![body, table_host],
            ..Section::default()
        }],
        ..Document::default()
    }
}

fn serializable_doc_info() -> DocInfo {
    let font = Font {
        name: "함초롬바탕".to_string(),
        ..Font::default()
    };
    let char_shape = CharShape {
        ratios: [100; 7],
        relative_sizes: [100; 7],
        base_size: 1_000,
        ..CharShape::default()
    };

    DocInfo {
        font_faces: (0..7).map(|_| vec![font.clone()]).collect(),
        border_fills: vec![BorderFill::default()],
        char_shapes: vec![char_shape],
        tab_defs: vec![TabDef::default()],
        para_shapes: vec![ParaShape::default()],
        styles: vec![Style {
            local_name: "테스트 스타일".to_string(),
            english_name: "Test Style".to_string(),
            lang_id: 1_042,
            para_shape_id: 0,
            char_shape_id: 0,
            ..Style::default()
        }],
        ..DocInfo::default()
    }
}

fn test_png() -> Vec<u8> {
    vec![
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
        0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f,
        0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41, 0x54, 0x08, 0xd7, 0x63, 0xf8,
        0xcf, 0xc0, 0xf0, 0x1f, 0x00, 0x05, 0x00, 0x01, 0xff, 0x89, 0x99, 0x3d, 0x1d, 0x00, 0x00,
        0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ]
}
