use serde::{Deserialize, Serialize};

/// A document-node category included in deterministic collaboration IDs.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeKind {
    Section,
    Paragraph,
    Table,
    Row,
    Cell,
    Image,
    ReadonlyObject,
}

impl NodeKind {
    fn stable_tag(self) -> &'static [u8] {
        match self {
            Self::Section => b"section",
            Self::Paragraph => b"paragraph",
            Self::Table => b"table",
            Self::Row => b"row",
            Self::Cell => b"cell",
            Self::Image => b"image",
            Self::ReadonlyObject => b"readonly_object",
        }
    }
}

/// A stable identifier derived from the source document and a node path.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct StableId(pub String);

impl StableId {
    /// Builds a deterministic ID for one node in a parsed source generation.
    pub fn for_node(source_fingerprint: &str, kind: NodeKind, path: &[u32]) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"rhwp-collaboration-id-v1\0");
        hasher.update(source_fingerprint.as_bytes());
        hasher.update(b"\0");
        hasher.update(kind.stable_tag());
        hasher.update(b"\0");

        for part in path {
            hasher.update(&part.to_le_bytes());
        }

        Self(hasher.finalize().to_hex().to_string())
    }
}
