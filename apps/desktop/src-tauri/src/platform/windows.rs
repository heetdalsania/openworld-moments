// SPDX-License-Identifier: AGPL-3.0-or-later
//! Windows implementation of the platform interfaces. Behavior is the same as before
//! M33; the code moved here from the product modules unchanged.

use std::path::Path;
use std::process::Command;

use super::{Family, Probe};

pub const FAMILY: Family = Family::Windows;

/// The Windows version is reported by the worker's system check; the host does not
/// read it, and x64 emulation on Arm is not detected (the alpha ships x64 only).
pub fn probe() -> Probe {
    Probe::default()
}

/// Explorer parses its own command line: `/select,"<path>"`. Windows paths cannot
/// contain quotes, and the path comes from the host, not the webview.
pub fn reveal_command(target: &Path, select: bool) -> Command {
    use std::os::windows::process::CommandExt;
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
    let mut command = Command::new(Path::new(&root).join("explorer.exe"));
    let path = target.as_os_str().to_string_lossy();
    if select {
        command.raw_arg(format!("/select,\"{path}\""));
    } else {
        command.raw_arg(format!("\"{path}\""));
    }
    command
}

/// Preserve pipes without opening a console window (`CREATE_NO_WINDOW`).
pub fn hide_console(command: &mut tokio::process::Command) {
    command.creation_flags(0x0800_0000);
}

/// OneDrive "online-only" files: offline or recall-on-access attributes.
pub fn is_cloud_placeholder(meta: &std::fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_OFFLINE: u32 = 0x0000_1000;
    const FILE_ATTRIBUTE_RECALL_ON_OPEN: u32 = 0x0004_0000;
    const FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: u32 = 0x0040_0000;
    meta.file_attributes()
        & (FILE_ATTRIBUTE_OFFLINE
            | FILE_ATTRIBUTE_RECALL_ON_OPEN
            | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
        != 0
}
