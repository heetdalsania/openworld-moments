# Scripts

Repository automation. Scripts must work on Windows and Linux CI runners, or be
called only from a job that pins its OS.

- `check-dco.sh` — verifies every commit in a range has a `Signed-off-by` trailer.
- `macos/build-shell.py` — builds an unsigned macOS development shell for one
  architecture (`--arch arm64` or `--arch x86_64`), checks every Mach-O file in the
  bundle is a native binary for macOS 14+, runs `--version-report`, and zips the app
  into `output/packaging/macos/` (M33). macOS only; used by the `macOS shell` CI jobs.
- `macos/macho.py` — pure-Python Mach-O header reader (architecture and minimum
  macOS version) used by `build-shell.py` and its tests.
