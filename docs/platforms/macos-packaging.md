# macOS worker and media toolchain (M34)

Status: **development builds**. Unsigned and not notarized (M37), and not a supported
release until M39. The macOS app now ships its own worker and media tools: a Mac
needs no Homebrew, no system Python, no developer tools and no shell `PATH`.

## What ships

Each architecture gets its own build, made on a native Mac of that architecture
([ADR-0008](../architecture/adr/0008-macos-distribution.md)):

| Component | Pin | How |
|---|---|---|
| Python | CPython 3.12.14, python-build-standalone 20260929, through uv 0.13.7 (`cpython-3.12.14-macos-aarch64-none` / `-x86_64-none`) | Frozen into the worker. Extension modules are linked into `libpython3.12.dylib` |
| Worker | The Git commit; executable SHA-256 recorded | PyInstaller 6.22.3, console onedir: the same strategy and the same freeze steps as Windows (`scripts/packaging/runtime_bundle.py`) |
| FFmpeg / FFprobe | 9.0.2 from the same checksum-verified source archive as Windows | Static FFmpeg libraries with `libx264` as the only external codec, autodetection off; built for `-mmacosx-version-min=14.0` |
| libx264 | `c24e06c2e184345ceb33eb20a15d1024d9fd3497` | Static, GPL-2.0-or-later ([ADR-0007](../architecture/adr/0007-windows-ffmpeg-packaging.md)) |
| Python packages | `uv.lock`, runtime closure only | Wheels for the target architecture. On Intel, cryptography 50.0.2 has no wheel and is built from source, linking Homebrew's OpenSSL statically |
| OCR, whisper.cpp, model weights | Not bundled | Optional; installed by the user or through the model manager |

## Bundle layout

```text
OpenWorld Moments.app/Contents/
├── Info.plist                 LSMinimumSystemVersion 14.0
├── MacOS/openworld-moments-desktop
└── Resources/runtime/
    ├── owm-worker             frozen worker (stdin token, loopback API, as on Windows)
    ├── _internal/             libpython3.12.dylib, extension modules, packages
    ├── tools/ffmpeg, tools/ffprobe
    ├── data/                  profiles and presets
    ├── notices/               license texts (Python, Rust, JavaScript, FFmpeg, x264)
    ├── THIRD_PARTY_NOTICES.txt
    └── inventory.json         every file's SHA-256, tools, sources, Mach-O audit
```

`tauri.macos-packaged.conf.json` adds the runtime as a Tauri resource. The plain
macOS configuration doesn't, so `cargo test` and `pnpm build` work without a frozen
runtime. M37 decides whether code in `Resources/` must move to `Frameworks/` or
`Helpers/` for signing.

## Sidecar launch rules

- Release builds on macOS and Windows start `Resources/runtime/owm-worker` (Windows:
  `runtime\owm-worker.exe`) by absolute path, with an argument array: the M03 stdin
  token and stdout handshake, kept on loopback. Development overrides
  (`OWM_WORKER_PYTHON`) apply only when no bundled worker is expected.
- The frozen worker checks the inventory before anything else: every listed file must
  exist with its SHA-256, inside the runtime and not a link. Then it sets `OWM_FFMPEG`
  and `OWM_FFPROBE` to the bundled tools. A missing or corrupt file stops it at once
  with `worker.bundle_corrupt` (exit 3); the host reports a repair error instead of
  hanging.
- The worker never runs an optional engine (Tesseract, whisper.cpp) that is built for
  the other architecture or quarantined as a download. It explains which build to
  install and never removes the quarantine itself (`openworld_moments/native.py`).

## Architecture audit

`scripts/macos/macho.py` reads Mach-O headers in pure Python. The freeze
(`freeze-worker.py`) and the build (`build-shell.py`) both fail unless:

- every Mach-O file is thin (no universal binaries) and of the target architecture;
- each declares a macOS minimum of 14.0 or older; the host and FFmpeg are exactly 14.0;
- every library it loads is in `/usr/lib` or `/System/Library`, or inside the runtime
  (resolving `@rpath`, `@loader_path` and `@executable_path`);
- no symbolic link points outside the runtime.

The summary goes into `inventory.json` as `macho_audit`. Apple Silicon result
(M4, macOS 26.6.2):

| | |
|---|---|
| Mach-O files | 9: `owm-worker`, `libpython3.12.dylib`, 5 extension modules, `ffmpeg`, `ffprobe` |
| Architecture | all `arm64` |
| Newest minimum | 14.0 (FFmpeg, host); Python and wheels 11.0 |
| System libraries | `libSystem`, `libz`, `libffi`, `libedit`, `libncurses`, `libpanel`, `libiconv`; CoreFoundation, CoreMedia, CoreVideo, SystemConfiguration |

## System doctor

The packaged doctor lists each runtime component with version, SHA-256, origin, license
and architecture (`architecture` in `system-doctor`, contracts 1.26): Python, SQLite,
the worker, FFmpeg and FFprobe. The inventory check rehashes the runtime.

