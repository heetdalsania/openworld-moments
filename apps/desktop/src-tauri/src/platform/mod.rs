// SPDX-License-Identifier: AGPL-3.0-or-later
//! M33: the one place operating-system differences live.
//!
//! Product modules (worker supervision, watched folders, phone import, reveal) call the
//! interfaces here instead of writing `cfg(target_os)` themselves. Each OS has a small
//! implementation module; everything that decides something (support level, directory
//! layout, the capabilities report) is a pure function of [`Facts`] so it is tested on
//! every platform, not only the one CI happens to run.
//!
//! See `docs/platforms/platform-interfaces.md` for the reviewed interface list.

use std::path::{Path, PathBuf};

use serde::Serialize;

#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "macos")]
use macos as imp;
#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
use windows as imp;
#[cfg(not(any(target_os = "windows", target_os = "macos")))]
mod other;
#[cfg(not(any(target_os = "windows", target_os = "macos")))]
use other as imp;

#[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
compile_error!("OpenWorld Moments builds only for x86_64 and aarch64");

pub use imp::{hide_console, is_cloud_placeholder, reveal_command};

/// Oldest macOS release the macOS builds support (verified in M33; see
/// `docs/platforms/macos-os-floor.md`). Keep in sync with `tauri.macos.conf.json`.
pub const MACOS_MINIMUM: &str = "14.0";

/// Product name used for macOS application folders.
pub const APP_FOLDER: &str = "OpenWorld Moments";

/// Target triple the host was compiled for, recorded by `build.rs`.
pub const TARGET: &str = env!("OWM_BUILD_TARGET");

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Family {
    Windows,
    Macos,
    Linux,
}

/// What the host learns about the computer it runs on. Gathered once.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Facts {
    pub family: Family,
    /// Marketing version (`15.2`), when the host reads it.
    pub os_version: Option<String>,
    /// `x86_64` or `aarch64`: what the executable was built for.
    pub arch: &'static str,
    /// Running under translation (Rosetta 2); `None` when the OS cannot say.
    pub translated: Option<bool>,
    pub target: &'static str,
    pub debug: bool,
}

/// The facts for this process. The OS is asked once and the answer cached.
pub fn facts() -> Facts {
    static FACTS: std::sync::OnceLock<Facts> = std::sync::OnceLock::new();
    FACTS
        .get_or_init(|| {
            let probe = imp::probe();
            Facts {
                family: imp::FAMILY,
                os_version: probe.os_version,
                arch: std::env::consts::ARCH,
                translated: probe.translated,
                target: TARGET,
                debug: cfg!(debug_assertions),
            }
        })
        .clone()
}

/// What the OS implementation reports.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Probe {
    pub os_version: Option<String>,
    pub translated: Option<bool>,
}

/// Parse a dotted release (`14`, `14.6`, `14.6.1`) into a comparable triple.
pub fn release(text: &str) -> Option<(u32, u32, u32)> {
    let mut parts = text.trim().split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next().map_or(Some(0), |p| p.parse().ok())?;
    let patch = parts.next().map_or(Some(0), |p| p.parse().ok())?;
    if parts.next().is_some() {
        return None;
    }
    Some((major, minor, patch))
}

/// `alpha`, `development` or `unsupported`, with the reasons behind it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Support {
    pub level: &'static str,
    pub reasons: Vec<&'static str>,
}

const BLOCKING: [&str; 3] = ["os-below-minimum", "translated", "architecture-unsupported"];

pub fn minimum(family: Family) -> Option<&'static str> {
    (family == Family::Macos).then_some(MACOS_MINIMUM)
}

