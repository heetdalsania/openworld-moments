// SPDX-License-Identifier: AGPL-3.0-or-later
//! M31: show a finished render or the library folder in the system file manager.
//!
//! The webview never names a path. The host resolves a render's library-relative output
//! itself, checks it stays inside the library and is a regular file, and then starts the
//! platform file manager with an argument array (no shell).

use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

/// A render output relative to the library: `renders/prj_<ULID>/job_<ULID>.mp4`.
pub fn render_relative_ok(relative: &str) -> bool {
    fn ulid(text: &str) -> bool {
        text.len() == 26
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b.is_ascii_uppercase() && !b"ILOU".contains(&b)))
    }
    let parts: Vec<&str> = relative.split('/').collect();
    match parts.as_slice() {
        ["renders", project, file] => {
            project.strip_prefix("prj_").is_some_and(ulid)
                && file
                    .strip_prefix("job_")
                    .and_then(|f| f.strip_suffix(".mp4"))
                    .is_some_and(ulid)
        }
        _ => false,
    }
}

/// The existing output file for a render, or `None` if it is missing, a link, or would
/// resolve outside the library.
pub fn render_output(library: &Path, relative: &str) -> Option<PathBuf> {
    if !render_relative_ok(relative) {
        return None;
    }
    let candidate = library.join(Path::new(relative));
    if candidate
        .components()
        .any(|c| matches!(c, Component::ParentDir))
    {
        return None;
    }
    let meta = std::fs::symlink_metadata(&candidate).ok()?;
    if !meta.file_type().is_file() {
        return None;
    }
    let root = std::fs::canonicalize(library).ok()?;
    let resolved = std::fs::canonicalize(&candidate).ok()?;
    resolved.starts_with(&root).then_some(resolved)
}

/// The file manager command that shows `target`, selecting it when `select` is true.
pub fn command(target: &Path, select: bool) -> Command {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let root = std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
        let mut command = Command::new(Path::new(&root).join("explorer.exe"));
        // Explorer parses its own command line: `/select,"<path>"`. Windows paths cannot
        // contain quotes, and the path comes from the host, not the webview.
        let path = target.as_os_str().to_string_lossy();
        if select {
            command.raw_arg(format!("/select,\"{path}\""));
        } else {
            command.raw_arg(format!("\"{path}\""));
        }
        command
    }
    #[cfg(target_os = "macos")]
    {
        let mut command = Command::new("/usr/bin/open");
        if select {
            command.arg("-R");
        }
        command.arg("--").arg(target);
        command
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let folder = if select {
            target.parent().unwrap_or(target)
        } else {
            target
        };
        let mut command = Command::new("xdg-open");
        command.arg(folder);
        command
    }
}

/// Start the file manager and reap it in the background; its exit code is not meaningful
/// (Explorer returns 1 on success).
pub fn show(target: &Path, select: bool) -> std::io::Result<()> {
    let mut child = command(target, select)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PROJECT: &str = "prj_01JCBQ00000000000000000001";
    const JOB: &str = "job_01JCBQ00000000000000000002";

    #[test]
    fn only_library_render_outputs_are_accepted() {
        assert!(render_relative_ok(&format!("renders/{PROJECT}/{JOB}.mp4")));
        for bad in [
            format!("renders/{PROJECT}/{JOB}.manifest.json"),
            format!("renders/{PROJECT}/../{JOB}.mp4"),
            format!("/renders/{PROJECT}/{JOB}.mp4"),
            format!("renders\\{PROJECT}\\{JOB}.mp4"),
            format!("derived/{PROJECT}/{JOB}.mp4"),
            format!("renders/{PROJECT}/job_01jcbq00000000000000000002.mp4"),
            format!("renders/{PROJECT}/{JOB}.mp4/extra"),
            String::new(),
        ] {
            assert!(!render_relative_ok(&bad), "{bad}");
        }
    }

    #[test]
    fn render_output_requires_a_real_file_inside_the_library() {
        let dir = tempfile::tempdir().unwrap();
        let library = dir.path().join("library");
        let relative = format!("renders/{PROJECT}/{JOB}.mp4");
        std::fs::create_dir_all(library.join("renders").join(PROJECT)).unwrap();
        assert_eq!(render_output(&library, &relative), None, "missing file");
        std::fs::create_dir(library.join(&relative)).unwrap();
        assert_eq!(render_output(&library, &relative), None, "directory");
        std::fs::remove_dir(library.join(&relative)).unwrap();
        std::fs::write(library.join(&relative), b"mp4").unwrap();
        let found = render_output(&library, &relative).unwrap();
        assert!(found.ends_with(format!("{JOB}.mp4")));
    }

    #[cfg(unix)]
    #[test]
    fn render_output_refuses_links_out_of_the_library() {
        let dir = tempfile::tempdir().unwrap();
        let library = dir.path().join("library");
        let outside = dir.path().join("private.mp4");
        std::fs::write(&outside, b"private").unwrap();
        std::fs::create_dir_all(library.join("renders").join(PROJECT)).unwrap();
        let relative = format!("renders/{PROJECT}/{JOB}.mp4");
        std::os::unix::fs::symlink(&outside, library.join(&relative)).unwrap();
        assert_eq!(render_output(&library, &relative), None);
    }

    #[test]
    fn file_manager_is_started_without_a_shell() {
        let command = command(Path::new("/tmp/render.mp4"), true);
        let program = command.get_program().to_string_lossy().to_lowercase();
        assert!(
            !program.contains("cmd") && !program.ends_with("sh"),
            "{program}"
        );
    }
}
