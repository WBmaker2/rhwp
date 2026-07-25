use std::error::Error;
use std::fmt;

use super::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CollaborationError {
    EmptySourceFingerprint,
    InvalidSourceFingerprint { reason: String },
    UnsupportedSchemaVersion { expected: u32, actual: u32 },
    SerializationFailed { message: String },
    StableIdMismatch { expected: String, actual: String },
    TargetOutOfBounds { kind: String },
    TargetKindMismatch { expected: String },
    UnsupportedCellParagraphStructure { paragraph_count: usize },
    ReadonlyTarget(StableId),
    UnknownTarget(StableId),
    InvalidImage { image_id: StableId, reason: String },
}

impl fmt::Display for CollaborationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptySourceFingerprint => {
                formatter.write_str("source fingerprint must not be empty")
            }
            Self::InvalidSourceFingerprint { reason } => {
                write!(formatter, "invalid source fingerprint: {reason}")
            }
            Self::UnsupportedSchemaVersion { expected, actual } => write!(
                formatter,
                "unsupported collaboration schema version: expected {expected}, got {actual}"
            ),
            Self::SerializationFailed { message } => {
                write!(
                    formatter,
                    "failed to serialize collaboration manifest: {message}"
                )
            }
            Self::StableIdMismatch { expected, actual } => write!(
                formatter,
                "collaboration stable id mismatch: expected {expected}, got {actual}"
            ),
            Self::TargetOutOfBounds { kind } => {
                write!(formatter, "collaboration {kind} target is out of bounds")
            }
            Self::TargetKindMismatch { expected } => write!(
                formatter,
                "collaboration target kind mismatch: expected {expected}"
            ),
            Self::UnsupportedCellParagraphStructure { paragraph_count } => write!(
                formatter,
                "collaboration cell requires exactly one paragraph, got {paragraph_count}"
            ),
            Self::ReadonlyTarget(target_id) => {
                write!(
                    formatter,
                    "collaboration target is read-only: {}",
                    target_id.0
                )
            }
            Self::UnknownTarget(target_id) => {
                write!(formatter, "unknown collaboration target: {}", target_id.0)
            }
            Self::InvalidImage { image_id, reason } => {
                write!(
                    formatter,
                    "invalid collaboration image {}: {reason}",
                    image_id.0
                )
            }
        }
    }
}

impl Error for CollaborationError {}
