# M35 — macOS files, permissions and lifecycle

Draft PR: [#53](https://github.com/heetdalsania/openworld-moments/pull/53).

## Milestone handoff

- Milestone: M35 — macOS files, permissions, and lifecycle.
- Outcome: Implementation in progress pending final automated results and physical validation. No completion or release qualification claim. M32 and other deferred earlier-milestone validation are unchanged.
- Files and modules changed: host library selection and lifecycle coordinator; platform AppKit notifications and File Provider detection; watcher recovery/status and event containment; native reauthorization/relink and library Settings UI; phone permission guidance and Info.plist; worker cache/log configuration, import availability checks and media-tool lifetime guardian; contracts/fixtures/generated outputs; native CI fixtures; storage/interface documentation and validation runbook.
- Public contracts or migrations: Contracts **1.27**, additive optional `derived-media.storage_root` (`library` or `cache`; omission still means `library`). Existing 1.x documents remain readable. No SQL migration. Native host adds `library_location`, `library_select`, `watched_folder_reauthorize` and optional live `unavailable_reason`. macOS worker uses `--cache-dir`, `--log-dir` and, for selected existing libraries, `--existing-library`. Native selection uses `--check-library-only` to verify identity without starting an API or writing the database. Frozen worker accepts the internal media guardian entrypoint.
- Commands run: `pnpm install --frozen-lockfile`; `uv sync --all-packages --locked`; `pnpm contracts:generate`; focused Vitest/Python suites; `cargo check`, `cargo clippy --workspace --all-targets --locked -- -D warnings`, `cargo test --workspace --locked`; `mypy --platform win32/linux/darwin`; `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`; Playwright CLI synthetic UI inspection/screenshots. Final results below.
- Test and validation results: Final repository-wide run pending. Focused recovery, cache regeneration, native-host supervisor/watcher integration and UI tests passed on Apple M4/macOS 26.6.2. See evidence boundaries below.
- Decisions made: Canonical database/media/models stay in Application Support or the explicitly selected existing library. Disposable derived media uses Caches, redacted rotating logs use Logs and phone staging uses per-user temp. Atomic import/render finalization staging stays on the canonical volume. Existing library selection takes effect on relaunch; the app never moves an open database. Existing-library identity is checked read-only before preferences or migrations change. Folder reauthorization requires the same configured root and preserves import identities. Tokens remain ephemeral, so no secret needs Keychain persistence. Sleep closes phone transfer and never restores its token on wake.
- Known limitations: Real OneDrive/File Provider, physical external-drive reconnect, OS permission revocation, actual sleep/wake notification delivery, clean-account firewall/local-network consent and real-phone transfer are **pending**. Browser screenshots are synthetic, POSIX permission fixtures are not TCC consent tests, and injected lifecycle events are not physical sleep proof. macOS remains an unsigned development target. Stable signed identity/consent attribution must be rechecked after M37. Old library-local cache files are retained and new cache misses regenerate. Library relocation uses a native chooser after an owner moves the closed library in Finder; there is no automatic live-library copier.
- Follow-up milestones affected: M36 consumes the unchanged cache/media abstractions; M37 must preserve Info.plist purpose text, sign the guardian-containing worker and verify native prompt attribution; M38 builds on the new selection/recovery UX; M39 must include the physical matrix. No earlier milestone was completed or requalified.
- Screenshots, reports, or artifacts: [`docs/platforms/macos-files-and-lifecycle.md`](../platforms/macos-files-and-lifecycle.md); [`M35-macos-validation.md`](./M35-macos-validation.md). Local ignored screenshots: `output/playwright/m35-library-location.png`, `m35-watched-access.png`, `m35-phone-network.png` (real Chromium UI with a synthetic host and example paths; no footage or user library).

## Dependencies and scope

M07 [#12](https://github.com/heetdalsania/openworld-moments/pull/12), M10 [#15](https://github.com/heetdalsania/openworld-moments/pull/15), M33 [#51](https://github.com/heetdalsania/openworld-moments/pull/51) and M34 [#52](https://github.com/heetdalsania/openworld-moments/pull/52) are merged. Work starts from M34 merge `c599986c6a148d411a0041eea5819e527363707f`. The owner explicitly permits proceeding while unrelated earlier physical/Windows validation remains deferred. None of those results are changed by M35.

## Evidence boundaries

| Evidence | Result |
|---|---|
| Native Rust compile/clippy and real supervisor/watcher E2E | Passed locally; final repository run recorded below |
| Synthetic coordinator sleep/wake, closed phone listener, no late-wake restart | Passed locally |
| Watcher restart/wake and Unicode/long-path fixtures, no duplicate reports | Passed locally |
| Cloud metadata fixture and local chmod permission loss/recovery | Passed locally; not a real provider or TCC prompt |
| Worker SIGKILL/restart and media-runner parent SIGKILL cleanup | Passed locally; real local subprocess termination with synthetic work |
| Cache deletion/regeneration, source immutability | Passed locally with FFmpeg and a generated synthetic clip |
| Native selectors | Routing and cancellation/error cases tested; real panel permission behavior pending |
| Hosted native Apple Silicon/Intel CI | Pending PR CI |
| Physical OneDrive/external drive, actual sleep and clean-account phone/firewall | Pending [runbook](./M35-macos-validation.md) |

## Validation results

Final results will be recorded before handoff. The ledger remains **In progress** until all M35-required validation is satisfied.
