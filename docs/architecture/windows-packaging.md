# Windows alpha packaging and model management (M29)

Status: implementation candidate, **not a qualified release**. The accepted
[GPL decision](./adr/0007-windows-ffmpeg-packaging.md) is separate from completing
M29. Clean Windows 11 x64 lifecycle evidence is still required. M32 remains the
public alpha release gate. No macOS/Linux installer is introduced here.

## Package identity and prerequisites

- Per-user Unicode NSIS setup executable, application ID
  `org.openworldmoments.desktop`, product name **OpenWorld Moments**.
- Candidate version `0.1.0-alpha.29`; downgrades are refused by the installer.
- Target: Windows 11 x64 with Microsoft's Evergreen WebView2 OS component.
  Microsoft [includes WebView2 with Windows 11](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/evergreen-vs-fixed-version).
  It is OS-managed rather than bundled/pinned by this app. Its exact user agent
  appears in the system-check UI and native smoke report. If removed by an
  administrator, install/repair it using Microsoft's normal WebView2 installer;
  no terminal or developer Python is needed to run the application.
- Default app files: `%LOCALAPPDATA%\OpenWorld Moments`.
- Default library: `%APPDATA%\org.openworldmoments.desktop\library`.
  The app ID and library path remain stable through repair and upgrade.
- This alpha is unsigned. Windows/enterprise policy may warn about an unknown
  publisher or block it. Verify the artifact checksum and provenance first; do
  not disable security software. Signing procurement and public publication are
  outside M29.

## Runtime and licensing

The packaged host starts `runtime/owm-worker.exe` using the M03 stdin token,
stdout handshake and supervised loopback API. There is no shell or user PATH
lookup for required media tools. Packaged Windows builds ignore development
`OWM_WORKER_PYTHON`, `OWM_FFMPEG` and `OWM_FFPROBE` overrides. The frozen executable
dispatches the worker, separate M10 phone gateway and a fixed-path explicit
uninstall cleanup command. It is not a general-purpose Python command runner.
Worker and gateway keep their pipes without opening
console windows. Corrupt/missing runtime files fail startup with a repair error.

| Component | Pin | Distribution |
|---|---|---|
| Python | CPython 3.12.14, standalone build 20260929 via uv 0.13.7 | Frozen native x64 runtime, PSF license text |
| Worker | Current Git commit and executable SHA-256 | PyInstaller 6.22.3, console/onedir bootloader; application remains AGPL |
| SQLite | The pinned Python runtime's library, actual version/hash inventoried | FTS5 and version ≥3.42 checked |
| FFmpeg/FFprobe | 9.0.2, source archive SHA-256 in sources.json | Built as static x64 executables, GPL-2.0-or-later |
| libx264 | c24e06c2e184345ceb33eb20a15d1024d9fd3497 | Only enabled external codec library, GPL-2.0-or-later |
| Python/Rust dependencies | uv.lock / Cargo.lock | Runtime hashes and package license texts accompany the candidate |
| OCR / transcription engines | Optional external installations | Not bundled; existing detector/Transcript panels report unavailability |
| Model weights | Explicit optional downloads only | No weights or footage in the installer or repository |

`sources.json` pins the binary-producing source archives and checksums. The
extractor bounds archive size/count and rejects traversal and links. The media
build disables autodetected external libraries and network protocols, enables
GPL/libx264 explicitly, and rejects nonfree configurations. CPU H.264/AAC,
thumbnails, waveforms, LUT tone mapping and existing render graphs remain the
core path. Hardware encoders absent from this minimal build are unavailable;
the doctor reports that limitation without claiming GPU support.

Each package has checksums, the exact FFmpeg/x264 source archives, build scripts,
compiler/package versions, runtime inventory and license notices. The inventory
audits every native PE file as x64, hashes payload files, and omits editable-build
direct_url metadata. `python-notices.json` pins the Python build source commit and
matching license-text hashes for its native dependencies (including OpenSSL,
libffi, SQLite and zlib); these are verified before bundling. MinGW toolchain
license texts, including static-runtime exceptions, accompany the package. M30 still owns the
full transitive SBOM and security audit. Frontend production dependencies from
both workspaces have their installed notices copied and their names, versions
and licenses inventoried; absolute build paths are excluded.

## Build and CI

Build on native Windows x64 with the repository's pinned Node/pnpm/Rust tools,
uv 0.13.7, managed CPython 3.12.14 and MSYS2 MINGW64 GCC/make/nasm/pkgconf.

```powershell
pnpm install --frozen-lockfile
uv sync --managed-python --locked --all-packages --group packaging --python cpython-3.12.14-windows-x86_64-none
uv run --locked --group packaging --directory services/media-worker python ../../scripts/windows/prepare-sources.py
# In MSYS2 MINGW64 from the repository root:
bash scripts/windows/build-media.sh
# Back in PowerShell:
uv run --locked --group packaging --directory services/media-worker python ../../scripts/windows/freeze-worker.py
pnpm build:windows
```

Use a fresh `output/packaging/source-build` for source preparation. Build inputs,
sidecars, sources and media outputs stay ignored. The normal `pnpm build` creates an unbundled host; use `pnpm dev` for the
checkout runtime. Windows release execution expects the packaged runtime even
when the host was built without an installer. The packaging overlay is explicitly
selected by `build:windows`.

