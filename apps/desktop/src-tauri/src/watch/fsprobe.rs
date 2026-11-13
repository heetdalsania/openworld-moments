// SPDX-License-Identifier: AGPL-3.0-or-later
//! Read-only filesystem checks for watched files: metadata, cloud placeholders,
//! readability, and a bounded folder walk. Nothing here writes, moves, or deletes.

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use super::stabilizer::Meta;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileState {
    /// A local regular file with this metadata.
    Local(Meta),
    /// A cloud placeholder (e.g. OneDrive Files On-Demand) whose bytes are not on
    /// this computer yet. It is not opened, so no download is triggered.
    CloudOnly,
    /// Gone, not a regular file, or empty.
    Absent,
}

pub fn mtime_ns(meta: &fs::Metadata) -> i128 {
    match meta.modified() {
        Ok(t) => match t.duration_since(UNIX_EPOCH) {
            Ok(d) => d.as_nanos() as i128,
            Err(e) => -(e.duration().as_nanos() as i128),
        },
        Err(_) => 0,
    }
}

fn is_cloud_placeholder(meta: &fs::Metadata) -> bool {
    crate::platform::is_cloud_placeholder(meta)
}

/// Metadata of a file without following symlinks (watched folders never follow links).
pub fn file_state(path: &Path) -> FileState {
    match fs::symlink_metadata(path) {
        Ok(m) if m.is_file() && is_cloud_placeholder(&m) => FileState::CloudOnly,
        Ok(m) if m.is_file() && m.len() > 0 => FileState::Local(Meta {
            size: m.len(),
            mtime_ns: mtime_ns(&m),
        }),
        _ => FileState::Absent,
    }
}

/// Can the file be opened and read? (Another program may still hold it exclusively.)
pub fn readable(path: &Path) -> bool {
    if !matches!(file_state(path), FileState::Local(_)) {
        return false;
    }
    let mut byte = [0u8; 1];
    fs::File::open(path)
        .and_then(|mut f| f.read(&mut byte))
        .is_ok()
}

pub fn folder_available(path: &Path) -> Result<(), String> {
    match fs::metadata(path) {
        Ok(m) if crate::platform::is_cloud_placeholder(&m) => Err("download-required".into()),
        Ok(m) if m.is_dir() => fs::read_dir(path)
            .map(|_| ())
            .map_err(|e| access_reason(&e).into()),
        Ok(_) => Err("not a folder".into()),
        Err(e) => Err(access_reason(&e).into()),
    }
}

fn access_reason(error: &std::io::Error) -> &'static str {
    match error.kind() {
        std::io::ErrorKind::PermissionDenied => "permission-required",
        std::io::ErrorKind::NotFound | std::io::ErrorKind::NotConnected => "offline",
        _ => "unavailable",
    }
}

/// '/'-separated path of `path` inside `root`, or None when it is outside or not
/// valid UTF-8 (such names cannot be reported and are skipped).
pub fn relative(root: &Path, path: &Path) -> Option<String> {
    let rel = path.strip_prefix(root).ok()?;
    let parts: Option<Vec<&str>> = rel
        .components()
        .map(|c| match c {
            std::path::Component::Normal(part) => part.to_str(),
            _ => None,
        })
        .collect();
    let parts = parts?;
    (!parts.is_empty()).then(|| parts.join("/"))
}

/// Regular files under `root` (subfolders when `recursive`), never following links,
/// at most `max_entries` files and `max_depth` levels. Unreadable subfolders are skipped.
pub fn walk(root: &Path, recursive: bool, max_entries: usize, max_depth: usize) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![(root.to_path_buf(), 0usize)];
    while let Some((dir, depth)) = stack.pop() {
        // A dataless directory can trigger a download just by enumerating it.
        let metadata = if dir == root {
            fs::metadata(&dir)
        } else {
            fs::symlink_metadata(&dir)
        };
        if !metadata.is_ok_and(|m| !m.is_symlink() && !crate::platform::is_cloud_placeholder(&m)) {
            continue;
        }
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_symlink() {
                continue;
            }
            if kind.is_dir() {
                if recursive && depth + 1 < max_depth {
                    stack.push((entry.path(), depth + 1));
                }
            } else if kind.is_file() {
                out.push(entry.path());
                if out.len() >= max_entries {
                    return out;
                }
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relative_paths_use_slashes() {
        let root = Path::new("/w");
        assert_eq!(
            relative(root, Path::new("/w/a/b.mp4")).as_deref(),
            Some("a/b.mp4")
        );
        assert_eq!(relative(root, Path::new("/elsewhere/b.mp4")), None);
        assert_eq!(relative(root, root), None);
        assert_eq!(relative(root, Path::new("/w/../elsewhere/b.mp4")), None);
    }

    #[test]
    fn walk_is_bounded_and_skips_links() {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(dir.path().join("a/b")).unwrap();
        fs::write(dir.path().join("top.mp4"), b"x").unwrap();
        fs::write(dir.path().join("a/b/deep.mp4"), b"x").unwrap();
        assert_eq!(walk(dir.path(), false, 100, 32).len(), 1);
        assert_eq!(walk(dir.path(), true, 100, 32).len(), 2);
        assert_eq!(walk(dir.path(), true, 1, 32).len(), 1);
        assert_eq!(walk(dir.path(), true, 100, 2).len(), 1); // a/b is too deep
    }

    #[test]
    fn empty_and_missing_files_are_absent() {
        let dir = tempfile::tempdir().unwrap();
        let empty = dir.path().join("empty.mp4");
        fs::write(&empty, b"").unwrap();
        assert_eq!(file_state(&empty), FileState::Absent);
        assert_eq!(
            file_state(&dir.path().join("missing.mp4")),
            FileState::Absent
        );
        let full = dir.path().join("full.mp4");
        fs::write(&full, b"abc").unwrap();
        assert!(matches!(
            file_state(&full),
            FileState::Local(Meta { size: 3, .. })
        ));
        assert!(readable(&full));
    }
}
