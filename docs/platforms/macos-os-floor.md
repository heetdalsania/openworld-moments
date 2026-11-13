# macOS OS floor: verification record

> Verified in M33 on 2026-11-11 against the locked dependencies at the M31 merge
> (`ecf30c5`). Re-run this check whenever `uv.lock`, `Cargo.lock`, the Rust toolchain or a
> bundled tool changes, and before raising or lowering the floor.

**Result: macOS 14.0 (Sonoma) is the floor for both `aarch64` and `x86_64`.** Nothing
locked needs a newer release, and one dependency the worker uses in development
(`opencv-python-headless` on Intel) already needs exactly 14.0.

The floor is set in three places, and `tests/test_macos_shell.py` keeps them equal:

| Where | Value | Effect |
|---|---|---|
| `apps/desktop/src-tauri/tauri.macos.conf.json` | `bundle.macOS.minimumSystemVersion: "14.0"` | `LSMinimumSystemVersion` in `Info.plist`: Finder refuses to open the app on older macOS |
| `scripts/macos/build-shell.py` | `MACOSX_DEPLOYMENT_TARGET=14.0` | `LC_BUILD_VERSION minos 14.0` in the host binary (checked after every build) |
| `apps/desktop/src-tauri/src/platform/mod.rs` | `MACOS_MINIMUM = "14.0"` | The platform report marks older systems `unsupported` (`os-below-minimum`) |

## How it was checked

- **Wheels:** every macOS wheel tag in `uv.lock` for CPython 3.12 (`cp312`, `abi3`,
  `py3-none`), split into packages the worker ships (`uv export --no-dev`) and
  development-only packages.
- **Binaries:** `scripts/macos/macho.py` reads `LC_BUILD_VERSION` from the built host
  and from a uv-managed (python-build-standalone) interpreter.
- **Documentation:** Tauri, Rust platform support and GitHub runner images for
  components with no binary in the repository yet.

## Results

| Component | Locked version | Apple Silicon floor | Intel floor | Evidence | Notes |
|---|---|---|---|---|---|
| Rust toolchain / std | 1.97.1 | 11.0 | 10.12 | Rust platform support | `x86_64-apple-darwin` is Tier 2 with host tools since Rust 1.90 (no upstream test guarantee) |
| Tauri 2 / tauri-cli | 2.x / 2.12.4 | 10.15 | 10.15 | Tauri docs; bundler default 10.13 | We set 14.0 |
| WebKit (WKWebView) | system | ships with macOS | ships with macOS | — | Updated by macOS, not bundled |
| Desktop host binary | this repository | **14.0** | **14.0** | `macho.py` on both built shells | Deployment target applied |
| CPython runtime | 3.12.14 (python-build-standalone 20260929) | 11.0 | older than 14 | M34: `macho.py` on the frozen `libpython3.12.dylib` (arm64 `minos 11.0`); Intel checked by the CI audit | The local Homebrew Python is built for macOS 26 and must never be bundled; the audit rejects it |
| cryptography | 50.0.2 | 11.0 | **no wheel** | `uv.lock` | Intel builds it from source against a static OpenSSL 3.5.9 built for macOS 14 (`scripts/macos/build-openssl.sh`); the frozen copy is audited and in the SBOM (M34). Homebrew's OpenSSL targets macOS 15 and is not used |
| cffi | 2.1.1 | 11.0 | 10.15 | `uv.lock` | |
| pydantic-core | 2.50.2 | 11.0 | 10.12 | `uv.lock` | |
| rpds-py | 2026.9.1 | 11.0 | 10.12 | `uv.lock` | |
| Other runtime packages | — | pure Python | pure Python | `uv.lock` | fastapi, uvicorn, websockets, jsonschema, … |
| opencv-python-headless (development only) | 4.14.0.94 | 13.0 | **14.0** | `uv.lock` | Highest floor found; not shipped |
| opentimelineio (development only) | 0.18.1 | 11.0 | no wheel | `uv.lock` | Not shipped; Intel development builds it from source |
| numpy (development only) | 2.5.4 | 11.0 | 10.13 | `uv.lock` | |
| FFmpeg / FFprobe | 9.0.2 with libx264, built from source (M34) | **14.0** | **14.0** | `macho.py` on the built tools | `scripts/macos/build-media.sh`; links only `libSystem` and system frameworks |
| OpenSSL (Intel, inside cryptography) | 3.5.9 LTS | — | **14.0** | `scripts/macos/openssl.json`, verified with a local source build | Built with `-mmacosx-version-min=14.0`, static |
| ONNX Runtime | not locked yet | — | — | — | Optional model artifacts (M34) must declare macOS 14 or older and the matching architecture |
| Tesseract OCR, whisper.cpp | not bundled yet | — | — | — | Same rule in M34 |
| GitHub runners | `macos-15`, `macos-15-intel` | 15 | 15 | runner images | `macos-15-intel` is the last Intel image (about August 2027) |

## Risks to revisit

- **Intel lifetime.** GitHub's Intel runners and Rust's Tier 1 testing for
  `x86_64-apple-darwin` are both ending; Apple has said macOS 26 is the last Intel
  release. Plan the Intel package's end of life before August 2027.
- **cryptography on Intel.** A source build depends on OpenSSL and a Rust toolchain at
  freeze time; M34 must pin and inventory both.
- **Raising the floor** needs a documented compatibility decision and a change to all
  three places above.