CI uses pinned `windows-2025`, freezes twice and compares payload hashes, builds
NSIS, then installs into a Unicode scratch path. It uses real WebView2/Tauri IPC
to check the doctor/catalog, import synthetic media and render a privacy-reviewed
project with bundled tools. It repairs the same version, builds a test-only higher
version (`0.1.0-alpha.29.1`), checks saved projects/renders after upgrade and verifies
uninstall retention. It refuses to run against an existing library. CDP is enabled
only in the CI child environment, never in product defaults.

The candidate artifact contains only the M29 installer, hashes, notices, source
archives, inventory and reports; it excludes test footage, libraries and model
weights. Before inventorying, the standard-library ZIP is rewritten in sorted member order
with fixed metadata, preserving every module's bytes. Frozen-payload repeatability
is checked within one toolchain snapshot; no files are excluded from comparison.
Bit-identical NSIS installers across compiler/runner updates are not claimed.
Hosted Windows Server smoke evidence cannot replace a clean Windows 11 client run.

## Doctor and model contracts

Contracts **1.23**, additive; migration **0019** extends the jobs kind constraint
without changing existing job data. M02's pre-upgrade backup and newer-schema
refusal remain active.

| Method | Route | Behavior |
|---|---|---|
| GET | `/v1/system-doctor` | Local storage, write permissions, loopback ports, SQLite/FTS5, codecs, real CPU/hardware test encodes, catalog signature and runtime inventory |
| GET | `/v1/model-manager` | Offline signature/checksum checks, signed model size/license/source/revision, required disk estimate, partial bytes, active checksum and retained versions |
| POST | `/v1/model-manager/download` | `{name}` from the bundled catalog → durable `model_download` job, with immutable checksum in stored params |
| POST | `/v1/model-manager/pin` | `{name,sha256}` → explicitly activate a hash-verified retained version |
| POST | `/v1/model-manager/remove` | `{name}` → remove that curated model, its versions and partial bytes; media/transcripts stay |
| POST | `/v1/jobs/{id}/cancel` or `/retry` | Existing cancellable job protocol; retry resumes verified-length partial data |

All routes remain token protected and explicitly host allowlisted; no caller
chooses a URL or filesystem path. The first packaged run presents a local system
check; Settings always allows rechecking and shows OS-managed WebView information.
Warnings about unavailable hardware do not hide a working CPU path.

The catalog contains curated MIT `tiny.en` and `base.en` artifacts from a pinned
Hugging Face revision. Ed25519 verifies exact manifest bytes before parsing URLs.
The trust root is compiled into the app, independent of the manifest. The initial
catalog's one-time signing key was discarded without persistence; catalog changes
require a reviewed application update and explicit trust-root/signature update.
There is no online catalog refresh or silent model update.

Only explicit Install starts network access. HTTPS origins are restricted for
the initial request and redirects. Size, content range and final SHA-256 are
checked; ignored ranges restart rather than append. A partial remains resumable
after interruption/cancel, but is never an active model. Fully verified versions
already committed at the cancellation boundary are retained. A 64 MiB reserve and
space for the verified version plus active copy are checked. File promotion is
atomic; source models/media are never rewritten. Active listings rehash model
contents, including same-size corruption. Retained versions and active copies
live under library/models/whisper; local hashes support explicit pin/rollback.
Concurrent destructive operations and active model/transcription jobs are refused.
Earlier CLI-installed models remain usable through M18; this UI manages only its
curated catalog. Downloading weights does not install whisper.cpp or establish
recognition quality, which remains unmeasured for real engines/gameplay here.

## Upgrade, uninstall and qualification

Repair and upgrade replace application files only. By default uninstall also
keeps the complete library, projects, downloaded models, derived media and managed
copies. The NSIS app-data checkbox requires a second explicit confirmation listing
the library/managed-media consequences. A restricted worker command resolves only
its fixed Windows Known Folder library, refuses linked roots/unrecognized databases,
and unlinks nested symlinks/junctions without traversing external originals. NSIS's
recursive application-data deletion is disabled. Application preferences remain;
failed removal reports retained data for manual cleanup. Silent uninstall always
retains data.
Referenced originals outside app data are not deleted. Retaining the library also
retains its private text; uninstall is not a text-purge operation.

Do not open a newer database with an older app. For rollback, retain the library,
preserve new work separately, and restore an M02 pre-upgrade backup into a separate
library copy with the matching older app. Never overwrite the only library copy.

Before marking M29 Complete, record this matrix on a clean supported Windows 11
x64 VM without developer Python, uv, FFmpeg, MSYS2 or a configured shell PATH:

1. Install the downloaded/checksummed candidate as a normal user; launch by icon.
2. Record OS/WebView versions, doctor/tool inventory and unsigned installer prompts.
3. Import a lawful synthetic clip, prepare playback, make/review a project and render.
4. Exercise model install, interrupted resume, offline/low disk, checksum/signature
   refusal and Unicode paths; record optional engine availability separately.
5. Repair, upgrade a supported older database/project, and verify retained edits,
   hashes, source media and pre-upgrade backup.
6. Uninstall with retention; reinstall and verify the same library. Separately test
   explicit data removal using a disposable library only.

Archive results with artifact hashes and distinguish hosted automation from this
client qualification. M29 and its dependents stay incomplete until the required
evidence exists.