/// Support policy (docs/platforms/macos-delivery-plan.md): Windows x64 release builds are
/// the alpha target; macOS stays a development target until M39 qualifies it; a build
/// running under translation or on an OS older than the floor is unsupported.
pub fn support(facts: &Facts) -> Support {
    let mut reasons = Vec::new();
    if facts.debug {
        reasons.push("debug-build");
    }
    match facts.family {
        Family::Macos => reasons.push("macos-preview"),
        Family::Linux => reasons.push("linux-development"),
        Family::Windows => {}
    }
    let below = match (facts.os_version.as_deref(), minimum(facts.family)) {
        (Some(version), Some(floor)) => match (release(version), release(floor)) {
            (Some(v), Some(f)) => v < f,
            _ => false,
        },
        _ => false,
    };
    if below {
        reasons.push("os-below-minimum");
    }
    if facts.translated == Some(true) {
        reasons.push("translated");
    }
    // The Windows alpha ships x64 only (Windows on Arm would emulate it).
    if facts.family == Family::Windows && facts.arch != "x86_64" {
        reasons.push("architecture-unsupported");
    }
    let level = if reasons.iter().any(|r| BLOCKING.contains(r)) {
        "unsupported"
    } else if reasons.is_empty() {
        "alpha"
    } else {
        "development"
    };
    Support { level, reasons }
}

/// Whether this build starts the worker from its own bundle: Windows (M29) and macOS
/// (M34) release builds. Debug builds use the repository's virtualenv.
pub fn bundled_worker(facts: &Facts) -> bool {
    matches!(facts.family, Family::Windows | Family::Macos) && !facts.debug
}

/// The bundled worker executable inside `runtime/` (same layout on both platforms).
pub const WORKER_EXECUTABLE: &str = if cfg!(windows) {
    "owm-worker.exe"
} else {
    "owm-worker"
};

/// The `platform-capabilities` contract document (no paths, names or identifiers).
pub fn capabilities(host_version: &str, facts: &Facts) -> serde_json::Value {
    let (convention, file_manager) = match facts.family {
        Family::Windows => ("windows-appdata", "explorer"),
        Family::Macos => ("macos-standard", "finder"),
        Family::Linux => ("xdg", "xdg-open"),
    };
    serde_json::json!({
        "schema_version": SCHEMA_VERSION,
        "host_version": host_version,
        "os": {
            "family": facts.family,
            "version": facts.os_version,
            "minimum": minimum(facts.family),
        },
        "architecture": { "binary": facts.arch, "translated": facts.translated },
        "build": {
            "target": facts.target,
            "profile": if facts.debug { "debug" } else { "release" },
            "bundled_worker": bundled_worker(facts),
        },
        "support": support(facts),
        "directories": { "convention": convention },
        // Nothing persists a secret yet (M35 adds the Keychain); the app keeps the
        // default Tauri menus until M38 adds native ones.
        "integrations": { "file_manager": file_manager, "secret_store": "none", "menus": "default" },
    })
}

/// Contract version the host writes. Kept equal to the contracts package by a test.
pub const SCHEMA_VERSION: &str = "1.26";

/// Where the app keeps its files. Only `data` holds the canonical library today; M35
/// moves disposable caches and logs into `cache` and `logs`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppDirs {
    pub data: PathBuf,
    pub cache: PathBuf,
    pub logs: PathBuf,
    pub temp: PathBuf,
}

impl AppDirs {
    /// The canonical library folder.
    pub fn library(&self) -> PathBuf {
        self.data.join("library")
    }
}

/// macOS-standard folders under the user's home (never derived from a shell variable
/// other than the home directory itself).
pub fn macos_dirs(home: &Path, temp: &Path) -> AppDirs {
    let library = home.join("Library");
    AppDirs {
        data: library.join("Application Support").join(APP_FOLDER),
        cache: library.join("Caches").join(APP_FOLDER),
        logs: library.join("Logs").join(APP_FOLDER),
        temp: temp.join(APP_FOLDER),
    }
}

