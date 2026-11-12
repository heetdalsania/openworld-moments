// SPDX-License-Identifier: AGPL-3.0-or-later
//! macOS implementation of the platform interfaces.

use std::path::Path;
use std::process::Command;

use super::{Family, Probe};

pub const FAMILY: Family = Family::Macos;

/// Ask the kernel for the OS version and whether this process is translated. `sysctl`
/// is started by absolute path with fixed arguments, so no shell or `PATH` is involved.
/// On Intel Macs `sysctl.proc_translated` does not exist, which means "not translated".
pub fn probe() -> Probe {
    let read = |name: &str| -> Option<String> {
        let out = Command::new("/usr/sbin/sysctl")
            .args(["-n", name])
            .stdin(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .output()
            .ok()?;
        out.status
            .success()
            .then(|| String::from_utf8_lossy(&out.stdout).trim().to_owned())
    };
    let os_version = read("kern.osproductversion").filter(|v| super::release(v).is_some());
    let translated = match read("sysctl.proc_translated").as_deref() {
        Some("1") => Some(true),
        Some("0") => Some(false),
        Some(_) => None,
        None if std::env::consts::ARCH == "x86_64" => Some(false),
        None => None,
    };
    Probe {
        os_version,
        translated,
    }
}

/// Finder: `open -R` selects the item, plain `open` shows a folder.
pub fn reveal_command(target: &Path, select: bool) -> Command {
    let mut command = Command::new("/usr/bin/open");
    if select {
        command.arg("-R");
    }
    command.arg("--").arg(target);
    command
}

/// Child processes never open a window on macOS.
pub fn hide_console(_command: &mut tokio::process::Command) {}

/// File Provider placeholders (iCloud, OneDrive) are handled in M35; until then a file
/// that reads as present is treated as local.
pub fn is_cloud_placeholder(_meta: &std::fs::Metadata) -> bool {
    false
}
