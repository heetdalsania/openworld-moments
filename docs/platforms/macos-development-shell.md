# macOS development shells (M33)

M33 builds the desktop host natively for Apple Silicon and Intel. The result is an
**unsigned development shell**: the real app window and UI, without the worker or media
tools (those arrive in M34), not notarized (M37), and not a supported release
(M39). Use it to check builds, the platform report and the UI on a Mac, never to give
to users.

## Support matrix

| | Apple Silicon | Intel |
|---|---|---|
| Rust target | `aarch64-apple-darwin` | `x86_64-apple-darwin` |
| macOS | 14 Sonoma or newer | 14 Sonoma or newer |
| Hardware | M1 or newer | Intel Macs that run macOS 14 |
| CI runner | `macos-15` | `macos-15-intel` |
| Artifact | `OpenWorld-Moments_<version>+<commit>_macOS_arm64_unsigned-dev.zip` | `…_macOS_x86_64_unsigned-dev.zip` |
| Status | Development shell | Development shell |

Not covered yet (no media-workflow parity is claimed):

- importing, analysis, playback copies, rendering and phone transfer, which need the
  bundled worker and FFmpeg (M34–M36);
- signing, notarization and DMGs (M37);
- native menus, VoiceOver testing and macOS guides (M38).

A shell running under Rosetta (the Intel build on an Apple Silicon Mac) is reported as
**unsupported**, and the system check tells the user to get the Apple Silicon build. The
same happens on macOS older than 14.

Why two packages and no App Sandbox: [ADR-0008](../architecture/adr/0008-macos-distribution.md).
Why 14.0: [OS floor record](./macos-os-floor.md). How OS differences are kept apart:
[platform interfaces](./platform-interfaces.md).

## Build from a clean checkout

Requirements on the Mac: Xcode Command Line Tools (`xcode-select --install`), the Rust
toolchain from `rust-toolchain.toml` (installed by `rustup` on first use), Node 22
with pnpm (`corepack enable`), and Python 3 (the system one is enough for the build
script).

```bash
pnpm install --frozen-lockfile
```

On an Apple Silicon Mac:

```bash
pnpm build:macos:arm64
```

On an Intel Mac:

```bash
pnpm build:macos:x86_64
```

Each command builds the app for that architecture with `MACOSX_DEPLOYMENT_TARGET=14.0`,
then checks:

- every Mach-O file in the bundle is a thin binary of that architecture that runs on
  macOS 14;
- `Info.plist` declares 14.0;
- the app's `--version-report` reports a native release build.

It then writes the zip, `build-info-<arch>.json` and `SHA256SUMS.txt` to
`output/packaging/macos/`.

Building the **other** architecture on one Mac (for example Intel on Apple Silicon)
needs `rustup target add x86_64-apple-darwin` and must skip the native run, because
the result would run under Rosetta:

```bash
python3 scripts/macos/build-shell.py --arch x86_64 --no-run
```

CI builds both architectures on native runners for every pull request (`macOS shell
(arm64)` and `macOS shell (x86_64)`). Each job uploads its zip as an artifact for 30
days.

## Opening a shell on a test Mac

**Prefer building on the test Mac itself** (commands above). The app you build there has
no quarantine flag, so it opens normally from `target/<triple>/release/bundle/macos/`.

A CI zip that was downloaded through a browser is quarantined, and an unsigned app is
blocked by Gatekeeper. Do **not** remove the quarantine attribute or disable Gatekeeper
to work around it. Use the build on the Mac itself, or fetch the artifact with the
GitHub CLI (`gh run download <run-id> -n macOS-arm64-unsigned-dev`), which does not
mark files as downloaded from the internet. Unpack it with `ditto -x -k <zip> <folder>`.

## Physical launch smoke test

Run on one Apple Silicon Mac and one Intel Mac, each on macOS 14 or newer.

1. Build the native shell on the Mac (above). The command must end with `verified
   native <arch> shell for macOS 14.0+`.
2. Run the version report from Terminal:

   ```bash
   "target/aarch64-apple-darwin/release/bundle/macos/OpenWorld Moments.app/Contents/MacOS/openworld-moments-desktop" --version-report
   ```

   (Use `x86_64-apple-darwin` on Intel.) Check `os.version` matches **About This Mac**,
   `architecture.binary` is `aarch64` (Apple Silicon) or `x86_64` (Intel), and
   `translated` is `false`.
3. Open the app from Finder. The window opens with first-run setup.
4. Choose **Start setup**. The system check shows a line such as *macOS 15.2 · Apple
   Silicon (arm64) build · version 0.0.0 · Development build* and the note that macOS
   builds are previews. The worker checks report that the worker is unavailable; that
   is expected until M34.
5. Quit with ⌘Q. No `openworld-moments-desktop` process remains in Activity Monitor.
6. Apple Silicon only: run the Intel shell. The system check shows *Not supported on
   this computer* and tells you to get the Apple Silicon build.

### Results

| Check | Apple Silicon | Intel |
|---|---|---|
| Hardware and macOS | Mac16,12 (Apple M4), macOS 26.6.2 | **Pending** |
| 1. Native build verified | Pass (built locally and in CI) | Pass when cross-built (`--no-run`); native build pending |
| 2. Version report | Pass: `aarch64`, `translated: false`, `26.6.2`, release | **Pending** |
| 3. App opens from Finder | Pass: window "OpenWorld Moments" opened from the unzipped artifact | **Pending** |
| 4. System check line | Covered by UI tests; on-screen check **pending** (screen was locked) | **Pending** |
| 5. Quits cleanly | Pass: quit by Apple event, no process left | **Pending** |
| 6. Rosetta detected | Pass: `translated: true`, `unsupported`; verifier rejects | n/a |
