# Scripts

Repository automation. Scripts must work on Windows and Linux CI runners, or be
called only from a job that pins its OS.

- `check-dco.sh` — verifies every commit in a range has a `Signed-off-by` trailer.
- `macos/build-shell.py` — builds an unsigned macOS development build for one
  architecture (`--arch arm64` or `--arch x86_64`) with the frozen runtime bundled
  (`--no-runtime` for the bare M33 shell), checks every Mach-O file and library
  dependency, runs `--version-report`, and zips the app into `output/packaging/macos/`.
  macOS only; used by the `macOS build` CI jobs.
- `macos/macho.py` — pure-Python Mach-O reader (architecture, minimum macOS version,
  loaded libraries and rpaths) and the runtime audit used by the freeze and the build.
- `macos/build-media.sh` — FFmpeg/FFprobe with libx264 for one macOS architecture from
  the pinned Windows sources, for macOS 14+, without build-machine paths (M34).
- `macos/freeze-worker.py` — freezes, audits and inventories the macOS worker (M34).
- `macos/runtime-smoke.py` — runs a frozen runtime as the host does, with an empty
  environment: doctor, import, render, cancellation, missing/corrupt tools (M34).
- `packaging/runtime_bundle.py` — freeze steps shared by the Windows and macOS builds.
