// SPDX-License-Identifier: AGPL-3.0-or-later
//! Linux (development only) implementation of the platform interfaces.

use std::path::Path;
use std::process::Command;

use super::{Family, Probe};

pub const FAMILY: Family = Family::Linux;

pub fn probe() -> Probe {
    Probe::default()
}

/// `xdg-open` shows the containing folder; there is no portable "select".
pub fn reveal_command(target: &Path, select: bool) -> Command {
    let folder = if select {
        target.parent().unwrap_or(target)
    } else {
        target
    };
    let mut command = Command::new("xdg-open");
    command.arg(folder);
    command
}

pub fn hide_console(_command: &mut tokio::process::Command) {}

pub fn is_cloud_placeholder(_meta: &std::fs::Metadata) -> bool {
    false
}
