# macOS files, permissions and lifecycle (M35)

Development builds for macOS 14+, following [ADR-0008](../architecture/adr/0008-macos-distribution.md). These changes do not qualify a release or complete the deferred Windows and physical Intel checks.

## Files and storage

| Contents | Location |
|---|---|
| Default canonical library: SQLite, managed media, models, project/render records, exports and backups | `~/Library/Application Support/OpenWorld Moments/library/` |
| Optional library selection, version 1, containing a user-selected path | `~/Library/Application Support/OpenWorld Moments/library-location.json` |
| Disposable proxies, filmstrips and waveforms | `~/Library/Caches/OpenWorld Moments/derived/` |
| Incomplete derived media | `~/Library/Caches/OpenWorld Moments/staging/derived/` |
| Redacted worker logs | `~/Library/Logs/OpenWorld Moments/worker.jsonl`, 2 MiB per file plus three rotations |
| Temporary phone uploads | OS per-user temporary directory, `OpenWorld Moments/phone/` |
| Temporary transcription WAVs | `~/Library/Caches/OpenWorld Moments/staging/transcripts/` |
| Import and render finalization staging | Inside the canonical library, `staging/`; removed at worker startup |
| User-saved open-format exports, diagnostics and calibration files | The destination explicitly chosen in a native Save panel |

Finalization staging stays on the destination volume so promotion uses an atomic rename. Moving import/render staging indiscriminately to the OS temporary volume would break managed imports and renders on external volumes. Canonical transcripts and analysis records remain in SQLite; models remain in Application Support.

Windows and Linux retain their existing default layouts. macOS passes `--cache-dir` and `--log-dir` to the worker; CLI callers without those flags retain the library-local layout. Contracts 1.27 add optional `derived-media.storage_root`: `library` (also the meaning when omitted) or `cache`. Artifact path syntax is unchanged. The worker alone resolves actual paths. No SQL migration is needed.

After an M34 upgrade, old library-local derived files are retained. New cache misses are rebuilt from the original/managed source. No old footage, model, project or library-local cache is silently deleted during upgrade. Removing the new disposable cache likewise results in ordinary missing-artifact recovery.

## Native selection and remembered authorization

Import buttons and watched folders use native Open panels; exports use native Save panels. Dragged paths are explicitly supplied by the user. The app never discovers capture folders by crawling a home directory, a volume or a cloud account.

Watched folder paths and file versions remain in SQLite. **Select folder again…** opens a native folder panel and accepts only the same configured root (including a canonical alias). Cancellation changes nothing. A different root must be added explicitly; reauthorization never deletes history or resets import identities. Native filesystem hints are checked against configured roots before walking; parent traversal and nested links are refused.

A missing/offline original can be located with **Locate original or restore access…**. This uses the existing hash-verified relink job; a different clip cannot replace the saved asset identity.

For library relocation, quit first and move the entire library folder in Finder. On relaunch, Settings → **Library location → Choose existing library…** opens a native folder panel. Selection checks the SQLite header and verifies the OpenWorld migration ledger through an immutable read-only helper before saving the preference. Unrelated, corrupt and unsupported newer databases are refused without migrations, journal files or source changes. A library already open in this app is already identified; selecting the same location can restore access. A different library is remembered for the next launch; the running database and its jobs are not moved or switched underneath the worker. The selected-library startup repeats the read-only identity check before migrations can run. Select only libraries you trust.

A remembered library starts with `--existing-library`: a disconnected drive or missing database reports `worker.library_unavailable` and never creates an empty replacement. Reconnect and select the same library to retry, or choose the moved folder and relaunch. Invalid preferences fail closed while leaving Settings available for repair. No reference source is moved; managed media and models travel with the whole canonical library folder.

These are non-sandboxed builds: configured paths and native macOS consent provide access. App Sandbox security-scoped bookmarks and background launch agents are not introduced. If macOS denies access, re-select the location and review System Settings → Privacy & Security → Files and Folders. The app does not request Full Disk Access or change OS permissions itself.

## File Provider, permissions and removable storage

