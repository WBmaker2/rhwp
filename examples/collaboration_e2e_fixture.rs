use std::env;
use std::fs;
use std::path::Path;
use std::process;

use rhwp::model::document::{DocInfo, Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::style::{BorderFill, CharShape, Font, ParaShape, Style, TabDef};
use rhwp::serializer::hwpx::serialize_hwpx;

fn main() {
    let Some(output) = env::args().nth(1) else {
        eprintln!("usage: collaboration_e2e_fixture <output.hwpx>");
        process::exit(2);
    };
    let bytes = serialize_hwpx(&source_document()).expect("serialize E2E HWPX fixture");
    let path = Path::new(&output);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create fixture output directory");
    }
    fs::write(path, bytes).expect("write E2E HWPX fixture");
}

fn source_document() -> Document {
    Document {
        doc_info: serializable_doc_info(),
        sections: vec![Section {
            paragraphs: vec![Paragraph {
                text: "Emulator 공동 편집 원본".to_string(),
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
            local_name: "Emulator 스타일".to_string(),
            english_name: "Emulator Style".to_string(),
            lang_id: 1_042,
            para_shape_id: 0,
            char_shape_id: 0,
            ..Style::default()
        }],
        ..DocInfo::default()
    }
}
