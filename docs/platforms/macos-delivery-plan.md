# macOS delivery plan

## Goal

Ship OpenWorld Moments as a normal, notarized macOS desktop application with the same core import-to-render workflow as Windows. The macOS build remains local-first, does not require a terminal, and does not require Rosetta for normal operation.

This plan extends the existing Windows-first roadmap without renumbering milestones already assigned or in progress. M32 remains the Windows public-alpha qualification gate. M33 through M39 add macOS support and conclude with a dual-platform release qualification.

## Supported matrix

| Dimension | Initial supported target |
|---|---|
| Operating system | macOS 14 Sonoma and newer supported releases |
| Apple Silicon | Native `aarch64` build; M1 or newer |
| Intel | Native `x86_64` build on Macs capable of running macOS 14+ |
| Distribution | Direct download from GitHub Releases |
| Package | Separate notarized DMG for each CPU architecture |
| Store | Mac App Store is not required for the initial release |
| Processing | Fully local after optional dependencies are installed |

Separate native DMGs are deliberate. They avoid requiring Rosetta and avoid the extra failure modes of merging the Tauri host, Python worker, FFmpeg, and every native model dependency into one universal binary. A universal DMG can be evaluated after both native packages are reliable.

M33 verified the floor and the build matrix: see the [OS floor record](./macos-os-floor.md), [ADR-0008](../architecture/adr/0008-macos-distribution.md), the [platform interfaces](./platform-interfaces.md) and the [development shell guide](./macos-development-shell.md). M34 bundles the worker
and media tools: see [macOS packaging](./macos-packaging.md).

The minimum macOS version is a release policy, not a hard-coded assumption. M33 must verify it against Tauri, WebKit, Rust, the packaged Python runtime, FFmpeg, ONNX Runtime, OCR, and transcription dependencies before locking the value. Raising the floor requires a documented compatibility decision.

## Distribution decision

The initial macOS release will use a Developer ID-signed and Apple-notarized DMG distributed outside the Mac App Store.

The alpha will use Hardened Runtime and narrowly reviewed entitlements. It will not enable App Sandbox initially because the application must launch signed media sidecars, watch user-selected folders over time, process large external files, and temporarily accept phone uploads on the local network. App Sandbox and Mac App Store distribution may be evaluated later as a separate product decision.

This choice does not permit broad, silent file access. Import and watched-folder access must originate from an explicit user selection, application-owned data must use standard macOS directories, and the UI must explain any permission or firewall prompt.

## Required external prerequisite

A distributable macOS release cannot be completed using source code alone. Before M37 begins, the maintainer must provide CI with:

- Active Apple Developer Program membership.
- A Developer ID Application certificate exported for protected CI use.
- An App Store Connect API key or other supported notarization credentials.
- The Apple team, issuer, and key identifiers required by the release workflow.
- Access to at least one clean Apple Silicon Mac and one clean Intel Mac for final validation.

Secrets must never be committed or printed. If these prerequisites are unavailable, contributors may produce unsigned development bundles, but M37 and M39 cannot be marked complete and the project must not describe the download as a supported macOS release.

## macOS application layout

```text
OpenWorld Moments.app/
└── Contents/
    ├── MacOS/                 # Tauri host and executable sidecars
    ├── Frameworks/            # packaged runtime libraries when required
    └── Resources/             # UI assets, schemas, notices, profiles
```

The exact sidecar placement is controlled by the verified Tauri bundler configuration rather than by runtime path guesses. Every executable, dynamic library, framework, and nested helper must be architecture-correct, included in the SBOM, signed in the proper order, and covered by the outer notarized artifact.

Expected release assets:

```text
OpenWorld-Moments_<version>_macOS_arm64.dmg
OpenWorld-Moments_<version>_macOS_x86_64.dmg
OpenWorld-Moments_<version>_Windows_x64.exe
checksums.txt
sbom-<platform>-<architecture>.cdx.json
THIRD_PARTY_NOTICES.txt
```

## Platform integration requirements

### Files and application data

- Store the canonical library and configuration under `~/Library/Application Support/OpenWorld Moments/` by default.
- Store disposable proxies, thumbnails, and analysis caches under `~/Library/Caches/OpenWorld Moments/`.
- Store diagnostic logs under `~/Library/Logs/OpenWorld Moments/` with redaction and retention limits.
- Use native file/folder selection for imports, watched folders, exports, and library relocation.
- Detect unavailable external drives, stale watched folders, cloud placeholders, and permission revocation without deleting records.
- Never assume a shell-initialized `PATH`; all shipped sidecars must be resolved from the app bundle.

### Processes and security

