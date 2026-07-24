use rhwp::collaboration::{build_collaboration_manifest, NodeKind, StableId};
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
    let body = Paragraph {
        text: "공동 편집 본문".to_string(),
        style_id: 3,
        ..Paragraph::default()
    };

    let cell = Cell {
        row: 0,
        col: 0,
        col_span: 1,
        row_span: 1,
        paragraphs: vec![Paragraph {
            text: "공동 편집 셀".to_string(),
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

    let document = Document {
        sections: vec![Section {
            paragraphs: vec![body, host],
            ..Section::default()
        }],
        ..Document::default()
    };

    let manifest = build_collaboration_manifest(&document, "sha256:fixture").unwrap();

    assert_eq!(manifest.sections.len(), 1);
    assert_eq!(manifest.sections[0].paragraphs[0].text, "공동 편집 본문");
    assert_eq!(manifest.sections[0].paragraphs[0].style_ref, Some(3));

    let imported_table = &manifest.sections[0].tables[0];
    assert!(imported_table.structure_readonly);
    assert_eq!(imported_table.rows.len(), 1);
    assert_eq!(imported_table.cells.len(), 1);
    assert_eq!(imported_table.cells[0].text, "공동 편집 셀");
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
