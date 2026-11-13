## Milestone handoff

- Milestone: M34 — macOS worker and media toolchain
- Outcome: **Implemented; not yet complete.**
  - **Still to run:**
    - the first run of both macOS CI jobs with packaging (the Intel freeze, its
      source-built cryptography and its audit run for the first time there);
    - a physical Intel Mac launch (together with M33's).
  - **Done and verified on Apple Silicon** (M4, macOS 26.6.2):
    - **Freeze strategy:** the same as Windows. PyInstaller 6.22.3 console onedir on
      the pinned python-build-standalone CPython 3.12.14 through uv 0.13.7, with the
      shared steps moved into `scripts/packaging/runtime_bundle.py`. The result is
      native per architecture.
    - **Media tools:** FFmpeg/FFprobe 9.0.2 with libx264 only, built from the same
      checksum-verified sources as Windows for `-mmacosx-version-min=14.0`, with
      autodetection off. They link only `libSystem` and system frameworks, and embed
      no build-machine paths.
    - **Bundle:** the runtime ships as `Contents/Resources/runtime`. Release hosts on
      macOS and Windows start the bundled worker by absolute path (`bundled_worker`,
      `WORKER_EXECUTABLE`).
    - **Architecture audit:** pure Python (`macho.py`). Every Mach-O file is thin, of
      the target architecture, with a minimum ≤ 14.0, and loads only system libraries
      or files inside the runtime; no link escapes. It runs at freeze and at build
      time, and the summary is stored in `inventory.json`.
    - **Damaged runtime:** a missing or corrupt tool stops the worker in about 2
      seconds with `worker.bundle_corrupt`, and the host doesn't hang.
    - **System doctor:** reports version, SHA-256, origin, license and architecture
      for Python, SQLite, the worker, FFmpeg and FFprobe.
    - **Model catalog:** optional `platforms` per entry. `compatible` appears in the
      status, and incompatible downloads or pins are refused with
      `models.incompatible_platform` before any job or network use. The signed catalog
      is unchanged.
    - **Optional engines:** Tesseract and whisper.cpp are refused when built for the
      other architecture or quarantined, with a fix the user can act on and no
      unquarantining.
    - **SBOM:** one per architecture (macOS Rust and Python closures, macOS files),
      verified against the runtime file by file, plus a macOS artifact scan.
- Files and modules changed:
  - **Scripts:**
    - new: `scripts/macos/build-media.sh`, `freeze-worker.py`, `runtime-smoke.py`,
      `scripts/packaging/runtime_bundle.py`;
    - `scripts/macos/macho.py`: load commands and `audit_runtime`;
    - `scripts/macos/build-shell.py`: packaged build, runtime audit, `--no-runtime`;
    - `scripts/windows/freeze-worker.py` uses the shared steps and records tool
      architecture;
    - `scripts/windows/artifacts.py` ships `runtime_bundle.py`;
    - `scripts/security/components.py` and `sbom.py`: per-platform profiles.
  - **Host (Rust):** `platform/mod.rs` (macOS release builds bundle the worker;
    `WORKER_EXECUTABLE`; contract 1.26), `host.rs`, and new
    `tauri.macos-packaged.conf.json`.
  - **Worker:**
    - new `native.py` (platform key, Mach-O architectures, quarantine through libc
      `getxattr`);
    - `system.py`: platform-aware bundle names, tool architecture;
    - `transcripts/catalog.py`, `downloads.py`: `platforms`, `compatible`,
      `installable`;
    - `api/app.py`: early refusal of incompatible downloads;
    - `transcripts/whisper.py`, `detectors/ocr.py`: engine checks;
    - `diagnostics.py` (1.26).
  - **Contracts 1.26:** `system-doctor` tool `architecture`; `model-manager`
    `platforms`/`compatible` with semantic rules; fixtures; generated files.
  - **Desktop:** the macOS preview note no longer says the tools are missing; test
    fixtures updated.
  - **CI:** the `macos` job now does:
    - managed CPython, with a static-OpenSSL cryptography build on Intel;
    - cached media build, freeze and audit;
    - host E2E against the frozen worker;
    - packaged build, runtime smoke, SBOM, verification and scan;
    - artifacts.
  - **Security:** `security/artifact-scan-exceptions-macos.json`.
  - **Config:** `eslint.config.js` ignores `output/` and `bundle-input/`.
  - **Docs:**
    - new `docs/platforms/macos-packaging.md`;
    - updates to the development build guide, OS floor record, platform interfaces,
      delivery plan, Windows packaging, scripts README, contracts CHANGELOG and
      VERSIONING, README and ledger;
    - the M33 ledger row no longer lists the Apple Silicon on-screen check as pending.
  - **Tests:**
    - `tests/test_native.py`;
    - Mach-O dependency, runtime-audit and packaged-bundle tests;
    - macOS SBOM profile tests;
    - catalog compatibility and API refusal tests;
    - the inventory test across platforms.
- Public contracts or migrations:
  - **Contracts 1.26:**
    - `system-doctor` `tools[].architecture` (optional);
    - `model-manager` `models[].platforms` and `compatible` (optional).

    Earlier 1.x documents stay readable. No database migration.
  - **Model catalog:** `platforms` is optional in `ModelEntry`; the signed bytes and
    trust root are unchanged.
  - **Worker API:** new error `models.incompatible_platform` (409) on
    `POST /v1/model-manager/download` and pin.
  - **Bundle:** the runtime layout is now shared by both platforms (Windows
    `runtime\owm-worker.exe`, macOS `Resources/runtime/owm-worker`), and
    `inventory.json` gains `platform`, `minimum_macos` and `macho_audit` on macOS.
- Commands run:
  - `prepare-sources.py`, then `build-media.sh arm64` (twice; the second build has
    path-free binaries);
  - `uv sync --managed-python … cpython-3.12.14-macos-aarch64-none`, in a separate
    environment so the development `.venv` is untouched;
  - `freeze-worker.py`;
  - `frozen-worker-probe.py` with an empty environment;
  - `runtime-smoke.py` on the frozen and on the bundled runtime;
  - `cargo test --test supervisor --test library_e2e --test session_e2e` against the
    frozen worker;
  - `build-shell.py --arch arm64` (packaged);
  - `sbom.py`, `verify_sbom.py`, `scan_artifacts.py`;
  - launching the app from the unzipped artifact, and checking the system check on
    screen;
  - the full `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`, worker
    `mypy --platform darwin|win32|linux`.
- Test and validation results:
  - **Mach-O audit (arm64):** 9 Mach-O files, all thin `arm64`. Newest minimum 14.0
    (host and FFmpeg); Python and wheels 11.0. System libraries only: `libSystem`,
    `libz`, `libffi`, `libedit`, `libncurses`, `libpanel`, `libiconv`, CoreFoundation,
    CoreMedia, CoreVideo, SystemConfiguration.
  - **Runtime smoke (arm64, empty environment, Unicode paths):**
    - the doctor is packaged and ready, with both tools `arm64`;
    - the synthetic clip goes import → playback copy → project → CPU render, producing
      H.264 and AAC at 3.0 s, and the source is unchanged;
    - cancellation reaches `cancelled`;
    - a missing tool exits 3 with `worker.bundle_corrupt` in 1.9 s; a corrupt tool in
      1.87 s;
    - the worker exits cleanly.
  - **Host E2E against the frozen worker:** supervisor 9 tests (start/auth, crash
    restart, repeated crashes, cancellation, port conflict, early exit),
    import-to-playback 1, sessions/editor 2. All pass.
  - **App:** opened from Finder from the zip, the host started
    `Resources/runtime/owm-worker` and created the library in
    `~/Library/Application Support/OpenWorld Moments/`. The system check showed
    "macOS 26.6.2 · Apple Silicon (arm64) build · version 0.1.0-alpha.34", "Packaged
    runtime" and "Core checks passed". Quitting stopped the worker. The test library
    was removed.
  - **SBOM (arm64):** 1,054 runtime files, 320 libraries, schema-valid; verified
    against the runtime and the license policy.
  - **Artifact scan:** 6 findings, all in third-party prebuilt wheels and explained;
    0 in our host, worker or FFmpeg.
  - **Sizes (arm64):** runtime 92 MiB (tools 43, `_internal` 36, notices 5), app
    97 MiB, zip 46 MiB.
  - **Gate:** `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check` passes.
    - Worker: 1,273 passed, 1 skipped (the existing environment skip).
    - Contracts: 366 Python and 399 TypeScript tests.
    - Desktop: 285 tests. Rust: all suites.
    - Lint, formatting, REUSE and contract drift are clean.
  - **Worker mypy** for darwin, win32 and linux: clean.
- Decisions made:
  - **One freeze pipeline for both platforms.** The Windows freeze now calls the same
    shared steps (moved unchanged), and the Windows release ships that module as
    corresponding source.
  - **The runtime lives in `Resources/`** for these unsigned builds, mirroring Windows
    `runtime\`. M37 decides whether signing needs `Frameworks/` or `Helpers/`.
  - **No VideoToolbox yet.** FFmpeg autodetection stays off, so the binaries link only
    system libraries and the CPU path is the reference; M36 adds tested hardware
    encoding.
  - **No unsafe FFI in the host, and minimal FFI in the worker.** Quarantine is read
    with libc `getxattr` through ctypes, because Python's `os.getxattr` doesn't exist
    on macOS; a test with a real attribute covers it.
  - **The catalog stays signed and unchanged.** `platforms` is optional, so no new
    signing key was needed.
  - **A path-free FFmpeg build** (placeholder prefix, relative include paths) instead
    of a new artifact-scan exception.
- Known limitations:
  - **Not yet done (blocks Complete):** the first green Intel CI run (freeze, static
    cryptography, audit, smoke) and a physical Intel Mac launch.
  - **Unsigned:** the bundled binaries carry only ad-hoc signatures (M37).
  - **No hardware encoding** on macOS yet (M36).
  - **cryptography on Intel** is built from source at freeze time with
    `OPENSSL_STATIC=1`.
  - **No ONNX or native OCR/transcription artifacts are in the catalog yet;** the
    compatibility checks are in place for when they are added.
  - **Python worker tests still run only on Linux and Windows CI;** macOS covers the
    host suites and the frozen-runtime smoke.
- Follow-up milestones affected:
  - **M35:** caches and logs into the resolved folders; File Provider placeholders;
    Keychain; local-network prompt for the bundled gateway.
  - **M36:** VideoToolbox probe and fallback; HDR and preview/render parity with the
    bundled FFmpeg (rebuild with the needed frameworks).
  - **M37:** signing order for `Resources/runtime` (or relocation), entitlements,
    notarization; DMG names from ADR-0008.
  - **M39:** both architectures on clean Macs.
- Pull request: [#52](https://github.com/heetdalsania/openworld-moments/pull/52)
- Screenshots, reports, or artifacts:
  - CI artifacts `macOS-<arch>-unsigned-dev` contain the zip, `build-info`,
    `SHA256SUMS`, `sbom-macos-<arch>.cdx.json`, the runtime inventory with its Mach-O
    audit, the runtime smoke report and the artifact scan.
  - No footage, libraries, models, databases, credentials or build outputs are
    committed.