## Optional artifacts and the model catalog

- A catalog entry can declare `platforms` (`macos-arm64`, `macos-x86_64`,
  `windows-x86_64`, `linux-…` or `any`). With no declaration it runs anywhere, so the
  signed catalog's bytes and signature are unchanged and Windows behaves exactly as
  before.
- `GET /v1/model-manager` reports `platforms` and `compatible` for each model.
- Downloading or pinning an incompatible artifact is refused with
  `models.incompatible_platform` (409) before any job or network use. Removing one
  still works.
- The two curated whisper.cpp models are architecture-independent weights. No ONNX or
  OCR artifacts are in the catalog yet; future native ones must declare `platforms`.

## SBOM and licenses

`scripts/security/sbom.py` now picks the package's platform from the inventory:

- the Rust closure for `aarch64-apple-darwin` or `x86_64-apple-darwin`;
- the Python closure with macOS markers;
- macOS file names, and the libraries that python-build-standalone links into libpython
  (OpenSSL, SQLite, bzip2, xz, expat, mpdecimal).

`verify_sbom.py` checks the SBOM file by file against the runtime and against the
license policy. CI uploads `sbom-macos-<arch>.cdx.json` with each build.

License findings:

- The macOS Rust closure adds no new license kinds (the policy passes).
- FFmpeg and x264 stay GPL-2.0-or-later under ADR-0007, from the same source archives
  as Windows.
- Python runtime notices come from the same pinned python-build-standalone commit.
- libffi, zlib, libedit and ncurses are macOS system libraries and are not bundled.

The artifact scan uses `security/artifact-scan-exceptions-macos.json`: only
third-party prebuilt wheels embed their upstream CI paths. Our host, worker and FFmpeg
contain none. The FFmpeg configure line uses a placeholder prefix and paths relative
to its source tree.

## Build

On a native Mac of the target architecture. Intel also needs `brew install nasm openssl@3`,
and `OPENSSL_DIR="$(brew --prefix openssl@3)" OPENSSL_STATIC=1` exported before
`uv sync`:

```bash
pnpm install --frozen-lockfile
uv sync --managed-python --locked --all-packages --no-dev --group packaging --python cpython-3.12.14-macos-aarch64-none
uv run --locked --no-dev --group packaging --directory services/media-worker python ../../scripts/windows/prepare-sources.py
bash scripts/macos/build-media.sh arm64
uv run --locked --no-dev --group packaging --directory services/media-worker python ../../scripts/macos/freeze-worker.py
pnpm build:macos:arm64
python3 scripts/macos/runtime-smoke.py "target/aarch64-apple-darwin/release/bundle/macos/OpenWorld Moments.app/Contents/Resources/runtime"
```

Replace `aarch64`/`arm64` with `x86_64` on Intel. To keep a development `.venv`,
point `UV_PROJECT_ENVIRONMENT` at a separate folder for the packaging environment.

## Validation

`scripts/macos/runtime-smoke.py` starts the bundled worker as the host does, with only
`HOME` and `LANG` set, from a Unicode folder with a Unicode library:

- the doctor reports every bundled tool;
- a synthetic clip made by the bundled FFmpeg is imported, gets a playback copy and a
  project, and renders on the CPU to H.264/AAC, checked by the bundled FFprobe; the
  source clip is unchanged;
- a running job is cancelled;
- a missing tool and a corrupt tool each stop the worker in about 2 seconds with
  `worker.bundle_corrupt`.

CI also runs the host's supervisor (start, crash detection and restart, repeated
crashes, cancellation), import-to-playback and session/editor tests against the frozen
worker on both architectures.

| Check | Apple Silicon (local M4, macOS 26.6.2) | Intel |
|---|---|---|
| Runtime frozen and audited | Pass | CI (`macos-15-intel`) |
| Runtime smoke | Pass | CI |
| Host E2E against frozen worker | Pass (12 tests) | CI |
| SBOM verified, artifact scan | Pass | CI |
| App opened from Finder, bundled worker started, system check "Core checks passed" | Pass | Physical Intel Mac pending (with the M33 launch) |

Sizes (Apple Silicon): runtime 92 MiB (tools 43 MiB, `_internal` 36 MiB, notices
5 MiB), app 97 MiB, zip 46 MiB.

## Known limitations

- **No hardware acceleration yet:** VideoToolbox is excluded (autodetection off). CPU
  `libx264` is the correctness path; M36 adds tested hardware encoding.
- **Unsigned:** the bundled worker and tools carry only linker or PyInstaller ad-hoc
  signatures. Signing order, entitlements and notarization are M37.
- **cryptography on Intel** is built from source at freeze time with
  `OPENSSL_STATIC=1`, so Homebrew's OpenSSL on the CI runner is linked into the
  extension. The Mach-O audit fails the build if it would load an outside library.
- **No universal binaries:** a universal wheel fails the audit. None are in the runtime
  closure today.
- **The Intel lane has a planned end:** GitHub's last Intel runner image is supported
  until about August 2027.