/// Resolve the folders for this OS. Windows and Linux keep the Tauri locations they
/// have used since M03, so existing libraries stay where they are.
pub fn app_dirs<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<AppDirs> {
    use tauri::Manager;
    let paths = app.path();
    if cfg!(target_os = "macos") {
        return Ok(macos_dirs(&paths.home_dir()?, &std::env::temp_dir()));
    }
    Ok(AppDirs {
        data: paths.app_data_dir()?,
        cache: paths.app_cache_dir()?,
        logs: paths.app_log_dir()?,
        temp: std::env::temp_dir().join(APP_FOLDER),
    })
}

/// The repository virtualenv's interpreter (development builds only).
pub fn venv_python(repo: &Path) -> PathBuf {
    if cfg!(windows) {
        repo.join(".venv/Scripts/python.exe")
    } else {
        repo.join(".venv/bin/python")
    }
}

/// The `--version-report` output: the capabilities document as indented JSON.
pub fn version_report(host_version: &str, facts: &Facts) -> String {
    serde_json::to_string_pretty(&capabilities(host_version, facts))
        .unwrap_or_else(|_| "{}".to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mac(version: &str, arch: &'static str, translated: Option<bool>) -> Facts {
        Facts {
            family: Family::Macos,
            os_version: Some(version.to_owned()),
            arch,
            translated,
            target: "aarch64-apple-darwin",
            debug: false,
        }
    }

    fn windows(arch: &'static str, debug: bool) -> Facts {
        Facts {
            family: Family::Windows,
            os_version: None,
            arch,
            translated: None,
            target: "x86_64-pc-windows-msvc",
            debug,
        }
    }

    #[test]
    fn releases_compare_numerically() {
        assert_eq!(release("14"), Some((14, 0, 0)));
        assert_eq!(release("14.6.1"), Some((14, 6, 1)));
        assert!(release("13.10").unwrap() < release("14.0").unwrap());
        assert!(release("10.15.7").unwrap() < release("14").unwrap());
        for bad in ["", "14.", "fourteen", "14.1.2.3", "-1"] {
            assert_eq!(release(bad), None, "{bad}");
        }
    }

    #[test]
    fn native_macos_at_or_above_the_floor_is_a_development_target() {
        for version in ["14.0", "14.7.2", "15.2", "26.1"] {
            for arch in ["aarch64", "x86_64"] {
                let s = support(&mac(version, arch, Some(false)));
                assert_eq!(s.level, "development", "{version} {arch}");
                assert_eq!(s.reasons, vec!["macos-preview"]);
            }
        }
    }

    #[test]
    fn macos_below_the_floor_or_under_rosetta_is_unsupported() {
        let old = support(&mac("13.6.1", "aarch64", Some(false)));
        assert_eq!(old.level, "unsupported");
        assert!(old.reasons.contains(&"os-below-minimum"));
        let rosetta = support(&mac("15.2", "x86_64", Some(true)));
        assert_eq!(rosetta.level, "unsupported");
        assert!(rosetta.reasons.contains(&"translated"));
        // An Intel Mac answers "not translated" by having no such sysctl.
        assert_eq!(support(&mac("15.2", "x86_64", None)).level, "development");
    }

    #[test]
    fn windows_policy_is_unchanged() {
        assert_eq!(support(&windows("x86_64", false)).level, "alpha");
        assert!(support(&windows("x86_64", false)).reasons.is_empty());
        let debug = support(&windows("x86_64", true));
        assert_eq!(
            (debug.level, debug.reasons),
            ("development", vec!["debug-build"])
        );
        assert_eq!(support(&windows("aarch64", false)).level, "unsupported");
        assert!(bundled_worker(&windows("x86_64", false)));
        assert!(!bundled_worker(&windows("x86_64", true)));
        assert!(bundled_worker(&mac("15.2", "aarch64", Some(false))));
        let mut debug_mac = mac("15.2", "aarch64", Some(false));
        debug_mac.debug = true;
        assert!(!bundled_worker(&debug_mac));
        let linux = Facts {
            family: Family::Linux,
            ..mac("15.2", "x86_64", None)
        };
        assert!(!bundled_worker(&linux));
    }

    #[test]
    fn capabilities_follow_the_contract_shape_and_carry_no_paths() {
        let doc = capabilities("0.1.0", &mac("15.2", "aarch64", Some(false)));
        assert_eq!(doc["schema_version"], SCHEMA_VERSION);
        assert_eq!(doc["os"]["family"], "macos");
        assert_eq!(doc["os"]["minimum"], MACOS_MINIMUM);
        assert_eq!(doc["architecture"]["binary"], "aarch64");
        assert_eq!(doc["build"]["profile"], "release");
        assert_eq!(doc["directories"]["convention"], "macos-standard");
        assert_eq!(doc["integrations"]["file_manager"], "finder");
        let text = doc.to_string();
        assert!(!text.contains('/') && !text.contains('\\'), "{text}");
        let keys: Vec<_> = doc.as_object().unwrap().keys().cloned().collect();
        assert_eq!(
            keys,
            [
                "architecture",
                "build",
                "directories",
                "host_version",
                "integrations",
                "os",
                "schema_version",
                "support"
            ]
        );
        let win = capabilities("0.1.0", &windows("x86_64", false));
        assert_eq!(win["os"]["minimum"], serde_json::Value::Null);
        assert_eq!(win["directories"]["convention"], "windows-appdata");
        assert_eq!(win["build"]["bundled_worker"], true);
    }

    #[test]
    fn host_writes_the_current_contract_version() {
        let versioning = include_str!("../../../../../packages/contracts/src/versioning.ts");
        let (major, minor) = SCHEMA_VERSION.split_once('.').unwrap();
        assert!(
            versioning.contains(&format!("major: {major}, minor: {minor} }}")),
            "SCHEMA_VERSION {SCHEMA_VERSION} differs from the contracts package"
        );
    }

    #[test]
    fn macos_folders_are_the_standard_library_folders() {
        let dirs = macos_dirs(
            Path::new("/Users/tester"),
            Path::new("/private/var/folders/x/T"),
        );
        assert_eq!(
            dirs.data,
            Path::new("/Users/tester/Library/Application Support/OpenWorld Moments")
        );
        assert_eq!(
            dirs.library(),
            Path::new("/Users/tester/Library/Application Support/OpenWorld Moments/library")
        );
        assert_eq!(
            dirs.cache,
            Path::new("/Users/tester/Library/Caches/OpenWorld Moments")
        );
        assert_eq!(
            dirs.logs,
            Path::new("/Users/tester/Library/Logs/OpenWorld Moments")
        );
        assert_eq!(
            dirs.temp,
            Path::new("/private/var/folders/x/T/OpenWorld Moments")
        );
    }

    #[test]
    fn this_process_reports_its_own_build() {
        let facts = facts();
        assert_eq!(facts.arch, std::env::consts::ARCH);
        assert!(facts.target.starts_with(facts.arch), "{}", facts.target);
        assert_eq!(facts.debug, cfg!(debug_assertions));
        let report: serde_json::Value =
            serde_json::from_str(&version_report("0.0.0", &facts)).unwrap();
        assert_eq!(report["build"]["target"], TARGET);
        if cfg!(target_os = "macos") {
            let version = facts.os_version.expect("macOS reports its version");
            assert!(release(&version).is_some(), "{version}");
            assert!(facts.translated.is_some() || facts.arch == "x86_64");
        }
    }

    #[test]
    fn file_manager_is_started_by_absolute_path_without_a_shell() {
        let command = reveal_command(Path::new("/tmp/render.mp4"), true);
        let program = Path::new(command.get_program());
        let name = program.to_string_lossy().to_lowercase();
        assert!(!name.contains("cmd") && !name.ends_with("sh"), "{name}");
        if !cfg!(target_os = "linux") {
            // No reliance on a shell PATH where the OS has a fixed location.
            assert!(program.is_absolute(), "{name}");
        }
    }
}
