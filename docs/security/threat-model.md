# Threat model and abuse-case checklist (M30)

This updates spec section 14.1 for the Windows alpha as built through M29. It lists
the trust boundaries, then every abuse case we considered, with the control, the
evidence that the control works, and a status. It is a manual review backed by
automated tests and scans, not a penetration-test certification.

Status meanings: **Resolved** (control in place and tested), **Mitigated** (reduced,
residual risk documented), **Accepted** (documented risk, no change planned now),
**Open** (needs evidence or work, with an owner milestone).

## Assets

User footage and the library (originals are never modified); transcripts, OCR text
and project text; the user's file-system paths; the local API token; the LAN upload
token; downloaded models; release artifacts and the build pipeline that makes them.

## Trust boundaries

```text
 [Phone on the LAN] --(B3: tokenised HTTP, only while the screen is open)--> [Phone gateway process]
                                                                                   | staging folder only
 [Web view (UI)] --(B1: Tauri IPC, allowlisted)--> [Rust host] --(B2: loopback HTTP + token)--> [Worker]
                                                       |                                             |
                                 native save dialogs --+          (B4: untrusted media) --> FFmpeg/FFprobe, OCR, parsers
                                                                  (B5: model catalog/downloads) --> HTTPS
 [Build pipeline: GitHub Actions] --(B6: lockfiles, pinned actions, SBOM, attestation)--> [Release artifacts]
```

- **B1 Web view → host:** the UI is untrusted for privileges. It can only invoke
  named commands. HTTP goes through `worker_api`, whose route allowlist validates
  methods, IDs and query strings. File writes happen through host-owned native save
  dialogs with fixed extensions and exclusive creation. There is no shell plugin, and
  the CSP forbids inline and remote scripts.
- **B2 Host → worker:** a loopback-only API with a per-launch 256-bit token passed on
  stdin, a Host-header allowlist (DNS rebinding), a loopback-peer check and bounded
  request bodies. The WebSocket requires the Authorization header, which browsers
  cannot set cross-site.
- **B3 Phone → gateway:**
  - a separate process, off by default and started only by the Import from phone
    screen, bound to one chosen private address;
  - a 256-bit token with a 10-minute expiry; it ends with the screen or on "I'm
    done";
  - Host allowlist, Origin check, per-address rate and lockout limits, an attempt
    cap, and file size, count, total and free-space limits;
  - streamed exclusive writes into a session staging folder under sanitized names;
  - no route to the library or the desktop API.
- **B4 Media → tools:** every file is untrusted. Tools receive argument arrays and
  never a shell, with timeouts, capped output, cancellation that kills the whole
  process tree, owned staging and derived folders, and read-only originals. The
  bundled FFmpeg is built with network protocols and autodetected libraries disabled.
- **B5 Models:**
  - downloads happen only on explicit user action;
  - they come from an Ed25519-signed catalog that pins URL, revision, size and
    SHA-256;
  - resumes are range-checked;
  - nothing activates until the hash matches;
  - no weights are bundled.
- **B6 Build and release:**
  - locked dependencies (uv.lock, Cargo.lock, pnpm-lock.yaml), pinned actions, and
    checksum-verified tool downloads;
  - FFmpeg and x264 built from pinned, hashed sources;
  - SBOM and checksums for every artifact, and provenance attestations for `main`
    builds;
  - secret, vulnerability, license and static-analysis gates.

## Abuse cases

### Local API and desktop (B1, B2)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| L1 | Another local process or a web page calls the worker API | Loopback bind, per-launch token, Host allowlist, peer check | `tests/worker/test_api.py`, `test_process.py` (non-loopback refused) | Resolved |
| L2 | DNS rebinding from a browser to the loopback port | Host-header allowlist | `test_unexpected_host_header_is_rejected` | Resolved |
| L3 | Cross-site WebSocket hijack of job events | Token must be in the Authorization header | `test_websocket_requires_the_token` | Resolved |
| L4 | Oversized or unbounded request bodies exhaust memory | 32 MiB cap, chunked bodies refused (M30) | `test_request_bodies_are_bounded` | Resolved |
| L5 | UI asks the worker for an arbitrary route or path | Host route allowlist validating methods, IDs and queries | `apps/desktop/src-tauri/src/media.rs` tests | Resolved |
| L6 | UI writes files where it chooses | Host-owned save dialogs, fixed extensions, exclusive create, no overwrite | `calibration::write_export` tests, `export_filename` tests | Resolved |
| L7 | Token leaks into logs or support output | Redactor on stderr tails and logs | `tests/test_redaction.py`, `test_tokens_and_environment_secrets_never_reach_logs` | Resolved |
| L8 | Malware already running as the user reads the library or token | Out of scope: same-user code is trusted by the OS | — | Accepted |

