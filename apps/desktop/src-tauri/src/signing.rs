// SPDX-License-Identifier: AGPL-3.0-or-later
//! M38: how the running application is signed, for the system check and diagnostics.
//!
//! The host asks macOS's own tools, `/usr/bin/codesign --display` and
//! `/usr/sbin/spctl --assess`, about its own bundle, by absolute path with fixed
//! arguments (no shell, no `PATH`). Only a classification leaves this module: never the
//! tools' output, the signer's name, the team or a path. The state can only be
//! `notarized` when Gatekeeper itself accepted the bundle as notarized, so the report
//! never claims notarization the bundle lacks.
//!
//! Parsing is pure and tested on every platform; only [`check`] runs the tools.

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Serialize;

/// `platform-capabilities.signing.state`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum State {
    NotApplicable,
    Unknown,
    Unsigned,
    Adhoc,
    DeveloperId,
    Notarized,
    Other,
}

/// `platform-capabilities.signing.gatekeeper`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Gatekeeper {
    NotApplicable,
    Unknown,
    Accepted,
    Rejected,
}

/// The `signing` block of the `platform-capabilities` contract (1.28).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Signing {
    pub state: State,
    pub hardened_runtime: Option<bool>,
    pub gatekeeper: Gatekeeper,
}

impl Signing {
    /// Windows and Linux: signing is not checked.
    pub const NOT_APPLICABLE: Signing = Signing {
        state: State::NotApplicable,
        hardened_runtime: None,
        gatekeeper: Gatekeeper::NotApplicable,
    };
    /// macOS, when the tools could not run or did not answer in time.
    pub const UNKNOWN: Signing = Signing {
        state: State::Unknown,
        hardened_runtime: None,
        gatekeeper: Gatekeeper::Unknown,
    };
}

/// What one tool run produced: whether it exited successfully, and its combined output.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    pub success: bool,
    pub text: String,
}

/// What `codesign --display --verbose=2` says about the signature.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Display {
    unsigned: bool,
    adhoc: bool,
    runtime: bool,
    developer_id: bool,
    has_authority: bool,
}

fn display(outcome: &Outcome) -> Option<Display> {
    let text = &outcome.text;
    if text.contains("code object is not signed at all") {
        return Some(Display {
            unsigned: true,
            adhoc: false,
            runtime: false,
            developer_id: false,
            has_authority: false,
        });
    }
    if !outcome.success {
        return None;
    }
    // `CodeDirectory v=20500 size=… flags=0x10002(adhoc,runtime) hashes=…`
    let flags: Vec<&str> = text
        .lines()
        .filter(|line| line.starts_with("CodeDirectory "))
        .filter_map(|line| {
            line.split_once("flags=")?
                .1
                .split_once('(')?
                .1
                .split_once(')')
        })
        .flat_map(|(names, _)| names.split(','))
        .map(str::trim)
        .collect();
    let authorities: Vec<&str> = text
        .lines()
        .filter_map(|line| line.strip_prefix("Authority="))
        .collect();
    Some(Display {
        unsigned: false,
        adhoc: flags.contains(&"adhoc") || text.lines().any(|l| l.trim() == "Signature=adhoc"),
        runtime: flags.contains(&"runtime"),
        // The leaf certificate comes first.
        developer_id: authorities
            .first()
            .is_some_and(|a| a.starts_with("Developer ID Application:")),
        has_authority: !authorities.is_empty(),
    })
}

/// Gatekeeper's verdict from `spctl --assess --type execute --verbose=2`. An assessment
/// that was overridden (for example with assessments turned off system-wide) is not an
/// acceptance of this bundle, so it reads as unknown.
pub fn gatekeeper(outcome: Option<&Outcome>) -> Gatekeeper {
    let Some(outcome) = outcome else {
        return Gatekeeper::Unknown;
    };
    let text = &outcome.text;
    if text
        .lines()
        .any(|l| l.trim_start().starts_with("override="))
    {
        return Gatekeeper::Unknown;
    }
    if outcome.success && text.contains(": accepted") {
        Gatekeeper::Accepted
    } else if text.contains("rejected") {
        Gatekeeper::Rejected
    } else {
        Gatekeeper::Unknown
    }
}

