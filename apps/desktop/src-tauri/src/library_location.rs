// SPDX-License-Identifier: AGPL-3.0-or-later
//! A native-selected existing library takes effect on the next launch. Selection
//! never copies, moves or deletes footage, and an offline selection never creates
//! an empty replacement database. The preference contains a path, not a secret.

use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub version: u32,
    pub path: PathBuf,
}

pub fn load(data: &Path) -> std::io::Result<Option<Selection>> {
    let file = match std::fs::File::open(data.join("library-location.json")) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let mut bytes = Vec::new();
    file.take(65_537).read_to_end(&mut bytes)?;
    if bytes.len() > 65_536 {
        return Err(std::io::Error::other("Library selection is too large"));
    }
    let selected: Selection = serde_json::from_slice(&bytes)?;
    if selected.version != 1 || !selected.path.is_absolute() {
        return Err(std::io::Error::other("Invalid library selection"));
    }
    Ok(Some(selected))
}

pub fn validate(path: &Path) -> std::io::Result<PathBuf> {
    let path = path.canonicalize()?;
    let database = path.join("database.sqlite3");
    if crate::platform::is_cloud_placeholder(&std::fs::metadata(&path)?)
        || crate::platform::is_cloud_placeholder(&std::fs::symlink_metadata(&database)?)
    {
        return Err(std::io::Error::other(
            "Download the library before selecting it",
        ));
    }
    if !path.is_dir() || !std::fs::symlink_metadata(&database)?.is_file() {
        return Err(std::io::Error::other("Choose an existing library folder"));
    }
    let mut header = [0; 16];
    std::fs::File::open(database)?.read_exact(&mut header)?;
    if &header != b"SQLite format 3\0" {
        return Err(std::io::Error::other(
            "The folder does not hold a SQLite library",
        ));
    }
    Ok(path)
}

pub fn save(data: &Path, selected: &Path) -> std::io::Result<()> {
    let path = validate(selected)?;
    std::fs::create_dir_all(data)?;
    let mut random = [0; 16];
    getrandom::fill(&mut random).map_err(std::io::Error::other)?;
    let temp = data.join(format!(".library-location-{}.tmp", hex::encode(random)));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(&serde_json::to_vec(&Selection { version: 1, path })?)?;
        file.sync_all()?;
        std::fs::rename(&temp, data.join("library-location.json"))
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temp);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remembered_selection_survives_an_offline_drive_without_creating_a_database() {
        let dir = tempfile::tempdir().unwrap();
        let data = dir.path().join("Support");
        let library = dir.path().join("Drive ✓/Library");
        std::fs::create_dir_all(&library).unwrap();
        std::fs::write(
            library.join("database.sqlite3"),
            b"SQLite format 3\0fixture",
        )
        .unwrap();
        assert!(load(&data).unwrap().is_none());
        save(&data, &library).unwrap();
        let selected = load(&data).unwrap().unwrap();
        assert_eq!(selected.path, library.canonicalize().unwrap());
        let offline = dir.path().join("Disconnected");
        std::fs::rename(&library, &offline).unwrap();
        assert_eq!(load(&data).unwrap().unwrap().path, selected.path);
        assert!(!library.exists());
        std::fs::rename(offline, &library).unwrap();
        assert_eq!(validate(&library).unwrap(), selected.path);
    }

    #[test]
    fn invalid_or_unavailable_selection_preserves_the_previous_preference() {
        let dir = tempfile::tempdir().unwrap();
        let library = dir.path().join("library");
        std::fs::create_dir(&library).unwrap();
        std::fs::write(
            library.join("database.sqlite3"),
            b"SQLite format 3\0fixture",
        )
        .unwrap();
        save(dir.path(), &library).unwrap();
        let before = std::fs::read(dir.path().join("library-location.json")).unwrap();
        assert!(save(dir.path(), &dir.path().join("missing")).is_err());
        assert!(save(dir.path(), dir.path()).is_err());
        assert_eq!(
            std::fs::read(dir.path().join("library-location.json")).unwrap(),
            before
        );
        assert_eq!(
            std::fs::read(library.join("database.sqlite3")).unwrap(),
            b"SQLite format 3\0fixture"
        );
    }
}
