# ADR-0008: macOS distribution: separate native DMGs, direct download, Hardened Runtime, no App Sandbox

- Status: Proposed in M33 (accepted by maintainer merge)
- Date: 2026-11-11
- Milestone: M33
- Deciders: project maintainers

## Context

Specification §28 and the [macOS delivery plan](../../platforms/macos-delivery-plan.md)
call for a macOS release that a nontechnical user installs without Terminal, Rosetta or
a Gatekeeper bypass, on Apple Silicon and on supported Intel Macs. The app is a Tauri
host that launches a frozen Python worker and FFmpeg sidecars (M34), watches folders the
user picked over long periods (M35), processes large external files, and briefly runs a
LAN upload gateway for phone transfer (M10).

M33 has to fix four choices before the platform work in M34–M37 builds on them:
how many packages, how they are distributed, which code-signing runtime they use, and
whether the App Sandbox is on.

## Decision

1. **Two native packages, one per CPU architecture.** `aarch64-apple-darwin` for Apple
   Silicon and `x86_64-apple-darwin` for Intel, each with architecture-matched sidecars.
   Asset names: `OpenWorld-Moments_<version>_macOS_arm64.dmg` and
   `OpenWorld-Moments_<version>_macOS_x86_64.dmg`. M33 development shells follow the same
   scheme with an `_unsigned-dev.zip` suffix.
2. **Direct download from GitHub Releases**, outside the Mac App Store.
3. **Developer ID signing with Hardened Runtime and notarization** (M37), with a
   reviewed, minimal entitlement list. M33 shells are unsigned (linker ad-hoc signature
   only) and are development artifacts.
4. **No App Sandbox in the initial release.** File access still starts only from a
   user's explicit selection; application data uses the standard macOS folders
   (`~/Library/Application Support|Caches|Logs/OpenWorld Moments`).
5. **macOS 14 Sonoma is the floor** for both architectures, verified against the locked
   dependencies in [macos-os-floor.md](../../platforms/macos-os-floor.md). It is set
   once (`tauri.macos.conf.json`, `MACOSX_DEPLOYMENT_TARGET`, `platform::MACOS_MINIMUM`)
   and a test keeps the three equal.

## Consequences

- No Rosetta and no universal-binary merge of the host, frozen Python runtime, FFmpeg
  and every native model library; each package can be tested and verified as one
  architecture (`scripts/macos/macho.py` rejects universal or wrong-architecture
  Mach-O files).
- Users must pick the right download. The app detects an Intel build running under
  Rosetta and says so (`translated` in the platform report), and the download page and
  guides explain the choice (M38).
- CI builds and caches twice. GitHub's last Intel runner image (`macos-15-intel`) is
  supported until about August 2027, and Rust demoted `x86_64-apple-darwin` to Tier 2
  in 1.90; the Intel package has a planned end of life and needs revisiting before then.
- Without the App Sandbox, launching signed sidecars, long-lived watched folders and the
  temporary LAN gateway work without security-scoped bookmarks or temporary exceptions.
  The trade-off is a wider default reach, so explicit selection, Hardened Runtime,
  notarization and narrow entitlements carry the safety argument. A sandboxed or
  App Store build is a separate later decision.
- Signing and notarization need an Apple Developer Program membership and protected CI
  secrets before M37; until then macOS builds must not be described as supported.

## Alternatives considered

- **One universal DMG.** Simpler download, but doubles the size and multiplies failure
  modes in sidecar and native-library merging; it can be revisited once both native
  packages are reliable.
- **Apple Silicon only.** Drops Intel Macs that run macOS 14+, which the specification
  supports.
- **Mac App Store with App Sandbox.** Needs security-scoped bookmarks for every watched
  folder, sandbox-compatible sidecar launching and review of the LAN gateway; too much
  risk for the first release.
- **Homebrew cask or a system Python.** Requires a terminal or system packages, which the
  specification rules out for nontechnical users.
