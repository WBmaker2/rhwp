use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use rhwp::model::document::{DocInfo, Document, Section};
use rhwp::model::paragraph::Paragraph;
use rhwp::model::style::{BorderFill, CharShape, Font, ParaShape, Style, TabDef};
use rhwp::parser::parse_document;
use rhwp::serializer::hwpx::serialize_hwpx;
use serde_json::Value;

#[test]
fn worker_imports_manifest_and_exports_reparseable_hwpx() {
    let directory = temporary_directory();
    fs::create_dir_all(&directory).expect("create temporary directory");
    let source_path = directory.join("source.hwpx");
    let manifest_path = directory.join("manifest.json");
    let patch_path = directory.join("patch.json");
    let output_path = directory.join("export.hwpx");
    fs::write(
        &source_path,
        serialize_hwpx(&source_document()).expect("serialize source"),
    )
    .expect("write source");

    let import = run_worker(&[
        "import",
        source_path.to_str().expect("source path"),
        "--manifest",
        manifest_path.to_str().expect("manifest path"),
    ]);
    assert!(import.status.success(), "{}", String::from_utf8_lossy(&import.stderr));
    let import_report: Value = serde_json::from_slice(&import.stdout).expect("import report");
    assert_eq!(import_report["status"], "ready");
    let manifest: Value = serde_json::from_slice(&fs::read(&manifest_path).expect("manifest"))
        .expect("manifest JSON");
    let paragraph_id = manifest["sections"][0]["paragraphs"][0]["id"]
        .as_str()
        .expect("paragraph ID");
    fs::write(
        &patch_path,
        serde_json::to_vec_pretty(&serde_json::json!({
            "paragraphs": [{
                "target_id": paragraph_id,
                "text": "공동 편집 worker 결과"
            }],
            "cells": []
        }))
        .expect("patch JSON"),
    )
    .expect("write patch");

    let export = run_worker(&[
        "export",
        source_path.to_str().expect("source path"),
        "--manifest",
        manifest_path.to_str().expect("manifest path"),
        "--patch",
        patch_path.to_str().expect("patch path"),
        "--output",
        output_path.to_str().expect("output path"),
    ]);
    assert!(export.status.success(), "{}", String::from_utf8_lossy(&export.stderr));
    let export_report: Value = serde_json::from_slice(&export.stdout).expect("export report");
    assert_eq!(export_report["updatedParagraphs"], 1);
    let exported = parse_document(&fs::read(&output_path).expect("export bytes"))
        .expect("reparse export");
    assert_eq!(exported.sections[0].paragraphs[0].text, "공동 편집 worker 결과");

    fs::remove_dir_all(directory).expect("remove temporary directory");
}

#[test]
fn worker_rejects_manifest_from_a_different_source_generation() {
    let directory = temporary_directory();
    fs::create_dir_all(&directory).expect("create temporary directory");
    let source_path = directory.join("source.hwpx");
    let changed_path = directory.join("changed.hwpx");
    let manifest_path = directory.join("manifest.json");
    let patch_path = directory.join("patch.json");
    let output_path = directory.join("export.hwpx");
    fs::write(
        &source_path,
        serialize_hwpx(&source_document()).expect("serialize source"),
    )
    .expect("write source");
    let mut changed = source_document();
    changed.sections[0].paragraphs[0].text = "다른 원본".to_string();
    fs::write(
        &changed_path,
        serialize_hwpx(&changed).expect("serialize changed source"),
    )
    .expect("write changed source");

    let import = run_worker(&[
        "import",
        source_path.to_str().expect("source path"),
        "--manifest",
        manifest_path.to_str().expect("manifest path"),
    ]);
    assert!(import.status.success());
    fs::write(&patch_path, br#"{"paragraphs":[],"cells":[]}"#).expect("write patch");

    let export = run_worker(&[
        "export",
        changed_path.to_str().expect("changed path"),
        "--manifest",
        manifest_path.to_str().expect("manifest path"),
        "--patch",
        patch_path.to_str().expect("patch path"),
        "--output",
        output_path.to_str().expect("output path"),
    ]);
    assert!(!export.status.success());
    assert!(String::from_utf8_lossy(&export.stderr).contains("source fingerprint mismatch"));
    assert!(!output_path.exists());

    fs::remove_dir_all(directory).expect("remove temporary directory");
}

fn run_worker(arguments: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_rhwp-collaboration-worker"))
        .args(arguments)
        .output()
        .expect("run collaboration worker")
}

fn temporary_directory() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("rhwp-collaboration-worker-{}-{nonce}", std::process::id()))
}

fn source_document() -> Document {
    Document {
        doc_info: serializable_doc_info(),
        sections: vec![Section {
            paragraphs: vec![Paragraph {
                text: "원본 본문".to_string(),
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

#[allow(dead_code)]
fn assert_path_exists(path: &Path) {
    assert!(path.exists(), "{} must exist", path.display());
}