fn notarized_source(outcome: Option<&Outcome>) -> bool {
    outcome.is_some_and(|o| {
        o.text
            .lines()
            .any(|l| l.trim() == "source=Notarized Developer ID")
    })
}

/// Combine both tools' answers. `codesign` decides how the bundle is signed; only a
/// Gatekeeper acceptance whose source is "Notarized Developer ID" makes it `notarized`.
pub fn classify(codesign: Option<&Outcome>, spctl: Option<&Outcome>) -> Signing {
    let Some(shown) = codesign.and_then(display) else {
        return Signing::UNKNOWN;
    };
    let mut verdict = gatekeeper(spctl);
    let state = if shown.unsigned {
        State::Unsigned
    } else if shown.adhoc {
        State::Adhoc
    } else if shown.developer_id {
        if verdict == Gatekeeper::Accepted && notarized_source(spctl) {
            State::Notarized
        } else {
            State::DeveloperId
        }
    } else if shown.has_authority {
        State::Other
    } else {
        State::Unknown
    };
    // Gatekeeper never accepts these; an "accepted" here can only be a misreading.
    if matches!(state, State::Unsigned | State::Adhoc) && verdict == Gatekeeper::Accepted {
        verdict = Gatekeeper::Unknown;
    }
    Signing {
        state,
        hardened_runtime: if state == State::Unknown {
            None
        } else {
            Some(shown.runtime)
        },
        gatekeeper: verdict,
    }
}

/// The code to assess: the enclosing `.app` bundle when the executable is
/// `X.app/Contents/MacOS/<name>`, otherwise the executable itself (development builds).
pub fn assessed_path(executable: &Path) -> PathBuf {
    let bundle = executable
        .parent()
        .filter(|p| p.file_name().is_some_and(|n| n == "MacOS"))
        .and_then(Path::parent)
        .filter(|p| p.file_name().is_some_and(|n| n == "Contents"))
        .and_then(Path::parent)
        .filter(|p| p.extension().is_some_and(|e| e == "app"));
    bundle.map_or_else(|| executable.to_path_buf(), Path::to_path_buf)
}

/// How long each tool may take. `spctl` may ask Apple's ticket service about a
/// Developer ID bundle that has no stapled ticket.
const TOOL_TIMEOUT: Duration = Duration::from_secs(15);

/// Run one system tool with fixed arguments, a clean environment and a timeout.
fn run(program: &str, args: &[&str], target: &Path, timeout: Duration) -> Option<Outcome> {
    use std::io::Read;
    use std::process::{Command, Stdio};
    let mut child = Command::new(program)
        .args(args)
        .arg(target)
        .env_clear()
        .env("LC_ALL", "C")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;
    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if std::time::Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(25));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let mut text = String::new();
    // Both tools print a few hundred bytes at most, far below a pipe's buffer.
    if let Some(mut out) = child.stdout.take() {
        let _ = out.read_to_string(&mut text);
    }
    if let Some(mut err) = child.stderr.take() {
        let _ = err.read_to_string(&mut text);
    }
    Some(Outcome {
        success: status.success(),
        text,
    })
}

/// Ask macOS how `target` is signed. Blocking: call it off the UI thread.
pub fn check(target: &Path) -> Signing {
    let codesign = run(
        "/usr/bin/codesign",
        &["--display", "--verbose=2"],
        target,
        TOOL_TIMEOUT,
    );
    let spctl = run(
        "/usr/sbin/spctl",
        &["--assess", "--type", "execute", "--verbose=2"],
        target,
        TOOL_TIMEOUT,
    );
    classify(codesign.as_ref(), spctl.as_ref())
}

