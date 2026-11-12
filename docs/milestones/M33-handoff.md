## Milestone handoff

- Milestone: M33 — macOS foundation and CI
- Outcome: **Implemented; not yet complete.**
  - **Still to run:**
    - the physical launch smoke test on an Intel Mac;
    - an on-screen look at the system-check line on the Apple Silicon Mac (the screen
      was locked during the run).

    Steps and the results table are in the
    [development shell guide](../platforms/macos-development-shell.md#physical-launch-smoke-test).
    The two `macOS shell` CI jobs run for the first time on this pull request.
  - **Done:**
    - **Platform contract:** `platform-capabilities` (contracts 1.25), written by the
      host. It reports the OS family and version, the floor, the binary architecture,
      translation (Rosetta), the build target and profile, a support level with
      reasons, the directory convention and integrations. It carries no paths, names or
      identifiers.
    - **Platform module:** one host module (`src/platform/`) holds every OS difference.
      Product modules have no `cfg(target_os)` left, and Windows behavior and its
      library location are unchanged.
    - **macOS folders:** the library is under
      `~/Library/Application Support/OpenWorld Moments/`, with Caches, Logs and temp
      folders resolved. Programs are started by absolute path, never from the shell
      `PATH`.
    - **Native builds:** `aarch64-apple-darwin` and `x86_64-apple-darwin`, with a 14.0
      deployment target. Each build is checked by Mach-O header (thin, right
      architecture, minimum ≤ 14.0, host exactly 14.0) and by `Info.plist`, then
      packaged as `OpenWorld-Moments_<version>+<commit>_macOS_<arch>_unsigned-dev.zip`.
    - **Version report:** `--version-report` prints the platform report and exits
      before any window or worker starts.
    - **CI:** two pinned jobs, `macos-15` (arm64) and `macos-15-intel` (x86_64). Each
      checks the runner is native, runs clippy and the Rust and desktop tests, builds,
      verifies the bundle, runs the version report and uploads the zip, with separate
      caches per architecture.
    - **In the app:** the system check names the OS, build architecture and support
      level. It explains macOS previews, Rosetta and too-old systems, even when no
      worker is running. Diagnostics embed the host report.
    - **Decisions recorded:** the OS floor verification, ADR-0008, the platform
      interface audit and the support matrix.
- Files and modules changed:
  - **Host (Rust):**
    - new `src/platform/{mod,macos,windows,other}.rs`;
    - `build.rs` records the target triple;
    - `lib.rs`: the `platform_info` command, `--version-report` and build stage names;
    - `host.rs`: worker selection, library folder, diagnostics host report;
    - `reveal.rs`, `phone.rs`, `worker/supervisor.rs`, `watch/fsprobe.rs` delegate to
      the platform module;
    - new `tauri.macos.conf.json` (minimum 14.0).
  - **Contracts:**
    - `platform-capabilities.schema.json`, plus an optional `host` in
      `diagnostics-report`;
    - Python and TypeScript semantic rules and fixtures;
    - the version bump to 1.25 (CHANGELOG, VERSIONING, generated files).
  - **Worker:** `diagnostics.py` and `api/app.py` accept, validate and embed the host
    report. A malformed report is dropped and doesn't block diagnostics.
  - **Desktop:**
    - new `platform.ts`;
    - the `SystemPanel` platform line and notes;
    - fake host support for `platform_info`.
  - **Scripts:**
    - new `scripts/macos/macho.py` (pure-Python Mach-O reader);
    - new `scripts/macos/build-shell.py` (build, verify, run the report, package);
    - `pnpm build:macos:arm64` and `build:macos:x86_64`;
    - the docs harness stub reports a Windows build.
  - **CI:** the `macos` job matrix in `.github/workflows/ci.yml`.
  - **Docs:**
    - `docs/architecture/adr/0008-macos-distribution.md`;
    - `docs/platforms/macos-os-floor.md`, `platform-interfaces.md` and
      `macos-development-shell.md`;
    - delivery plan links, architecture index, desktop UI and worker docs;
    - `scripts/README.md`;
    - the system-check guide screenshot, regenerated.
  - **Tests:**
    - Rust: platform policy, folders, report shape and version sync, version flag,
      stage names, diagnostics body;
    - worker: `tests/test_macos_shell.py` (22 tests) and two diagnostics host tests;
    - desktop: four system-check tests;
    - contracts: 13 fixtures (two of them diagnostics).
- Public contracts or migrations:
  - **Contracts 1.25:** the new `platform-capabilities` contract, and the optional
    `host` in `diagnostics-report`. Earlier 1.x documents stay readable. No database
    migration.
  - **Host:** the `platform_info` command and the `--version-report` command-line flag.
  - **Worker API:** `POST /v1/diagnostics` accepts an optional `host` object.
  - **macOS library location:** now `~/Library/Application Support/OpenWorld Moments/`.
    macOS was never released. Contributors who ran development builds before M33 have
    a library in `~/Library/Application Support/org.openworldmoments.desktop/library`;
    it is not moved automatically. Move it by hand if needed.
- Commands run:
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`;
  - worker `mypy --platform darwin|win32|linux`;
  - `pnpm build:macos:arm64`;
  - `scripts/macos/build-shell.py --arch x86_64 --no-run`, then `--skip-build`
    under Rosetta;
  - `scripts/docs/capture-screenshots.py` and `scripts/docs/a11y-smoke.py`;
  - a debug host run, to confirm the library folder.
  - `cargo clippy --target x86_64-pc-windows-msvc` could not run on macOS (the Windows
    resource compiler `llvm-rc` is missing). The Windows CI jobs cover the moved
    Windows code.
- Test and validation results:
  - **Gate:** passes with the generated files staged.
    - Worker: 1,239 passed, 1 skipped (the existing environment skip).
    - Contracts: 360 Python and 393 TypeScript tests.
    - Desktop: 285 tests.
    - Rust: all suites pass.
    - Lint, formatting, REUSE and contract drift are clean.
  - **Worker mypy** for darwin, win32 and linux: clean.
  - **Apple Silicon shell (M4, macOS 26.6.2):**
    - built in 3m19s and verified: thin `arm64`, `minos 14.0`, `LSMinimumSystemVersion
      14.0`;
    - the version report (run with only `HOME` and `LANG` set) shows `aarch64`,
      `translated: false`, release, `development` (`macos-preview`);
    - the unzipped artifact opened its window and quit cleanly.
  - **Intel shell, cross-built:** verified as thin `x86_64` with `minos 14.0`. Run
    under Rosetta it reports `translated: true` and `unsupported`, and the verifier
    rejects it as designed.
  - **Folders:** a debug host with the worker created
    `~/Library/Application Support/OpenWorld Moments/library/database.sqlite3`. The
    test library was removed afterwards.
  - **Browser smoke:** 29 of 29 checks pass; the guide screenshot shows the new line.
  - **Goldens:** the export goldens were regenerated for the 1.25 version string.
- Decisions made:
  - **macOS 14.0 floor** for both architectures (verification record). The highest
    floor found is `opencv-python-headless` on Intel at exactly 14.0 (development
    only).
  - **ADR-0008:**
    - separate native DMGs;
    - GitHub Releases;
    - Developer ID, Hardened Runtime and notarization in M37;
    - no App Sandbox at first.
  - **Support policy:**
    - Windows x64 release = `alpha`;
    - macOS = `development` until M39;
    - Rosetta, an OS below the floor or Windows on Arm = `unsupported`.
  - **No `unsafe`:** the host reads `kern.osproductversion` and
    `sysctl.proc_translated` through `/usr/sbin/sysctl` by absolute path, so it needs
    no FFI and no new dependency.
  - **macOS release shells start without a worker** (`bundled_worker: false`) until
    M34 bundles one.
  - **Testers build on the test Mac or download with `gh`:** the guide never asks
    anyone to remove quarantine or bypass Gatekeeper.
- Known limitations:
  - **Not yet done (blocks Complete):**
    - the physical Intel Mac launch;
    - an on-screen look at the system check on Apple Silicon;
    - the first green run of both macOS CI jobs.
  - **Not claimed:** no media-workflow parity. Import, analysis, playback copies,
    renders and phone transfer need the bundled worker and FFmpeg (M34–M36).
  - **Intel risks** (OS floor record):
    - cryptography 50.0.2 has no Intel macOS wheel and is built from source;
    - `x86_64-apple-darwin` is Rust Tier 2;
    - `macos-15-intel` is GitHub's last Intel image (about August 2027).
  - **Windows:** the host does not read the Windows version itself (the worker's
    system check still does), and it doesn't detect x64 emulation on Windows on Arm.
  - **Out of scope:** Python tests don't run on macOS CI (M34).
- Follow-up milestones affected:
  - **M34:**
    - set `bundled_worker` for macOS;
    - resolve sidecars from the bundle;
    - freeze a source-built cryptography for Intel;
    - build FFmpeg with `-mmacosx-version-min=14.0`;
    - extend `build-shell.py` and `macho.py` checks to every sidecar.
  - **M35:**
    - move caches, logs and staging into the resolved folders;
    - File Provider placeholders in `is_cloud_placeholder`;
    - Keychain behind `secret_store`.
  - **M37:** signing and notarization of the same bundle layout; DMG asset names from
    ADR-0008.
  - **M38:** native menus (`menus: native`), and macOS wording for the system-check
    notes.
- Pull request: to be linked
- Screenshots, reports, or artifacts:
  - CI artifacts `macOS-arm64-unsigned-dev` and `macOS-x86_64-unsigned-dev` (zip,
    `build-info-<arch>.json`, `SHA256SUMS.txt`).
  - `docs/guides/images/setup-system-check.png`, regenerated with synthetic data.
  - No footage, libraries, models, databases, credentials or build outputs are
    committed.
