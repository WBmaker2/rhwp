use rhwp::collaboration::{
    apply_collaboration_patch, build_collaboration_manifest, CollaborationPatch, NodeKind,
    StableId, TextReplacement,
};
use rhwp::model::control::{Control, Equation};
use rhwp::model::document::{DocInfo, Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::style::{BorderFill, CharShape, Font, ParaShape, Style, TabDef};
use rhwp::model::table::{Cell, Table};
use rhwp::parser::parse_document;
use rhwp::serializer::hwpx::serialize_hwpx;

#[test]
fn nested_cell_equation_is_readonly_and_survives_hwpx_roundtrip() {
    let mut document = document_with_nested_cell_equation();
    let manifest = build_collaboration_manifest(&document, "sha256:nested-fixture").unwrap();
    let nested_equation_id = StableId::for_node(
        "sha256:nested-fixture",
        NodeKind::ReadonlyObject,
        &[0, 0, 0, 0, 0, 0],
    );

    let nested_equation = manifest
        .readonly_objects
        .iter()
        .find(|object| object.id == nested_equation_id)
        .expect("nested cell equation must be classified as read-only");
    assert_eq!(nested_equation.kind, "equation");

    let cell_id = manifest.sections[0].tables[0].cells[0].id.clone();
    apply_collaboration_patch(
        &mut document,
        &manifest,
        &CollaborationPatch {
            paragraphs: Vec::new(),
            cells: vec![TextReplacement {
                target_id: cell_id,
                text: "편집된 셀".to_string(),
            }],
            inserted_images: Vec::new(),
        },
    )
    .unwrap();

    let hwpx = serialize_hwpx(&document).expect("serialize document with nested equation");
    let reparsed = parse_document(&hwpx).expect("parse document with nested equation");
    let table = reparsed.sections[0].paragraphs[0]
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Table(table) => Some(table.as_ref()),
            _ => None,
        })
        .expect("round-tripped table");
    let cell_paragraph = &table.cells[0].paragraphs[0];

    assert_eq!(cell_paragraph.text, "편집된 셀");
    let equation = cell_paragraph
        .controls
        .iter()
        .find_map(|control| match control {
            Control::Equation(equation) => Some(equation.as_ref()),
            _ => None,
        })
        .expect("round-tripped nested equation");
    assert_eq!(equation.script, "x over y");
}

fn document_with_nested_cell_equation() -> Document {
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

    Document {
        doc_info: serializable_doc_info(),
        sections: vec![Section {
            paragraphs: vec![Paragraph {
                controls: vec![Control::Table(Box::new(table))],
                ..Paragraph::default()
            }],
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
