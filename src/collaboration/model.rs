use serde::{Deserialize, Serialize};

use super::StableId;

pub const COLLABORATION_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CollaborationManifest {
    pub schema_version: u32,
    pub source_fingerprint: String,
    pub sections: Vec<SectionManifest>,
    pub readonly_objects: Vec<ReadonlyObjectManifest>,
}

impl CollaborationManifest {
    pub fn empty(source_fingerprint: impl Into<String>) -> Self {
        Self {
            schema_version: COLLABORATION_SCHEMA_VERSION,
            source_fingerprint: source_fingerprint.into(),
            sections: Vec::new(),
            readonly_objects: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SectionManifest {
    pub id: StableId,
    pub paragraphs: Vec<ParagraphManifest>,
    pub tables: Vec<TableManifest>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ParagraphManifest {
    pub id: StableId,
    pub text: String,
    pub style_ref: Option<u32>,
    pub location: ParagraphLocation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ParagraphLocation {
    pub section_index: u32,
    pub paragraph_index: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct TableManifest {
    pub id: StableId,
    pub rows: Vec<RowManifest>,
    pub cells: Vec<CellManifest>,
    pub structure_readonly: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RowManifest {
    pub id: StableId,
    pub cell_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CellManifest {
    pub id: StableId,
    pub text: String,
    pub style_ref: Option<u32>,
    pub structure_readonly: bool,
    pub location: CellLocation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CellLocation {
    pub section_index: u32,
    pub host_paragraph_index: u32,
    pub control_index: u32,
    pub cell_index: u32,
    pub row_index: u32,
    pub column_index: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReadonlyObjectManifest {
    pub id: StableId,
    pub kind: String,
}
