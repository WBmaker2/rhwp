use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process;

use rhwp::collaboration::{
    apply_collaboration_patch, build_collaboration_manifest, CollaborationManifest,
    CollaborationPatch, StableId, TextReplacement,
};
use rhwp::parser::parse_document;
use rhwp::serializer::hwpx::serialize_hwpx;
use serde::Deserialize;

const EXIT_RUNTIME: i32 = 1;
const EXIT_USAGE: i32 = 2;

#[derive(Debug, Deserialize)]
struct TextReplacementDto {
    target_id: StableId,
    text: String,
}

#[derive(Debug, Default, Deserialize)]
struct CollaborationPatchDto {
    #[serde(default)]
    paragraphs: Vec<TextReplacementDto>,
    #[serde(default)]
    cells: Vec<TextReplacementDto>,
}

impl From<CollaborationPatchDto> for CollaborationPatch {
    fn from(value: CollaborationPatchDto) -> Self {
        Self {
            paragraphs: value
                .paragraphs
                .into_iter()
                .map(|replacement| TextReplacement {
                    target_id: replacement.target_id,
                    text: replacement.text,
                })
                .collect(),
            cells: value
                .cells
                .into_iter()
                .map(|replacement| TextReplacement {
                    target_id: replacement.target_id,
                    text: replacement.text,
                })
                .collect(),
            inserted_images: Vec::new(),
        }
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let result = match args.get(1).map(String::as_str) {
        Some("import") => import_document(&args[2..]),
        Some("export") => export_document(&args[2..]),
        Some("--help") | Some("-h") => {
            print_help();
            Ok(())
        }
        _ => {
            print_help();
            process::exit(EXIT_USAGE);
        }
    };

    if let Err(error) = result {
        eprintln!("{error}");
        process::exit(EXIT_RUNTIME);
    }
}

fn import_document(args: &[String]) -> Result<(), String> {
    let parsed = parse_args(args, &["--manifest"])?;
    let source = parsed.input;
    let manifest_path = required_path(&parsed, "--manifest")?;
    let source_bytes = read_file(&source, "source document")?;
    let fingerprint = source_fingerprint(&source_bytes);
    let document =
        parse_document(&source_bytes).map_err(|error| format!("parse failed: {error}"))?;
    let manifest = build_collaboration_manifest(&document, &fingerprint)
        .map_err(|error| format!("manifest build failed: {error}"))?;
    let manifest_json = serde_json::to_vec_pretty(&manifest)
        .map_err(|error| format!("manifest serialization failed: {error}"))?;
    atomic_write(&manifest_path, &manifest_json)?;

    println!(
        "{}",
        serde_json::json!({
            "status": "ready",
            "sourceFingerprint": fingerprint,
            "manifestPath": manifest_path,
            "paragraphCount": manifest
                .sections
                .iter()
                .map(|section| section.paragraphs.len())
                .sum::<usize>(),
            "cellCount": manifest
                .sections
                .iter()
                .flat_map(|section| section.tables.iter())
                .map(|table| table.cells.len())
                .sum::<usize>(),
        })
    );
    Ok(())
}

fn export_document(args: &[String]) -> Result<(), String> {
    let parsed = parse_args(args, &["--manifest", "--patch", "--output"])?;
    let source = parsed.input;
    let manifest_path = required_path(&parsed, "--manifest")?;
    let patch_path = required_path(&parsed, "--patch")?;
    let output_path = required_path(&parsed, "--output")?;

    let source_bytes = read_file(&source, "source document")?;
    let computed_fingerprint = source_fingerprint(&source_bytes);
    let manifest: CollaborationManifest =
        serde_json::from_slice(&read_file(&manifest_path, "manifest")?)
            .map_err(|error| format!("invalid manifest: {error}"))?;
    if manifest.source_fingerprint != computed_fingerprint {
        return Err(format!(
            "source fingerprint mismatch: manifest={} source={computed_fingerprint}",
            manifest.source_fingerprint
        ));
    }
    let patch_dto: CollaborationPatchDto =
        serde_json::from_slice(&read_file(&patch_path, "patch")?)
            .map_err(|error| format!("invalid patch: {error}"))?;
    let patch: CollaborationPatch = patch_dto.into();
    let mut document =
        parse_document(&source_bytes).map_err(|error| format!("parse failed: {error}"))?;
    let report = apply_collaboration_patch(&mut document, &manifest, &patch)
        .map_err(|error| format!("patch failed: {error}"))?;
    let exported =
        serialize_hwpx(&document).map_err(|error| format!("HWPX export failed: {error}"))?;
    parse_document(&exported).map_err(|error| format!("export verification failed: {error}"))?;
    atomic_write(&output_path, &exported)?;

    println!(
        "{}",
        serde_json::json!({
            "status": "ready",
            "outputPath": output_path,
            "outputBytes": exported.len(),
            "updatedParagraphs": report.updated_paragraphs,
            "updatedCells": report.updated_cells,
            "insertedImages": report.inserted_images,
        })
    );
    Ok(())
}

struct ParsedArgs {
    input: PathBuf,
    options: std::collections::HashMap<String, PathBuf>,
}

fn parse_args(args: &[String], allowed_options: &[&str]) -> Result<ParsedArgs, String> {
    let Some(input) = args.first() else {
        return Err("source document path is required".to_string());
    };
    if input.starts_with('-') {
        return Err("source document path must be the first argument".to_string());
    }
    let mut options = std::collections::HashMap::new();
    let mut index = 1;
    while index < args.len() {
        let option = args[index].as_str();
        if !allowed_options.contains(&option) {
            return Err(format!("unknown option: {option}"));
        }
        let Some(value) = args.get(index + 1) else {
            return Err(format!("missing value for {option}"));
        };
        options.insert(option.to_string(), PathBuf::from(value));
        index += 2;
    }
    Ok(ParsedArgs {
        input: PathBuf::from(input),
        options,
    })
}

fn required_path(parsed: &ParsedArgs, name: &str) -> Result<PathBuf, String> {
    parsed
        .options
        .get(name)
        .cloned()
        .ok_or_else(|| format!("{name} is required"))
}

fn source_fingerprint(bytes: &[u8]) -> String {
    format!("blake3:{}", blake3::hash(bytes).to_hex())
}

fn read_file(path: &Path, label: &str) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| format!("failed to read {label} {}: {error}", path.display()))
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)
        .map_err(|error| format!("failed to create {}: {error}", parent.display()))?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| format!("invalid output path: {}", path.display()))?;
    let temporary = parent.join(format!(".{file_name}.{}.tmp", process::id()));
    fs::write(&temporary, bytes)
        .map_err(|error| format!("failed to write {}: {error}", temporary.display()))?;
    fs::rename(&temporary, path).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        format!("failed to publish {}: {error}", path.display())
    })
}

fn print_help() {
    eprintln!(
        "rhwp-collaboration-worker import <source.hwp|source.hwpx> --manifest <manifest.json>"
    );
    eprintln!(
        "rhwp-collaboration-worker export <source.hwp|source.hwpx> --manifest <manifest.json> --patch <patch.json> --output <output.hwpx>"
    );
}
