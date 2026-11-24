# macOS signing, notarization and DMGs (M37)

Status: **implemented, not yet released.** Every step that doesn't need Apple
credentials is built and checked in CI on both architectures. The project has no Apple
Developer Program membership yet, so no build has been signed with Developer ID or
notarized. Until that happens, macOS is **not a supported release**: CI's DMGs are
signed ad hoc, Gatekeeper rejects them, and they must not be published or handed to
users. See [What is left](#what-is-left).

Related: [ADR-0008](../architecture/adr/0008-macos-distribution.md) (separate native
DMGs, direct download, Hardened Runtime, no App Sandbox),
[macOS packaging](./macos-packaging.md) (what is in the runtime) and the
[delivery plan](./macos-delivery-plan.md#required-external-prerequisite).

## What gets built

One DMG per CPU architecture, built on a native runner of that architecture:

| | Release (Developer ID) | Today in CI (no credentials) |
|---|---|---|
| File | `OpenWorld-Moments_<version>_macOS_arm64.dmg`, `..._macOS_x86_64.dmg` | `OpenWorld-Moments_<version>+<commit>_macOS_<arch>_adhoc-unnotarized.dmg` |
| Signature | Developer ID Application, secure timestamp | Ad hoc (`codesign -s -`) |
| Hardened Runtime | On for every executable and library | On |
| Notarized and stapled | App and DMG | SKIPPED |
| Gatekeeper | Accepted (`source=Notarized Developer ID`) | Rejected (expected) |
| Next to it | `sbom-macos-<arch>.cdx.json`, `checksums.txt`, `THIRD_PARTY_NOTICES.txt`, `signing-report-<arch>.json`, `dmg-check-<arch>.json`, `notarization-*.json` | The same, without notarization logs |

The ad hoc name carries the commit and `_adhoc-unnotarized`, so it can't pass for a
release asset.

The DMG holds only `OpenWorld Moments.app` and an `Applications` link (`hdiutil`,
HFS+, UDZO, volume `OpenWorld Moments`). DMGs aren't bit-for-bit reproducible
(`hdiutil` writes timestamps). Reproducibility is claimed for the inputs: the frozen
runtime inventory, the SBOM and the CI run that built the app.

### Bundle identity and metadata

| Key | Value | Source |
|---|---|---|
| `CFBundleIdentifier` | `org.openworldmoments.desktop`, **never changes**. macOS keys permissions, Keychain items and preferences to it | `tauri.conf.json` |
| `CFBundleShortVersionString` / `CFBundleVersion` | `0.1.0-alpha.37`. It must equal the runtime inventory's `application`, or packaging stops | `tauri.macos-packaged.conf.json`, `scripts/macos/freeze-worker.py` |
| `LSMinimumSystemVersion` | `14.0` | `tauri.macos.conf.json` |
| `LSApplicationCategoryType` | `public.app-category.video` | `tauri.macos.conf.json` (`category`) |
| `NSHumanReadableCopyright` | `© OpenWorld Moments contributors. AGPL-3.0-or-later.` | `tauri.macos.conf.json` |
| Icon | `icon.icns` | `tauri.conf.json` |
| `NSLocalNetworkUsageDescription` | Phone-upload explanation (M35) | `Info.plist` |

`sign-and-package.py` checks the identifier, icon, category, copyright and version
before it signs anything.

### Where the code lives

The runtime stays in `Contents/Resources/runtime` (M34). It isn't moved to
`Frameworks/` or `Helpers/`. Every Mach-O file there is signed on its own, as nested
code, before the bundle. The bundle's seal then covers those files as resources, and
`codesign --verify --deep --strict` checks the whole tree. Moving the runtime would
change the host's worker path (contract 1.26) and M34's inventory layout, and signing
doesn't require it. Notarization checks every binary in the submission wherever it
lives. If Apple ever rejects this layout, the fix is a relocation in a separate change.
See [Known limitations](#known-limitations).

## Entitlements

Every executable is signed with the Hardened Runtime. The reviewed entitlement files are:

| File | Applied to | Keys |
|---|---|---|
| [`apps/desktop/src-tauri/macos/entitlements.plist`](../../apps/desktop/src-tauri/macos/entitlements.plist) | The app (Tauri host), `owm-worker`, `ffmpeg`, `ffprobe` in Developer ID builds; the app, `ffmpeg` and `ffprobe` in ad hoc builds | **None** |
| [`apps/desktop/src-tauri/macos/entitlements-adhoc.plist`](../../apps/desktop/src-tauri/macos/entitlements-adhoc.plist) | **Ad hoc builds only**, and only `Resources/runtime/owm-worker` | `com.apple.security.cs.disable-library-validation` |

Libraries and Python extension modules get no entitlements (they have no effect on
them).

Each key was reviewed and refused:

| Entitlement | Decision |
|---|---|
| `com.apple.security.app-sandbox` | Not used. ADR-0008: no App Sandbox for the alpha |
| `com.apple.security.get-task-allow` | Forbidden. It allows debugger attachment, and notarization rejects it |
| `com.apple.security.cs.allow-jit`, `allow-unsigned-executable-memory`, `disable-executable-page-protection` | Not needed. WKWebView's JavaScript JIT runs in Apple's own WebContent process. FFmpeg, the frozen CPython and our ctypes use (a single `getxattr` call, no callbacks) don't generate code |
| `com.apple.security.cs.disable-library-validation` | Not needed with Developer ID, because every bundled library is signed by the same team. Ad hoc signatures have no Team ID, so library validation would stop the worker loading its own `libpython3.12.dylib`. That was observed: dyld reported "mapping process and mapped file (non-platform) have different Team IDs". Ad hoc builds therefore use the exception for the worker only. A Developer ID build that carries it fails verification |
| `com.apple.security.cs.allow-dyld-environment-variables` | Forbidden. The host starts the worker with an explicit environment, and nothing depends on `DYLD_*` |
| `com.apple.security.network.*`, `files.*` | Only meaningful inside the App Sandbox |
| Camera, microphone, Apple Events, location | Not used |

To add a key, write its reason in this table and add it to `ALLOWED_ENTITLEMENTS` in
`scripts/macos/sign-and-package.py`. Tests fail on any key that isn't in that list or
that is in the forbidden list, whether it appears in the file or in a signed binary.

## Signing order

`python3 scripts/macos/sign-and-package.py package --arch <arch>` signs inside out.
Every command is an argument array:

1. **Audit:** the architecture audit (`build-shell.py`), the bundle metadata and the
   entitlement files.
2. **Nested code, deepest first:** each Mach-O file under `Contents/` except the host
   executable, with `--options runtime`, a stable identifier
   (`org.openworldmoments.desktop.runtime.<name>`) and the timestamp (Developer ID).
   That covers:
   - the runtime's extension modules (`_internal/**.so`);
   - `libpython3.12.dylib`;
   - `tools/ffmpeg` and `tools/ffprobe`;
   - `owm-worker`;
   - any nested `.framework` or `.bundle` after its contents.

   Links are skipped (their target is signed).
3. **Re-hash `runtime/inventory.json`.** Signing rewrites those files, and the worker
   refuses a runtime whose hashes don't match (M34, `worker.bundle_corrupt`). The
   script refuses if anything other than signed code changed, or if a file appeared or
   disappeared.
4. **Sign the app bundle.** This also signs the Tauri host executable, with the
   entitlements.
5. **Verify:**
   - `codesign --verify --deep --strict`;
   - for every item: `codesign --display` for the identity, the Team ID, the timestamp
     and the `runtime` flag (no leftover `linker-signed`), and its entitlements;
   - the inventory hashes;
   - the architecture audit again.
6. **Notarize the app** (Developer ID only): zip it, submit it with
   `xcrun notarytool submit --wait`, fetch and inspect the log, then
   `xcrun stapler staple` and `validate`.
7. **Build and sign the DMG** (no Hardened Runtime option for a disk image).
8. **Notarize the DMG** (Developer ID only): submit, inspect, staple and validate.
9. **Gatekeeper:**
   - `spctl --assess --type execute` on the app;
   - `spctl --assess --type open --context context:primary-signature` on the DMG.

Then `verify-dmg` (install, replace, tamper and uninstall checks), the SBOM with the
DMG hash, `checksums`, `verify_sbom.py --release-dir` and the release-folder secret
scan.

## CI

### Every pull request and push (`ci.yml`, job `macOS build (<arch>)`)

The job runs on `macos-15` (Apple Silicon) and `macos-15-intel`. After the existing
build, smoke, media and SBOM steps, it:

1. runs `check-credentials`, which prints `signing mode: adhoc` and the SKIPPED notice.
   Pull requests never see Apple secrets;
2. runs `package --mode adhoc`: signs inside out, builds and signs the DMG;
3. runs `runtime-smoke.py` against the **signed** runtime (Hardened Runtime, re-hashed
   inventory);
4. runs `verify-dmg --expect adhoc`, which checks:
   - `hdiutil verify` and the DMG signature;
   - that the DMG holds only the app and the `Applications` link;
   - a drag install into a temporary `Applications` folder, with
     `codesign --verify --deep --strict` and the architecture audit;
   - `--version-report` with a temporary `HOME`;
   - that replacing the app keeps a synthetic library;
   - that a tampered resource and an unsigned nested binary are both rejected;
   - that uninstalling keeps the library;
   - that Gatekeeper rejects the app;
5. writes the SBOM (with the DMG's SHA-256) and `checksums.txt`, verifies both against
   the signed runtime, and scans the release folder for secrets and paths. There are no
   exceptions ([`security/artifact-scan-exceptions-macos-release.json`](../../security/artifact-scan-exceptions-macos-release.json));
6. uploads everything with the unsigned zip as `macOS-<arch>-unsigned-dev`.

### Release signing (`macos-release.yml`, manual)

A maintainer starts **macOS release signing** (`workflow_dispatch`) with the ID of a
successful CI run on `main`. For each architecture, on its native runner:

1. It checks that the run used `ci.yml`, ran on `main` and succeeded, then checks out
   that commit.
2. `check-credentials` runs in the protected `macos-release` environment. With no
   secrets, the job ends with a **"macOS notarization SKIPPED"** notice and a job
   summary, and signs and uploads nothing. With some but not all of them, it fails and
   names the missing variables, never their values.
3. It downloads that run's **unsigned** zip and checks its SHA-256 against
   `SHA256SUMS.txt`. These are the bits CI built and tested.
4. `package --mode developer-id --require-notarized` runs. The secrets are passed only
   to this step and to step 2.
5. `runtime-smoke.py` runs against the Developer ID runtime, which proves library
   validation passes with a Team ID.
6. `verify-dmg --expect notarized` adds a stapled-ticket check, and requires Gatekeeper
   to accept the installed app.
7. The SBOM, checksums, SBOM verification and secret scan run, then a build-provenance
   attestation is made.
8. The release folder is uploaded as `macOS-<arch>-notarized-release-candidate`
   (90 days).

It publishes nothing; GitHub Releases are M39. **The release gate:**
`--require-notarized` exits 3 unless the DMG is Developer ID signed, notarized
(Accepted with **no** issues in the log), stapled, and accepted by Gatekeeper. Without
credentials it exits 3 before doing anything. A notarization failure, a log with
warnings, a stapling failure or a Gatekeeper rejection fails the job before anything
is uploaded.

### Secrets

These are the secrets of the `macos-release` environment (names only; values never go
in the repository, logs or artifacts):

| Secret | What it holds |
|---|---|
| `MACOS_CERTIFICATE_P12_BASE64` | The Developer ID Application certificate and its private key, exported as `.p12`, base64-encoded |
| `MACOS_CERTIFICATE_PASSWORD` | The `.p12` export password |
| `APPLE_TEAM_ID` | The 10-character team ID (public: it appears in every signature) |
| `APPLE_API_KEY_ID` | App Store Connect API key ID, used for notarization |
| `APPLE_API_ISSUER_ID` | App Store Connect issuer ID (UUID) |
| `APPLE_API_KEY_P8_BASE64` | The `AuthKey_<id>.p8` private key, base64-encoded |

How they are protected:

- **Environment:** the secrets live in the GitHub environment `macos-release`, with a
  deployment branch rule for `main` only and a required reviewer recommended. They are
  not repository secrets, and `ci.yml` never references them (a test enforces this).
- **Steps:** only the two signing steps receive them, never third-party actions such as
  the cache or uv setup.
- **Keychain:**
  - the certificate is imported into a temporary keychain with a random password,
    restricted to `codesign`;
  - it is added to the search list, then removed and deleted afterwards whatever
    happens, along with the decoded `.p12`;
  - a final `always()` step deletes any `owm-signing` keychain that is left over.
- **API key:** the `.p8` is written mode 0600 into a temporary folder and deleted after
  each `notarytool` call.
- **Logs:** a command that carries a secret runs through a separate runner entry
  point, `secret(label, args)`, with a literal label. That path never logs or reports
  anything derived from the arguments: its log line and any error use the label alone
  (`security import [arguments withheld]`). All program output is scrubbed of every
  secret value, including the decoded key's lines. Tests cover partial and malformed
  credentials, redaction, and the absence of secrets from logs, errors and every output
  file.
- **Artifacts:** the release folder is scanned for secrets with no exceptions.
  Notarization logs hold Apple's submission ID, file paths inside the submission and
  cdhashes, nothing secret.

### Where to find the evidence

- `signing-report-<arch>.json` holds:
  - the mode, the identity and the bundle ID;
  - the signing order and the entitlement file hash;
  - the number of re-hashed files;
  - the notarization submission IDs and log file names;
  - stapling, Gatekeeper, the DMG name and SHA-256, and whether it is `publishable`.
- `notarization-app-<arch>.json` and `notarization-dmg-<arch>.json` are Apple's
  notarization logs.
- `dmg-check-<arch>.json` holds the install, replace, tamper and uninstall results and
  the Gatekeeper result.
- `checksums.txt` and `sbom-macos-<arch>.cdx.json`.

## Maintainer setup

This is the remaining external prerequisite; it needs the account holder:

1. **Enroll** in the Apple Developer Program (as an organization or an individual).
   Accept the latest Program License Agreement in App Store Connect. A pending
   agreement makes `notarytool` fail with HTTP 403.
2. **Developer ID Application certificate:**
   - create it in Certificates, Identifiers & Profiles (account holder role) from a CSR
     made in Keychain Access on a trusted Mac;
   - export the certificate *with* its private key as `.p12` with a strong password.
3. **Notarization key:** in App Store Connect → Users and Access → Integrations → Team
   Keys, create a key with the *Developer* role. Download `AuthKey_<id>.p8`; Apple
   allows only one download. Note the key ID and the issuer ID.
4. **Environment:** in the GitHub repository settings, create the environment
   `macos-release` with deployment branches limited to `main` and a required reviewer.
5. **Secrets:** add the six secrets above to that environment. To make the base64
   values on the Mac without echoing them:

   ```bash
   base64 -i DeveloperID.p12 | pbcopy
   ```

   ```bash
   base64 -i AuthKey_ABC1234567.p8 | pbcopy
   ```

   Paste each one into its secret, then delete the local files or keep them only in a
   password manager.
6. **Run it:** after a green CI run on `main`, start *macOS release signing* with that
   run's ID. Download both `macOS-<arch>-notarized-release-candidate` artifacts.
7. **Clean-machine check** on a Mac with no development tools or previous build, for
   each architecture. Download the DMG through a browser so it is quarantined, then:
   - check it against `checksums.txt`;
   - open the DMG and drag the app to Applications;
   - launch it from Launchpad or Finder with no Terminal and no security prompt beyond
     the normal "downloaded from the internet" confirmation;
   - confirm the system check shows the right architecture and "Packaged runtime";
   - quit, install the next build over it, and confirm the library is still there;
   - uninstall as below.

   Record the results in the M37 handoff.

## Manual verification

On any Mac, for a downloaded release DMG:

```bash
shasum -a 256 -c checksums.txt --ignore-missing
```

```bash
codesign --verify --strict --verbose=2 OpenWorld-Moments_0.1.0-alpha.37_macOS_arm64.dmg
```

```bash
xcrun stapler validate OpenWorld-Moments_0.1.0-alpha.37_macOS_arm64.dmg
```

```bash
spctl --assess --type open --context context:primary-signature --verbose=4 OpenWorld-Moments_0.1.0-alpha.37_macOS_arm64.dmg
```

After installing:

```bash
codesign --verify --deep --strict --verbose=2 "/Applications/OpenWorld Moments.app"
```

```bash
spctl --assess --type execute --verbose=4 "/Applications/OpenWorld Moments.app"
```

```bash
syspolicy_check distribution "/Applications/OpenWorld Moments.app"
```

```bash
lipo -archs "/Applications/OpenWorld Moments.app/Contents/MacOS/openworld-moments-desktop"
```

What each one should show:

- `spctl` should print `accepted` and `source=Notarized Developer ID`;
- `syspolicy_check` should report no errors;
- `lipo` should print only `arm64` (or only `x86_64` for the Intel DMG).

`python3 scripts/macos/sign-and-package.py verify-dmg <dmg> --arch <arch> --expect notarized`
runs the automated checks against a copy and never touches `/Applications` or your
library.

Never remove the quarantine attribute (`xattr -d com.apple.quarantine`) or tell users
to bypass Gatekeeper. If Gatekeeper rejects a release, the release is broken.

## Install, upgrade, replace and uninstall

- **Install:** open the DMG and drag *OpenWorld Moments* onto *Applications*. Pick the
  DMG that matches your Mac: `arm64` for Apple Silicon, `x86_64` for Intel. The Intel
  build under Rosetta works, but it says so in the system check.
- **Upgrade or replace:** quit the app, then drag the new version onto *Applications*
  and choose *Replace*. The bundle holds no user data, so replacing it never touches
  your library. A different architecture's DMG replaces the app the same way. The
  bundle identifier never changes, so macOS keeps folder permissions, Keychain entries
  and preferences. CI checks this (`replace_keeps_library`).
- **Downgrade:** the same as an upgrade. M02's migrations back up the database before
  any upgrade, and an older app refuses a newer library rather than damaging it.
- **Uninstall the app:** quit it, then move `/Applications/OpenWorld Moments.app` to
  the Trash. Your library, settings and logs stay (`uninstall_keeps_library`).
- **Remove your data too** (explicit and permanent). This deletes your library,
  project edits, settings and caches:
  - `~/Library/Application Support/OpenWorld Moments/`: the library database, settings
    and managed copies of imported clips. Delete this only if you want to lose them.
  - `~/Library/Caches/OpenWorld Moments/`: proxies, thumbnails and analysis caches.
    Always safe to delete; they are rebuilt.
  - `~/Library/Logs/OpenWorld Moments/`: diagnostic logs.
  - A library you moved elsewhere stays wherever you put it.

  Original clips that were imported by reference are never inside these folders and
  are never deleted.

## Rotation

| Event | What to do |
|---|---|
| **The API key leaked or a person left** | Revoke the key in App Store Connect at once. Create a new one, replace `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID` (if the issuer changed) and `APPLE_API_KEY_P8_BASE64`. Signed releases stay valid |
| **The API key expired or was refused** (HTTP 401) | The release job fails with "Apple refused the App Store Connect API key". Rotate as above |
| **The certificate is expiring** (5-year life) | Create a new Developer ID Application certificate before expiry and replace `MACOS_CERTIFICATE_P12_BASE64` and `MACOS_CERTIFICATE_PASSWORD`. Signed and notarized releases keep working after expiry, thanks to the secure timestamp |
| **The certificate's private key leaked** | Ask Apple (Developer Support) to revoke the certificate. Revocation can invalidate software already signed with it, so re-sign and re-notarize every supported release with a new certificate, publish the replacements and say so in the release notes |
| **The `.p12` password leaked** | Treat it as a leaked private key if the `.p12` may have leaked too. Otherwise re-export with a new password |
| **The environment changed** | Review `macos-release` reviewers and branch rules whenever maintainers change |

## Release recovery

- **Notarization rejected or issues listed:** read
  `notarization-<kind>-<arch>.json`; each issue has a path and a message. Fix the cause
  (usually an unsigned or wrongly signed nested binary, or a missing timestamp), make a
  new CI run and sign again. Never publish a DMG from a failed run.
- **Stapling failed** (Apple's ticket service was slow): run the job again. The gate
  stops anything from being uploaded.
- **A published DMG is broken:** withdraw the asset, fix it, release a new version
  number, and replace the asset and `checksums.txt` together, so hashes and SBOMs stay
  traceable.

## Local evidence (Apple Silicon, ad hoc)

Apple M4, macOS 26.6.2, 23 November 2026, commit `ccb1b79` plus this branch. The
runtime was re-frozen as `0.1.0-alpha.37`, then the app was built with `build-shell.py`
and packaged with `package --mode adhoc`:

| Check | Result |
|---|---|
| Signing order | 10 items: 5 extension modules, `libpython3.12.dylib`, `ffmpeg`, `ffprobe`, `owm-worker`, then the app. 9 inventory entries re-hashed |
| `codesign --verify --deep --strict` (built, mounted and installed app) | `valid on disk`, `satisfies its Designated Requirement` |
| Every nested item | `flags=0x10002(adhoc,runtime)`, `Signature=adhoc`, identifiers `org.openworldmoments.desktop.runtime.*` |
| Worker without the ad hoc exception | Refused by library validation ("different Team IDs"); this is why the exception exists |
| `runtime-smoke.py` on the signed runtime | Passed: doctor, import, CPU render, cancellation, missing tool and corrupt tool (exit 3 in 1.9 s) |
| `verify-dmg --expect adhoc` | Passed: replace and uninstall keep the library, the tampered resource and the unsigned nested binary are rejected, and the version report shows `aarch64-apple-darwin`, release, bundled worker |
| DMG mounted | Contains only `OpenWorld Moments.app` and `Applications -> /Applications` |
| App launched from the DMG copy (temporary `HOME`) | The host started `Resources/runtime/owm-worker` as its child, the worker reported `worker ready` on loopback, the library was created under the temporary `~/Library/Application Support/OpenWorld Moments/`, and quitting stopped both processes |
| `spctl --assess` app and DMG | **rejected**. Expected: ad hoc and not notarized |
| `syspolicy_check distribution` | "Adhoc Signed App" (warning) and "Notary Ticket Missing" (fatal). Expected |
| SBOM | 1,057 files, 320 libraries, DMG hash recorded; `verify_sbom.py --release-dir` passed |
| Release-folder secret scan | 0 findings |
| DMG | 45.3 MiB (`OpenWorld-Moments_0.1.0-alpha.37+ccb1b79_macOS_arm64_adhoc-unnotarized.dmg`) |

## What is left

M37 stays **In progress** until:

1. the maintainer completes [Maintainer setup](#maintainer-setup) steps 1–5: enroll,
   create the certificate and API key, then create the `macos-release` environment
   with the six secrets;
2. a *macOS release signing* run succeeds for both architectures: Developer ID
   signatures, notarization Accepted with no issues, tickets stapled, Gatekeeper
   accepted, and the SBOM and checksums verified;
3. the clean-machine Gatekeeper, install, upgrade and uninstall checks pass on an Apple
   Silicon Mac and an Intel Mac (step 7), with the results and artifact hashes recorded
   in the handoff.

## Known limitations

- **No Developer ID or notarization run yet.** That path is covered only by tests with
  faked Apple tools: rejected and warning logs, an expired key, the order of steps,
  cleanup and redaction. `macos-release.yml` can only be started once it is on `main`.
- **The runtime stays in `Resources/`.** This is supported by `codesign` and checked by
  `--verify --deep --strict`, but no Developer ID notarization has run against it yet.
- **GPL source offer:** the runtime notices promise FFmpeg and x264 sources "with
  release builds". The macOS release folder doesn't include those archives yet; M39
  must attach them, as Windows' `artifacts.py` does.
- **The Intel lane** is checked by CI only: no physical Intel Mac yet (M40 and M39).
- **No universal DMG and no automatic updater**, by design (ADR-0008).