/// This process's signing state, checked once per launch. Not checked off macOS.
pub fn current(family: crate::platform::Family) -> Signing {
    if family != crate::platform::Family::Macos {
        return Signing::NOT_APPLICABLE;
    }
    static CURRENT: std::sync::OnceLock<Signing> = std::sync::OnceLock::new();
    *CURRENT.get_or_init(|| match std::env::current_exe() {
        Ok(exe) => check(&assessed_path(&exe)),
        Err(_) => Signing::UNKNOWN,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ok(text: &str) -> Outcome {
        Outcome {
            success: true,
            text: text.to_owned(),
        }
    }
    fn failed(text: &str) -> Outcome {
        Outcome {
            success: false,
            text: text.to_owned(),
        }
    }

    const ADHOC: &str =
        "Executable=/Applications/OpenWorld Moments.app/Contents/MacOS/openworld-moments-desktop
Identifier=org.openworldmoments.desktop
Format=app bundle with Mach-O thin (arm64)
CodeDirectory v=20500 size=1234 flags=0x10002(adhoc,runtime) hashes=27+7 location=embedded
Signature=adhoc
Info.plist entries=20
TeamIdentifier=not set
Sealed Resources version=2 rules=13 files=1057
Internal requirements count=0 size=12
";
    const DEVELOPER_ID: &str =
        "Executable=/Applications/OpenWorld Moments.app/Contents/MacOS/openworld-moments-desktop
Identifier=org.openworldmoments.desktop
CodeDirectory v=20500 size=1234 flags=0x10000(runtime) hashes=27+7 location=embedded
Signature size=9046
Authority=Developer ID Application: Example Person (AB12CD34EF)
Authority=Developer ID Certification Authority
Authority=Apple Root CA
Timestamp=28 Nov 2026 at 10:00:00
TeamIdentifier=AB12CD34EF
";
    const LINKER: &str = "Executable=/repo/target/debug/openworld-moments-desktop
Identifier=openworld_moments_desktop-1234
CodeDirectory v=20400 size=999 flags=0x20002(adhoc,linker-signed) hashes=30+0 location=embedded
Signature=adhoc
";
    const ACCEPTED: &str = "/Applications/OpenWorld Moments.app: accepted\nsource=Notarized Developer ID\norigin=Developer ID Application: Example Person (AB12CD34EF)\n";
    const UNNOTARIZED: &str =
        "/Applications/OpenWorld Moments.app: rejected\nsource=Unnotarized Developer ID\n";
    const REJECTED: &str = "/Applications/OpenWorld Moments.app: rejected\n";

    #[test]
    fn ad_hoc_hardened_bundle_is_reported_as_ad_hoc_and_rejected() {
        let s = classify(Some(&ok(ADHOC)), Some(&failed(REJECTED)));
        assert_eq!(
            s,
            Signing {
                state: State::Adhoc,
                hardened_runtime: Some(true),
                gatekeeper: Gatekeeper::Rejected
            }
        );
    }

    #[test]
    fn development_binary_is_linker_signed_ad_hoc_without_hardened_runtime() {
        let s = classify(Some(&ok(LINKER)), Some(&failed(REJECTED)));
        assert_eq!((s.state, s.hardened_runtime), (State::Adhoc, Some(false)));
    }

    #[test]
    fn notarized_needs_gatekeeper_to_accept_it_as_notarized() {
        let s = classify(Some(&ok(DEVELOPER_ID)), Some(&ok(ACCEPTED)));
        assert_eq!(
            s,
            Signing {
                state: State::Notarized,
                hardened_runtime: Some(true),
                gatekeeper: Gatekeeper::Accepted
            }
        );
    }

    #[test]
    fn developer_id_without_a_notarization_is_never_called_notarized() {
        for spctl in [
            Some(failed(UNNOTARIZED)),
            None,
            Some(failed("")),
            // Accepted, but not as notarized (an older policy or another source).
            Some(ok("/x.app: accepted\nsource=Developer ID\n")),
        ] {
            let s = classify(Some(&ok(DEVELOPER_ID)), spctl.as_ref());
            assert_eq!(s.state, State::DeveloperId, "{spctl:?}");
        }
    }

    #[test]
    fn assessments_turned_off_are_not_an_acceptance() {
        let overridden = ok("/x.app: accepted\noverride=security disabled\n");
        assert_eq!(gatekeeper(Some(&overridden)), Gatekeeper::Unknown);
        let s = classify(Some(&ok(DEVELOPER_ID)), Some(&overridden));
        assert_eq!(
            (s.state, s.gatekeeper),
            (State::DeveloperId, Gatekeeper::Unknown)
        );
        // Even a garbled acceptance never pairs with an ad hoc signature.
        let s = classify(Some(&ok(ADHOC)), Some(&ok("/x.app: accepted\n")));
        assert_eq!((s.state, s.gatekeeper), (State::Adhoc, Gatekeeper::Unknown));
    }

    #[test]
    fn unsigned_code_and_tool_failures() {
        let unsigned = failed("/x.app: code object is not signed at all\n");
        let s = classify(Some(&unsigned), Some(&failed(REJECTED)));
        assert_eq!(
            s,
            Signing {
                state: State::Unsigned,
                hardened_runtime: Some(false),
                gatekeeper: Gatekeeper::Rejected
            }
        );
        // codesign did not run, timed out, or failed for another reason.
        assert_eq!(classify(None, Some(&ok(ACCEPTED))), Signing::UNKNOWN);
        assert_eq!(
            classify(Some(&failed("/x.app: No such file or directory")), None),
            Signing::UNKNOWN
        );
        // Signed, but with no recognisable details.
        let s = classify(Some(&ok("Identifier=x\n")), None);
        assert_eq!(s, Signing::UNKNOWN);
    }

    #[test]
    fn other_identities_are_other() {
        let text = DEVELOPER_ID.replace(
            "Developer ID Application: Example Person",
            "Apple Development: Example Person",
        );
        let s = classify(Some(&ok(&text)), Some(&failed(REJECTED)));
        assert_eq!(s.state, State::Other);
    }

    #[test]
    fn the_report_never_carries_names_teams_or_paths() {
        let s = classify(Some(&ok(DEVELOPER_ID)), Some(&ok(ACCEPTED)));
        let json = serde_json::to_string(&s).unwrap();
        assert_eq!(
            json,
            r#"{"state":"notarized","hardened_runtime":true,"gatekeeper":"accepted"}"#
        );
        for secret in ["Example", "AB12CD34EF", "/Applications"] {
            assert!(!json.contains(secret), "{json}");
        }
        assert_eq!(
            serde_json::to_value(Signing::NOT_APPLICABLE).unwrap(),
            serde_json::json!({"state":"not-applicable","hardened_runtime":null,"gatekeeper":"not-applicable"})
        );
    }

    #[test]
    fn the_bundle_is_assessed_rather_than_its_executable() {
        assert_eq!(
            assessed_path(Path::new(
                "/Applications/OpenWorld Moments.app/Contents/MacOS/openworld-moments-desktop"
            )),
            Path::new("/Applications/OpenWorld Moments.app")
        );
        for bare in [
            "/repo/target/debug/openworld-moments-desktop",
            "/x/Contents/MacOS/app",
            "/x.app/MacOS/app",
            "app",
        ] {
            assert_eq!(assessed_path(Path::new(bare)), Path::new(bare), "{bare}");
        }
    }

    #[test]
    fn other_platforms_are_not_checked() {
        assert_eq!(
            current(crate::platform::Family::Windows),
            Signing::NOT_APPLICABLE
        );
        assert_eq!(
            current(crate::platform::Family::Linux),
            Signing::NOT_APPLICABLE
        );
    }

    #[cfg(unix)]
    #[test]
    fn a_tool_that_hangs_is_stopped_and_reads_as_unknown() {
        let started = std::time::Instant::now();
        let outcome = run(
            "/bin/sleep",
            &[],
            Path::new("5"),
            Duration::from_millis(200),
        );
        assert!(outcome.is_none());
        assert!(started.elapsed() < Duration::from_secs(3));
        let missing = run("/nonexistent/tool", &[], Path::new("x"), TOOL_TIMEOUT);
        assert!(missing.is_none());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn this_test_binary_is_ad_hoc_signed_by_the_linker() {
        // Every arm64 (and modern x86_64) linker output carries an ad hoc signature.
        let exe = std::env::current_exe().unwrap();
        let s = check(&exe);
        assert!(matches!(s.state, State::Adhoc | State::Unsigned), "{s:?}");
        assert_ne!(s.gatekeeper, Gatekeeper::Accepted);
    }
}
