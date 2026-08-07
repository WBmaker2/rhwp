use rhwp::collaboration::{
    build_collaboration_manifest, get_collaboration_cell_text, get_collaboration_paragraph_text,
};
use rhwp::model::control::Control;
use rhwp::model::document::{Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::table::{Cell, Table};

const FP: &str = "sha256:task5fixture";

fn paragraph(text: &str) -> Paragraph {
    Paragraph {
        text: text.to_string(),
        ..Default::default()
    }
}

#[test]
fn reads_paragraph_text_after_stable_id_validation() {
    let document = Document {
        sections: vec![Section {
            paragraphs: vec![paragraph("hello")],
            ..Default::default()
        }],
        ..Default::default()
    };
    let manifest = build_collaboration_manifest(&document, FP).unwrap();
    let node = &manifest.sections[0].paragraphs[0];
    assert_eq!(
        get_collaboration_paragraph_text(&document, FP, 0, 0, node.id.0.as_str()).unwrap(),
        "hello"
    );
}

#[test]
fn reads_single_paragraph_cell_text() {
    let mut host = paragraph("");
    let table = Table {
        row_count: 1,
        col_count: 1,
        cells: vec![Cell {
            paragraphs: vec![paragraph("cell")],
            ..Default::default()
        }],
        ..Default::default()
    };
    host.controls.push(Control::Table(Box::new(table)));
    let document = Document {
        sections: vec![Section {
            paragraphs: vec![host],
            ..Default::default()
        }],
        ..Default::default()
    };
    let manifest = build_collaboration_manifest(&document, FP).unwrap();
    let node = &manifest.sections[0].tables[0].cells[0];
    assert_eq!(
        get_collaboration_cell_text(&document, FP, 0, 0, 0, 0, node.id.0.as_str()).unwrap(),
        "cell"
    );
}

#[test]
fn rejects_multi_paragraph_cell_reads() {
    let mut host = paragraph("");
    let table = Table {
        row_count: 1,
        col_count: 1,
        cells: vec![Cell {
            paragraphs: vec![paragraph("a"), paragraph("b")],
            ..Default::default()
        }],
        ..Default::default()
    };
    host.controls.push(Control::Table(Box::new(table)));
    let document = Document {
        sections: vec![Section {
            paragraphs: vec![host],
            ..Default::default()
        }],
        ..Default::default()
    };
    let manifest = build_collaboration_manifest(&document, FP).unwrap();
    let node = &manifest.sections[0].tables[0].cells[0];
    assert!(get_collaboration_cell_text(&document, FP, 0, 0, 0, 0, node.id.0.as_str()).is_err());
}