### Phone upload (B3)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| P1 | Gateway reachable when the user is not uploading | Process runs only while the screen is open; closes on expiry, finish or leaving | `test_process_serves_only_while_active`, M29 Windows run 8.4 | Resolved |
| P2 | Guessing the token | 256-bit token, constant-time compare, identical 404s, per-address lockout after 20 failures, session ends after 1,000 (M30) | `test_wrong_tokens_and_unknown_paths_look_the_same`, `test_wrong_tokens_lock_out_that_address`, `test_mass_guessing_ends_the_session_safely` | Resolved |
| P3 | Replaying a token after expiry or finish, or in a new session | Expiry, finished state, and a fresh token per session | `test_expired_and_finished_sessions_refuse_everything`, `test_a_finished_sessions_token_cannot_be_replayed` | Resolved |
| P4 | Another website in the phone's browser forges uploads | The token in the path is unknown to other sites; Origin must match the gateway for state changes (M30) | `test_state_changes_from_another_origin_are_refused` | Resolved |
| P5 | Path traversal or device names via the file name | One sanitized component; reserved names, controls and bidi overrides replaced (M30) | `test_names_are_reduced_to_one_safe_component`, `test_hostile_names_become_one_safe_component` | Resolved |
| P6 | Oversized, disguised or non-video uploads | Extension, magic-byte sniff, size, count, total and free-space checks; refused files deleted | `test_unsupported_and_disguised_files_never_stay`, `test_oversized_and_over_limit_uploads_are_refused_before_writing`, `test_gateway_uploads_stay_in_staging` | Resolved |
| P7 | Flooding requests or retrying rejected uploads | 120 requests/min per address; 300 attempts per session (M30) | `test_request_flood_is_throttled_per_minute`, `test_rejected_retries_are_capped` | Resolved |
| P8 | Slow-loris uploads hold the session | 60 s read timeout, two concurrent uploads at most | `test_interrupted_upload_leaves_nothing`, `test_concurrent_upload_limit` | Resolved |
| P9 | Eavesdropping on a shared network (plain HTTP) | Desktop warns about trusted networks; short-lived token; video-only, write-only | Phone guide, M10 UI | Accepted (no TLS on LAN in the alpha) |
| P10 | A standard (non-administrator) Windows user meets the firewall prompt | Not verified: the M29 run used an administrator account | M40 | **Open (M40)** |
| P11 | The second-upload "out of space" fix (#38) on real Windows | Regression tests on both sides | `test_upload_after_staging_folder_was_tidied`, Rust `imports_keep_a_live_session_folder`; Windows retest waived | **Open (M40)** |

### Media parsing and tools (B4)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| M1 | Crafted media crashes or hangs a parser | Separate tool processes, timeouts, capped stdout and stderr tails, stable error codes | `tests/media/test_fuzz_corpus.py` (structural cases, truncations, 40 seeded mutants), `test_probe_job.py`, `test_process.py` | Mitigated |
| M2 | User-controlled text becomes a shell command | Argument arrays everywhere; Ruff S-rules; repository AST guard; no shell plugin | `test_no_python_code_runs_a_shell`, `test_desktop_never_spawns_a_shell`, render argv tests | Resolved |
| M3 | Cancelled tools keep running (e.g. behind a launcher shim) and hold files | Cancel kills the process tree (M27) | `test_cancel_kills_tools_started_through_a_shim` | Resolved |
| M4 | Paths escape the library or staging | Resolved-path checks, managed copies and staging under the library, junction and symlink refusal | `tests/media/test_import.py`, `test_paths.py`, `test_import_never_writes_outside_the_library` | Resolved |
| M5 | A malicious file name leaks the user's paths into errors | Probe errors and stderr tails redact the file path | `test_probe_handles_every_malformed_file` | Resolved |
| M6 | FFmpeg vulnerabilities | Minimal static build (network protocols and autodetect off), pinned 9.0.2; FFmpeg is not covered by PyPI/RustSec/npm audits | Manual check of FFmpeg security advisories at each release | Mitigated (manual tracking) |
| M7 | Memory exhaustion by a pathological file | Timeouts and output caps; no per-process memory limit | — | Accepted |

### Models and updates (B5)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| U1 | Tampered or substituted model download | Signed catalog, pinned SHA-256 and size, range-checked resume, no activation before verification | `tests/transcripts/test_downloads.py` | Resolved |
| U2 | A model with unclear redistribution rights | Catalog records license and source; only MIT whisper.cpp models | SBOM `machine-learning-model` entries | Resolved |
| U3 | A malicious update | No auto-update (out of scope); users install verified packages by hand | `release-verification.md` | Accepted |

### Build, release and artifacts (B6)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| S1 | A known-vulnerable dependency ships | `audit_dependencies.py`: pip-audit (runtime closure), cargo-audit, `pnpm audit --prod`, with a reviewed exception file | CI "Security scans" job | Resolved (0 known vulnerabilities at M30) |
| S2 | Secrets committed to the repository | gitleaks over the full history with narrow, reviewed allowlists | CI "Security scans" job | Resolved |
| S3 | Secrets or private paths in release artifacts | Artifact scanner over the release, runtime and desktop binary; build logs redacted, `config.log` not shipped; Rust paths remapped | `scan_artifacts.py` in the Windows job | Mitigated (see accepted exceptions) |
| S4 | A dependency with an incompatible license ships | `check_licenses.py` on the live closures and the SBOM | CI "Security scans" and Windows jobs | Resolved |
| S5 | Artifacts don't match their description | SBOM regenerated and compared; every packaged file re-hashed; checksums verified | `verify_sbom.py` in the Windows job | Resolved |
| S6 | A tampered or substituted installer | Checksums plus a GitHub provenance attestation for `main` builds | `release-verification.md` | Mitigated (unsigned until signing is procured) |
| S7 | Insecure code patterns or workflow injection | CodeQL (Python, TypeScript, Actions) plus Ruff S, Clippy and ESLint | `codeql.yml`, CI | Resolved |
| S8 | A compromised third-party action | Actions pinned to exact versions (MSYS2 by commit SHA); minimal permissions | `ci.yml` | Mitigated |

### Privacy (spec 14.3)

| # | Abuse case | Control | Evidence | Status |
|---|---|---|---|---|
| X1 | Exports leak absolute paths | Only on explicit opt-in, and only in formats that reference media (M27) | `test_no_absolute_paths_unless_explicitly_requested` | Resolved |
| X2 | Telemetry or crash upload | None exists | Code review; no analytics dependencies in the SBOM | Resolved |
| X3 | Plugins run arbitrary code | Plugins deferred | — | Resolved (not built) |

## Accepted risks and exceptions

1. **Upstream build paths in third-party binaries.** The CPython runtime (with
   OpenSSL, libffi and SQLite) and Rust-based wheels embed their upstream build
   machines' paths. They contain no personal data or secrets.
   (`security/artifact-scan-exceptions.json`)
2. **CI workspace path in FFmpeg/FFprobe.** The public GitHub Actions workspace path
   appears in the embedded configure line. A neutral build prefix needs a rebuild and
   requalification of the qualified binaries, so it moves to the M32 release build.
3. **Linux-only Rust advisories.** `glib` 0.18.5 (RUSTSEC-2024-0429, unsound) and
   `proc-macro-error` 1.0.4 (RUSTSEC-2024-0370, unmaintained) come from Tauri's
   Linux GTK stack. They are not in the Windows package (verified with `cargo tree`).
4. **No TLS on the LAN gateway (P9), no per-process memory limit (M7), no automatic
   update (U3), and an unsigned installer (S6).** Each is documented above.

## Open items

- **P10 and P11:** Windows evidence for a standard user and the #38 fix (M40,
  non-blocking).
- **Private vulnerability reporting:** GitHub's private reporting must be enabled by
  the repository owner. Until then, use the interim route in `SECURITY.md`.
- **FFmpeg advisories (M6):** checked manually per release; no automated feed.
