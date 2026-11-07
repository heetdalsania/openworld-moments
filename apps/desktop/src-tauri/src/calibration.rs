// SPDX-License-Identifier: AGPL-3.0-or-later
//! The save dialog selects the destination. Exports never replace existing files.
use std::{io::Write, path::Path};

/// Write only a new, correctly typed destination chosen by the save dialog.
pub fn write_export(path: &Path, bytes: &[u8], extension: &str) -> std::io::Result<()> {
    if path.extension().and_then(|e| e.to_str()) != Some(extension) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "Wrong output extension",
        ));
    }
    // Atomic exclusive creation also refuses symlinks/hardlinks and existing footage.
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn export_preserves_existing_files_and_requires_expected_extension() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("patch.json");
        write_export(&path, b"{}", "json").unwrap();
        assert!(write_export(&path, b"changed", "json").is_err());
        assert_eq!(std::fs::read(path).unwrap(), b"{}");
        let source = dir.path().join("capture.mp4");
        std::fs::write(&source, b"source").unwrap();
        assert!(write_export(&source, b"changed", "json").is_err());
        let link = dir.path().join("linked.json");
        std::fs::hard_link(&source, &link).unwrap();
        assert!(write_export(&link, b"changed", "json").is_err());
        assert_eq!(std::fs::read(source).unwrap(), b"source");
    }
    #[cfg(unix)]
    #[test]
    fn refuses_symlink_output() {
        let dir = tempfile::tempdir().unwrap();
        let source = dir.path().join("capture.mp4");
        std::fs::write(&source, b"source").unwrap();
        let link = dir.path().join("linked.json");
        std::os::unix::fs::symlink(&source, &link).unwrap();
        assert!(write_export(&link, b"changed", "json").is_err());
        assert_eq!(std::fs::read(source).unwrap(), b"source");
    }
}