- Launch only the architecture-matched, bundled worker and media tools.
- Bind desktop IPC to loopback with the same per-launch authentication used on Windows.
- Keep phone upload disabled by default and explain the macOS firewall/local-network prompt before enabling it.
- Preserve cancellation and cleanup across `SIGTERM`, application quit, sleep, and wake.
- Use Keychain through the host abstraction for secrets that must persist.
- Never remove quarantine metadata or instruct users to bypass Gatekeeper.

### Media behavior

- CPU decoding and encoding remain the correctness fallback.
- Probe VideoToolbox before advertising it and expose fallback reasons.
- Validate H.264, HEVC, variable-frame-rate, rotation, no-audio, and common HDR inputs.
- Prevent HDR-to-SDR exports from producing washed-out or incorrectly tagged output.
- Require preview/render crop parity for both horizontal and vertical projects.

### User experience

- Provide normal macOS menus, `Command` shortcuts, Finder reveal actions, and application lifecycle behavior.
- Explain architecture choice on the download page and in troubleshooting.
- Test keyboard navigation with macOS conventions.
- Test the complete workflow with VoiceOver, Voice Control, increased contrast, reduced motion, and 200% interface scaling.
- Make permission recovery actionable without asking users to disable system protections.

## CI and test strategy

The macOS lane uses pinned GitHub-hosted Apple Silicon and Intel runner labels rather than `macos-latest` for release jobs. Fast unit/contract tests may use a smaller matrix, but release candidates must build both native architectures.

CI proves compilation, contracts, unit tests, architecture correctness, dependency inventory, and deterministic packaging inputs. CI alone does not prove GUI behavior, hardware acceleration, Gatekeeper behavior, sleep/wake recovery, or watched-folder behavior. Those require physical clean-machine validation.

The qualification matrix must include:

| Journey | Apple Silicon | Intel | Windows x64 |
|---|---:|---:|---:|
| Install and first launch | Required | Required | Required |
| Manual/reference import | Required | Required | Required |
| Managed-copy import | Required | Required | Required |
| Watched folder restart | Required | Required | Required |
| Phone QR upload | Required | Required | Required |
| Worker crash/restart | Required | Required | Required |
| Horizontal CPU render | Required | Required | Required |
| Vertical CPU render | Required | Required | Required |
| Hardware render/fallback | Required | Required | Required |
| VoiceOver keyboard path | Required | Smoke | N/A |
| Upgrade and uninstall | Required | Required | Required |
| Gatekeeper/notarization | Required | Required | N/A |

## Milestone sequence

| Milestone | Result |
|---|---|
| M33 | macOS platform contract, native build matrix, and CI foundation |
| M34 | Architecture-specific worker, FFmpeg, and optional dependency packaging |
| M35 | File access, watched folders, application directories, sleep/wake, and LAN permissions |
| M36 | Playback, VideoToolbox, HDR/proxy, and render parity |
| M37 | Signed, hardened, notarized, stapled Apple Silicon and Intel DMGs |
| M38 | macOS onboarding, menus, accessibility, diagnostics, and documentation |
| M39 | Cross-platform release candidate and clean-machine qualification |

M33–M36 can begin only after their declared dependencies are merged. M37 requires the signing prerequisites above. M39 is the first milestone after which the repository may claim that the downloadable application officially supports both Windows and macOS.

## macOS definition of done

macOS support is complete only when:

- A nontechnical user selects the correct DMG, installs the app, and launches it without Terminal or a security bypass.
- Both Apple Silicon and Intel packages pass Gatekeeper verification and contain only matching native executables.
- The full import, reconstruction, review, edit, horizontal render, and vertical render journey succeeds on clean Macs.
- Watched folders and imported files survive restart, permission changes, drive disconnect/reconnect, and sleep/wake safely.
- CPU output is correct and VideoToolbox either passes capability tests or visibly falls back.
- The app does not depend on Homebrew, a system Python, a shell `PATH`, or separately installed FFmpeg.
- VoiceOver and keyboard users can complete the primary workflow.
- Upgrade and uninstall preserve user libraries unless the user explicitly requests deletion.
- Release assets include checksums, SBOMs, third-party notices, notarization evidence, compatibility results, and known limitations.

## Primary references

- Tauri distribution overview: <https://v2.tauri.app/distribute/>
- Tauri macOS signing and notarization: <https://v2.tauri.app/distribute/sign/macos/>
- Tauri DMG packaging: <https://v2.tauri.app/distribute/dmg/>
- Tauri sidecar packaging: <https://v2.tauri.app/develop/sidecar/>
- Apple notarization requirements: <https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>
- Apple Developer ID certificates: <https://developer.apple.com/help/account/certificates/create-developer-id-certificates>
- Apple packaging guidance: <https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution>
- Apple accessibility testing: <https://developer.apple.com/documentation/accessibility/performing-accessibility-testing-for-your-app>
- GitHub-hosted runner reference: <https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job>