- `SF_DATALESS` identifies macOS File Provider metadata without local contents, including OneDrive and iCloud. A hidden or ordinary sparse file is not a placeholder. Windows retains its offline/recall attribute checks.
- Watchers do not open dataless files or enumerate dataless directories. File counts expose cloud-only candidates; a cloud-only watched root reports `download-required`.
- Import scan, metadata snapshot and pre-probe checks refuse placeholders with retryable `media.download_required`. Download/keep the selected item locally in Finder or OneDrive, wait for completion and retry. The app never requests a cloud account or automatically downloads a capture.
- The existing ten-second size/mtime stabilization runs after local contents become available. Hashing still checks the source before/after reading. A provider changing an item mid-import yields a recoverable import failure.
- Folder errors distinguish `permission-required`, `download-required`, `offline` and other unavailability. Records remain in the database. Backoff avoids repeated errors; reauthorization bypasses the backoff and reconciles immediately.
- A disconnected volume is not deleted from settings. Reconnection triggers a scan. Persistent folder/path/size/mtime identities and asset hashes prevent duplicate imports across restarts.

## Sleep, wake, quit and crashes

AppKit workspace sleep/wake notifications enter one ordered lifecycle coordinator. Sleep pauses watchers, discards pending stabilization, closes the temporary phone gateway and stops the worker through its existing graceful shutdown. Wake restarts the worker and immediately reconciles configured watched roots, with a fresh stabilization interval. A phone token/QR code is never resumed.

Quit uses the same coordinator. A late or queued wake cannot restart the worker after shutdown. Interrupted jobs retain their recovery state; the job engine never marks incomplete work ready. Host force-quit closes the worker/gateway stdin pipes. Worker hard-kill is handled by existing supervisor restart and durable job recovery.

On macOS each media tool runs in its own guarded process session. A small bundled Python entrypoint holds a pipe from the worker; EOF kills only that owned tool process group, including shim children. Thus a SIGKILL of the worker cannot leave FFmpeg writing a partial file. Normal cancellation and timeouts retain bounded output, process-tree cleanup and argument-array execution. No daemon or launch agent is installed.

## Phone transfer and secrets

Phone transfer is off by default and requires the existing informed opt-in plus **Show QR code**. Before that action the screen explains macOS Local Network and Firewall settings, trusted Wi-Fi, keeping the firewall enabled, denial recovery, and sleep invalidating the code. `Info.plist` includes `NSLocalNetworkUsageDescription`; the macOS bundle verifier requires it.

The gateway remains a separate process on the selected private IPv4 address, with a fresh in-memory token, ten-minute expiry and existing upload validation/rate limits. The authenticated worker API remains loopback-only. Leaving the screen, closing the session, expiry, sleep or quit closes the listener; waking does not create another session. Already received imports keep their existing cleanup behavior.

No secret needs to persist: worker tokens rotate each launch and phone tokens each session. They are not written into preferences, SQLite or logs. Consequently M35 does not add a dummy Keychain item or persist a token to satisfy an integration label; `secret_store` remains `none`. Any future persistent credential must use a platform Keychain adapter. Folder/library paths are configuration, not credentials.

macOS privacy and firewall decisions must be tested with a real phone and a clean account. Unsigned development identity can change between builds; repeat consent/attribution checks after M37 supplies stable signing. Loopback tests do not establish phone connectivity or OS prompt behavior.

## Evidence and remaining validation

See the [M35 handoff](../milestones/M35-handoff.md) and [manual validation runbook](../milestones/M35-macos-validation.md). Automated fixtures prove application behavior; they do not establish real OneDrive/File Provider behavior, a physical removable-drive reconnect, TCC consent, actual sleep delivery or clean-Mac firewall permissions.

Primary API references: [Apple TN3150: dataless files](https://developer.apple.com/documentation/technotes/tn3150-getting-ready-for-data-less-files), [workspace sleep notification](https://developer.apple.com/documentation/appkit/nsworkspace/willsleepnotification), [workspace wake notification](https://developer.apple.com/documentation/appkit/nsworkspace/didwakenotification), and [Apple TN3179: local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).
