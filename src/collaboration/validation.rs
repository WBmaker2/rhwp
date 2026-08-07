use super::{CollaborationError, CollaborationManifest, COLLABORATION_SCHEMA_VERSION};

const MAX_SOURCE_FINGERPRINT_BYTES: usize = 256;

pub fn validate_source_fingerprint(value: &str) -> Result<(), CollaborationError> {
    if value.is_empty() {
        return Err(CollaborationError::EmptySourceFingerprint);
    }
    if value.len() > MAX_SOURCE_FINGERPRINT_BYTES {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: format!("must be at most {MAX_SOURCE_FINGERPRINT_BYTES} bytes"),
        });
    }
    if value.trim() != value {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "must not contain leading or trailing whitespace".to_string(),
        });
    }
    if value.chars().any(char::is_control) {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "must not contain control characters".to_string(),
        });
    }

    let Some((algorithm, digest)) = value.split_once(':') else {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "must use algorithm:digest form".to_string(),
        });
    };

    if algorithm.is_empty() || digest.is_empty() {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "algorithm and digest must not be empty".to_string(),
        });
    }

    if !algorithm
        .bytes()
        .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "algorithm must contain lowercase ASCII letters, digits, or '-'".to_string(),
        });
    }

    if !digest
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err(CollaborationError::InvalidSourceFingerprint {
            reason: "digest must contain ASCII letters, digits, '-', '_', or '.'".to_string(),
        });
    }

    Ok(())
}

pub fn validate_collaboration_manifest(
    manifest: &CollaborationManifest,
) -> Result<(), CollaborationError> {
    if manifest.schema_version != COLLABORATION_SCHEMA_VERSION {
        return Err(CollaborationError::UnsupportedSchemaVersion {
            expected: COLLABORATION_SCHEMA_VERSION,
            actual: manifest.schema_version,
        });
    }

    validate_source_fingerprint(&manifest.source_fingerprint)
}
