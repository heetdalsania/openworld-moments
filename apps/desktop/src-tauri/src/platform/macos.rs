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

/// Apple TN3150: SF_DATALESS marks File Provider metadata without local bytes.
/// Metadata only: opening the item would ask the provider to download it.
pub fn is_cloud_placeholder(meta: &std::fs::Metadata) -> bool {
    use std::os::macos::fs::MetadataExt;
    dataless(meta.st_flags())
}

fn dataless(flags: u32) -> bool {
    flags & 0x4000_0000 != 0 // SF_DATALESS, sys/stat.h
}

/// Install once, for the lifetime of this app process. NSNotificationCenter retains
/// its block observers. Blocks capture only a Send channel, never UI or borrowed data.
pub fn observe_lifecycle(sender: tokio::sync::mpsc::UnboundedSender<super::LifecycleEvent>) {
    use objc2_app_kit::{
        NSWorkspace, NSWorkspaceDidWakeNotification, NSWorkspaceWillSleepNotification,
    };
    use objc2_foundation::NSNotification;
    use std::ptr::NonNull;
    let center = NSWorkspace::sharedWorkspace().notificationCenter();
    // SAFETY: AppKit exports both names as process-lifetime NSString constants.
    let names = unsafe {
        [
            (
                NSWorkspaceWillSleepNotification,
                super::LifecycleEvent::Sleep,
            ),
            (NSWorkspaceDidWakeNotification, super::LifecycleEvent::Wake),
        ]
    };
    for (name, event) in names {
        let sender = sender.clone();
        let block = block2::RcBlock::new(move |_: NonNull<NSNotification>| {
            let _ = sender.send(event);
        });
        // SAFETY: no object/queue, and the copied block captures only Send data.
        unsafe {
            center.addObserverForName_object_queue_usingBlock(Some(name), None, None, &block);
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn only_dataless_flag_means_cloud_only() {
        assert!(super::dataless(0x4000_0000));
        assert!(super::dataless(0x4000_8000));
        assert!(!super::dataless(0));
        assert!(!super::dataless(0x8000)); // UF_HIDDEN is not a placeholder
    }
}
