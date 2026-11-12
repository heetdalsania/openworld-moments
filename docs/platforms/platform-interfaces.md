# Host platform interfaces (M33 audit)

The desktop host keeps operating-system differences in one module,
[`apps/desktop/src-tauri/src/platform/`](../../apps/desktop/src-tauri/src/platform/mod.rs).
Product modules call it and contain no `cfg(target_os)` of their own. Two exceptions
remain: `main.rs` keeps Tauri's required `windows_subsystem` attribute, and tests keep
OS-specific setup.

Each OS has a small implementation file (`windows.rs`, `macos.rs`, `other.rs` for
Linux development). Policy decisions are pure functions of `Facts`, so all
platforms' rules are unit-tested on every CI runner.

## Interfaces

| Interface | Purpose | Windows | macOS | Linux (development) |
|---|---|---|---|---|
| `facts()` / `Probe` | OS family and version, binary architecture, translation, build target | version left to the worker's system check; translation unknown | `/usr/sbin/sysctl -n kern.osproductversion`, `sysctl.proc_translated` (absolute path, no shell) | not read |
| `support(facts)` | `alpha`, `development` or `unsupported`, with reasons | x64 release = alpha; Arm = unsupported | development (`macos-preview`); below 14.0 or under Rosetta = unsupported | development |
| `capabilities()` | The `platform-capabilities` contract document (1.25) | ✓ | ✓ | ✓ |
| `app_dirs(app)` | Data, cache, log and temp folders | Tauri `app_data_dir` etc. (unchanged since M03) | `~/Library/Application Support/OpenWorld Moments`, `~/Library/Caches/…`, `~/Library/Logs/…`, `$TMPDIR/OpenWorld Moments` | Tauri XDG folders |
| `bundled_worker(facts)` | Whether the build starts a worker from its own bundle | release builds | not until M34 | no |
| `venv_python(repo)` | Development worker interpreter | `.venv/Scripts/python.exe` | `.venv/bin/python` | `.venv/bin/python` |
| `reveal_command()` | Show a file in the file manager | `%SystemRoot%\explorer.exe /select,"…"` | `/usr/bin/open -R -- …` | `xdg-open <folder>` |
| `hide_console()` | Start helper processes without a console window | `CREATE_NO_WINDOW` | nothing to do | nothing to do |
| `is_cloud_placeholder()` | Skip files that are only in the cloud | OneDrive offline/recall attributes | not detected yet (M35: File Provider) | no |

Windows behavior is unchanged. The Windows code moved verbatim from `host.rs`,
`reveal.rs`, `phone.rs`, `worker/supervisor.rs` and `watch/fsprobe.rs`, and the Windows
library stays in `%APPDATA%\org.openworldmoments.desktop\library`.

## No shell `PATH`

Every program the host starts is named by absolute path: the bundled or virtualenv
worker, `/usr/sbin/sysctl`, `/usr/bin/open` and `explorer.exe` under `%SystemRoot%`.
Linux development uses `xdg-open` from `PATH`. CI runs `--version-report` with only
`HOME` and `LANG` set to prove the macOS host needs nothing else.

## Audit of the remaining areas

| Area | Today | macOS work |
|---|---|---|
| Paths | `app_dirs`; only the library (`data`) is used | M35 moves proxies, thumbnails and analysis caches to `cache`, logs to `logs`, and staging to `temp` |
| Dialogs | `tauri-plugin-dialog` (native `NSOpenPanel`/`NSSavePanel` on macOS); no OS code in the app | M35: remembered locations and reauthorization |
| Keychain / secrets | Nothing persists a secret: the worker token and phone tokens exist only in memory for one launch or session | M35: Keychain behind this module if a secret must persist (`secret_store` in the report) |
| Processes | Worker and phone gateway by absolute path, argument arrays, piped stdin token, `kill_on_drop`; `hide_console` | M34: bundle-relative sidecars on macOS; M35: `SIGTERM`, quit and sleep/wake |
| Menus | Tauri's default menu (`menus: default` in the report) | M38: native application menus and `Command` shortcuts |
| Lifecycle | `RunEvent` handling in `host.rs` stops the worker and gateway on exit | M35: sleep/wake and forced-exit recovery; M38: quit confirmation |
| Network prompts | Phone LAN off by default (M31 consent) | M35: explain the macOS local-network and firewall prompts |

## Version report

`openworld-moments-desktop --version-report` prints the platform report as JSON and
exits before any window or worker starts. CI runs it on both native runners; the
physical smoke test uses it on real Macs. It contains no paths, names or identifiers.
