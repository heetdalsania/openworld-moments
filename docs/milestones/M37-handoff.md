## Milestone handoff

- Milestone: M37 — macOS signing, notarization, and DMGs
- Outcome: **In progress. Not complete. Blocked on the external Apple Developer Program
  prerequisite** ([delivery plan](../platforms/macos-delivery-plan.md#required-external-prerequisite)).
  The maintainer deferred enrollment, so no Developer ID certificate or notarization
  credentials exist. Everything that doesn't need them is built and verified.
  - **Done and verified:**
    - separate native `arm64` and `x86_64` app bundles and architecture-labelled DMGs,
      built and checked on both native CI runners;
    - inside-out Hardened Runtime signing of the worker, libraries, FFmpeg, FFprobe,
      host, app and DMG;
    - reviewed minimum entitlements (none);
    - re-hashing of the runtime inventory after signing;
    - SBOM and checksums for each DMG;
    - install, replace, tamper and uninstall checks;
    - a protected release workflow that switches to Developer ID, `notarytool`, log
      inspection and `stapler` only when all six secrets are present. Without them it
      skips clearly and never fails open.
  - **Remaining before M37 can be marked Complete:**
    1. Enroll in the Apple Developer Program. Create a Developer ID Application
       certificate and an App Store Connect API key
       ([maintainer setup](../platforms/macos-signing.md#maintainer-setup)).
    2. Create the GitHub environment `macos-release` (deployment branches: `main`;
       required reviewer) with the secrets `MACOS_CERTIFICATE_P12_BASE64`,
       `MACOS_CERTIFICATE_PASSWORD`, `APPLE_TEAM_ID`, `APPLE_API_KEY_ID`,
       `APPLE_API_ISSUER_ID` and `APPLE_API_KEY_P8_BASE64`.
    3. Run **macOS release signing** (`.github/workflows/macos-release.yml`) with a green
       CI run ID on `main`, for both architectures, and record the notarization
       submission IDs and the DMG hashes.
    4. Do the Gatekeeper check and the install, launch, upgrade and uninstall runs on a
       clean Apple Silicon Mac and a clean Intel Mac from the downloaded
       (quarantined) DMGs, and record them here.
- Files and modules changed:
  - **New:**
    - `scripts/macos/sign-and-package.py`, with the commands `package`, `verify-dmg`,
      `checksums` and `check-credentials`;
    - `apps/desktop/src-tauri/macos/entitlements.plist` (empty) and
      `entitlements-adhoc.plist` (ad hoc only; library validation for the worker);
    - `.github/workflows/macos-release.yml`;
    - `security/artifact-scan-exceptions-macos-release.json` (no exceptions);
    - `services/media-worker/tests/test_macos_signing.py` (45 tests);
    - `docs/platforms/macos-signing.md`;
    - this handoff.
  - **Changed:**
    - `.github/workflows/ci.yml`: the macOS job adds the credential check, ad hoc
      signing and DMG, the signed-runtime smoke, `verify-dmg`, and the DMG SBOM,
      checksums, verification and scan;
    - `tauri.macos.conf.json`: category Video, copyright, short description,
      `hardenedRuntime`;
    - `tauri.macos-packaged.conf.json` and `scripts/macos/freeze-worker.py`: version
      `0.1.0-alpha.37`;
    - docs: `macos-packaging.md`, `macos-delivery-plan.md`,
      `docs/security/release-verification.md`, `scripts/README.md`;
    - the M37 ledger row and the README status.
    - `Cargo.lock`: `cookie` 0.18.2 → 0.18.3 (`cargo update -p cookie`), a prerequisite
      fix for the new RUSTSEC-2026-0594 advisory that fails the Security scans job on
      every branch. It is the same lock-only change as M32's PR #57.
- Public contracts or migrations: none (no schema, contract or database change). The
  new conventions are:
  - release DMGs are named `OpenWorld-Moments_<version>_macOS_<arch>.dmg` (ADR-0008),
    and builds without credentials
    `OpenWorld-Moments_<version>+<commit>_macOS_<arch>_adhoc-unnotarized.dmg`;
  - the release folder holds the DMG, `sbom-macos-<arch>.cdx.json`, `checksums.txt`,
    `THIRD_PARTY_NOTICES.txt`, `signing-report-<arch>.json`, `dmg-check-<arch>.json`
    and the `notarization-*.json` logs;
  - the runtime's `inventory.json` hashes describe the **signed** files in a signed app;
  - the CI secret names are listed above;
  - the CI artifacts are `macOS-<arch>-unsigned-dev`, which now also holds
    `release-<arch>/`, and `macOS-<arch>-notarized-release-candidate` (release workflow
    only).
- Commands run (Apple M4, macOS 26.6.2):
  - `scripts/macos/freeze-worker.py`, with a separate `UV_PROJECT_ENVIRONMENT`, for
    `0.1.0-alpha.37`;
  - `python3 scripts/macos/build-shell.py --arch arm64 --no-package`;
  - `sign-and-package.py check-credentials`;
  - `package --arch arm64 --mode adhoc`;
  - `runtime-smoke.py` on the signed runtime;
  - `verify-dmg … --arch arm64 --expect adhoc`;
  - `sbom.py --installer`, `checksums`, `verify_sbom.py --release-dir` and
    `scan_artifacts.py` on the release folder;
  - a manual `hdiutil attach`, `codesign --verify --deep --strict`, `spctl --assess`
    (app and DMG) and `syspolicy_check distribution`;
  - a launch of the installed copy with a temporary `HOME`;
  - `pytest tests/test_macos_signing.py tests/test_macos_shell.py`;
  - the full `pnpm check`.
- Test and validation results:
  - **Signing order (arm64):**
    - 5 extension modules, then `libpython3.12.dylib`, `ffmpeg`, `ffprobe`,
      `owm-worker`, then the app;
    - every item shows `flags=0x10002(adhoc,runtime)` and an identifier
      `org.openworldmoments.desktop.runtime.*`;
    - 9 inventory entries were re-hashed, and only signed code changed.
  - **Library validation:** the first attempt, without an exception, showed that ad
    hoc plus Hardened Runtime stops the worker loading its own `libpython` ("different
    Team IDs"). The ad hoc-only exception fixes that. Developer ID builds forbid it,
    and verification fails if it appears.
  - **`codesign --verify --deep --strict`:** valid and satisfies its Designated
    Requirement, for the built app, the app mounted from the DMG and the installed
    copy.
  - **Signed runtime smoke:** passed: doctor, import, CPU render, cancellation,
    missing tool and corrupt tool (`worker.bundle_corrupt`, exit 3 in 1.93 s).
  - **`verify-dmg`:** passed:
    - `hdiutil verify` and the DMG signature;
    - the DMG holds only the app and `Applications -> /Applications`;
    - the installed copy passes the architecture audit;
    - the version report shows `aarch64-apple-darwin`, release, bundled worker;
    - replacing the app keeps the library;
    - the tampered resource and the unsigned nested `ffprobe` are rejected;
    - uninstalling keeps the library.
  - **Launch:** the installed copy started with a temporary `HOME`. The host started
    `Resources/runtime/owm-worker` as its child, the worker logged `worker ready` on
    loopback, the library was created under the temporary
    `~/Library/Application Support/OpenWorld Moments/`, and SIGTERM stopped both
    processes. The real user library was not touched.
  - **Gatekeeper (expected rejection):** `spctl --assess --type execute` printed
    `rejected` for the app, and `--type open` printed `rejected` for the DMG.
    `syspolicy_check distribution` reported "Adhoc Signed App" and "Notary Ticket
    Missing". This is the expected result for an unnotarized build and is why it is
    not publishable.
  - **SBOM:** 1,057 files and 320 libraries, with the DMG SHA-256 recorded;
    `verify_sbom.py --release-dir` passed. The release-folder scan found nothing.
  - **Ad hoc DMG (local):** 45 MiB,
    `OpenWorld-Moments_0.1.0-alpha.37+ccb1b79_macOS_arm64_adhoc-unnotarized.dmg`.
    The SHA-256 differs per build, because `hdiutil` isn't reproducible.
  - **Tests (`test_macos_signing.py`):** 45 tests cover:
    - missing, partial and malformed credentials;
    - redaction, in the runner, in errors and in every output file;
    - inside-out order, Mach-O types, codesign commands and stable identifiers;
    - the entitlement allowlist and forbidden keys, and the scope of the ad hoc
      exception;
    - re-hashing the inventory, including a non-code change and a new file;
    - signature identity, team, timestamp and runtime checks;
    - notarization Accepted, Invalid, warnings, no log, no ticket, and an expired key
      (HTTP 401);
    - keychain identity selection;
    - DMG names and checksums;
    - the whole flow without credentials, which is SKIPPED and not publishable;
    - the release gate, which refuses before running any command;
    - a full faked Developer ID flow: order, keychain and key cleanup, no secrets;
    - Gatekeeper rejecting a notarized build, another team's signature, and a
      wrong-architecture bundle;
    - `check-credentials` and `GITHUB_OUTPUT`;
    - Tauri metadata and version agreement;
    - that only the protected workflow references the secrets.
  - **CI:** both native macOS jobs run the ad hoc signing, smoke, `verify-dmg` and SBOM
    steps (see the PR checks).
- Decisions made:
  - **Our own signing script instead of Tauri's signing.** Tauri doesn't sign Mach-O
    files in `resources`, and the inventory must be re-hashed between nested and outer
    signing. Tauri's `signingIdentity` stays unset.
  - **The runtime stays in `Contents/Resources/runtime`**, signed as nested code before
    the bundle, so the host's worker path and M34's inventory layout don't change.
  - **The app and the DMG are both notarized and stapled**, so the first launch works
    offline after a drag install.
  - **Apple's log warnings fail the release**, as do any listed issues and a missing
    ticket.
  - **The release workflow re-signs the exact unsigned zip a green CI run on `main`
    built and tested**, after checking its SHA-256, instead of rebuilding. It is a
    manual `workflow_dispatch` in the protected `macos-release` environment, and the
    secrets go to two steps only.
  - **Some but not all credentials is an error.** No credentials is a clear SKIPPED.
    `--require-notarized` exits 3 unless the DMG is publishable.
  - **The ad hoc DMG name** carries the commit and `_adhoc-unnotarized`, so it can't be
    mistaken for a release asset.
  - **`CFBundleVersion` stays equal to the semver prerelease version.** The App Store's
    numeric rules don't apply to Developer ID distribution.
- Known limitations:
  - No Developer ID signature, notarization, stapled ticket or Gatekeeper acceptance
    has happened yet. That path is covered only by faked-tool tests, and
    `macos-release.yml` can't be dispatched until it is on `main`.
  - No clean-Mac runs yet, on Apple Silicon or Intel. The Intel DMG is built and
    checked in CI only.
  - Notarization of code in `Resources/` is unproven until the first real submission.
    If Apple objects, relocating the runtime is a separate change.
  - DMGs are not bit-reproducible (`hdiutil` timestamps).
  - The macOS release folder doesn't yet include the FFmpeg and x264 source archives
    that the notices promise; M39 must attach them, as Windows' `artifacts.py` does.
- Follow-up milestones affected:
  - **M38** stays blocked behind M37. It should link the install and uninstall section
    of `macos-signing.md` from the user guides and the download page.
  - **M39** stays blocked. It publishes the notarized candidates with a combined
    `checksums.txt`, the GPL source archives and the clean-machine matrix.
  - **M40** is unchanged.
- Pull request: PR pending
- Screenshots, reports, or artifacts:
  - CI artifacts `macOS-<arch>-unsigned-dev` contain `release-<arch>/`: the DMG,
    SBOM, checksums, notices, signing report and DMG check.
  - Local reports stay in the ignored `output/packaging/macos/release-arm64/`.
  - No credentials, footage, libraries, models, databases or build outputs are
    committed.
