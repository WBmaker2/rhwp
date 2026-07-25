use rhwp::collaboration::{
    apply_collaboration_cell_text, apply_collaboration_paragraph_text,
    build_collaboration_manifest, CollaborationError,
};
use rhwp::model::control::Control;
use rhwp::model::document::{Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::table::{Cell, Table};

fn fixture() -> Document {
    let table = Table {
        row_count: 1,
        col_count: 1,
        cells: vec![Cell {
            row: 0,
            col: 0,
            paragraphs: vec![Paragraph {
                text: "before cell".into(),
                ..Default::default()
            }],
            ..Default::default()
        }],
        ..Default::default()
    };
    Document {
        sections: vec![Section {
            paragraphs: vec![
                Paragraph {
                    text: "before paragraph".into(),
                    ..Default::default()
                },
                Paragraph {
                    controls: vec![Control::Table(Box::new(table))],
                    ..Default::default()
                },
            ],
            ..Default::default()
        }],
        ..Default::default()
    }
}

#[test]
fn paragraph_apply_validates_id_and_updates_text() {
    let mut doc = fixture();
    let manifest = build_collaboration_manifest(&doc, "sha256:apply").unwrap();
    let node = &manifest.sections[0].paragraphs[0];
    apply_collaboration_paragraph_text(
        &mut doc,
        "sha256:apply",
        0,
        0,
        &node.id.0,
        "after paragraph",
    )
    .unwrap();
    assert_eq!(doc.sections[0].paragraphs[0].text, "after paragraph");
    assert!(matches!(
        apply_collaboration_paragraph_text(&mut doc, "sha256:apply", 0, 0, "bad", "x"),
        Err(CollaborationError::StableIdMismatch { .. })
    ));
}

#[test]
fn cell_apply_validates_id_and_updates_single_paragraph_cell() {
    let mut doc = fixture();
    let manifest = build_collaboration_manifest(&doc, "sha256:apply").unwrap();
    let cell = &manifest.sections[0].tables[0].cells[0];
    apply_collaboration_cell_text(
        &mut doc,
        "sha256:apply",
        0,
        1,
        0,
        0,
        &cell.id.0,
        "after cell",
    )
    .unwrap();
    let Control::Table(table) = &doc.sections[0].paragraphs[1].controls[0] else {
        panic!()
    };
    assert_eq!(table.cells[0].paragraphs[0].text, "after cell");
    assert!(table.dirty);
}

#[test]
fn cell_apply_rejects_multi_paragraph_cells() {
    let mut doc = fixture();
    let Control::Table(table) = &mut doc.sections[0].paragraphs[1].controls[0] else {
        panic!()
    };
    table.cells[0].paragraphs.push(Paragraph::default());
    let manifest = build_collaboration_manifest(&doc, "sha256:apply").unwrap();
    let cell = &manifest.sections[0].tables[0].cells[0];
    assert!(matches!(
        apply_collaboration_cell_text(&mut doc, "sha256:apply", 0, 1, 0, 0, &cell.id.0, "x"),
        Err(CollaborationError::UnsupportedCellParagraphStructure { .. })
    ));
}
