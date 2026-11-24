# M32 — Windows public alpha qualification report

**Release:** OpenWorld Moments `0.1.0-alpha.32` for Windows 11 x64 · tag `v0.1.0-alpha.32`
(created by GitHub when the maintainer publishes the draft) · prepared 2026-11-23.

**Overall result: qualified by maintainer decision, as a draft release.** Every automated
gate passes, and the hosted Windows runner installs and exercises this exact installer.
The clean-machine Windows checks were **waived by the maintainer** because no Windows PC
was available. The existing clean-machine evidence is the
[M29 client report](./M29-windows-client-report.md) for the earlier `0.1.0-alpha.29`
build. The waived checks are listed in [Waivers](#waivers) and collected in the
non-blocking [M40 section E](./M40-windows-deferred-verification.md#e-windows-public-alpha-m32).
**No clean-machine pass of `0.1.0-alpha.32` is claimed.**

## 1. Release-candidate freeze

| Item | Frozen value |
|---|---|
| Base | `main` at `ccb1b79` (M36 merged), then `cdc9b68` (M37 work in progress, PR #58) merged in, plus the M32 branch ([PR #57](https://github.com/heetdalsania/openworld-moments/pull/57)) |
| Installer version | `0.1.0-alpha.32` in `apps/desktop/src-tauri/tauri.packaged.conf.json`, now the only place it is written |
| Library schema | 19 (`0019_model_downloads.sql`; no migration since M29) |
| Contracts | 1.27 |
| Detector SDK / story generator | 1.3.0 / `owm-story` 1.0.0 |
| Profiles | `generic-wanted`, `generic-text`, `generic-audio`, `generic-open-world`, all 1.0.0, synthetic only; `open-world-vi` and `gta-v` unvalidated placeholders |
| Speech-model catalog | `models.json` SHA-256 `9f21f0e0483430117222f1fc658a9a0e30fdfee947f13699872fc56220262159` (Ed25519-signed): whisper.cpp `tiny.en`, `base.en` at `5359861c739e955e79d9a303bcbc70fb988958b1`, MIT, download-only |
| Bundled runtime | CPython 3.12.14 (python-build-standalone 20260929), PyInstaller 6.22.3, uv 0.13.7, FFmpeg/FFprobe 9.0.2 GPL with libx264 (unchanged from M29; `scripts/windows/sources.json` SHA-256 `bd038f6ac8ef0c48df2728528337f6da237b43d4492e0a6aac70c0cedb6f1af6`) |
| `uv.lock` | `844e61ac5df000b8684d4b68a4c698f0597cf57a0b26a28c7bb7b09820421d09` |
| `pnpm-lock.yaml` | `dd4b3a70fef7e327fe0c53e9409f0fd1eb3adc12e53e4679321044f47a22c65f` |
| `Cargo.lock` | `fa0bcde5919dec3c0826e499a2aa383e2c0b0823000ed027b6ec5e5f6649b70e` (M32 updates `cookie` 0.18.2 → 0.18.3 for [RUSTSEC-2026-0594](https://rustsec.org/advisories/RUSTSEC-2026-0594.html)) |
| Rust toolchain | 1.97.1 (`rust-toolchain.toml`) |

The FFmpeg sources and build script did not change, so the media build is the one
qualified on Windows 11 hardware in M29. M30 deferred a neutral FFmpeg build-path prefix
to M32. It is **not** applied: changing it would rebuild the binaries M29 qualified, and
no Windows machine is available to qualify new ones. The public CI path left in the
FFmpeg binaries stays a documented accepted risk (`security/artifact-scan-exceptions.json`).

## 2. Milestones and handoff evidence

| Milestone | PR | Merge commit | Handoff |
|---|---|---|---|
| M20 Story engine | [#26](https://github.com/heetdalsania/openworld-moments/pull/26) | `a53b2aa` | [M20](./M20-handoff.md) |
| M23 Captions and audio | [#29](https://github.com/heetdalsania/openworld-moments/pull/29) | `ac3bff9` | [M23](./M23-handoff.md) |
| M25 Vertical layouts | [#31](https://github.com/heetdalsania/openworld-moments/pull/31) | `ba4b21b` | [M25](./M25-handoff.md) |
| M26 Search and collections | [#32](https://github.com/heetdalsania/openworld-moments/pull/32) | `d54f930` | [M26](./M26-handoff.md) |
| M27 Open exports | [#33](https://github.com/heetdalsania/openworld-moments/pull/33) | `0301fd4` | [M27](./M27-handoff.md) |
| M28 Privacy review | [#34](https://github.com/heetdalsania/openworld-moments/pull/34) | `6e9410a` | [M28](./M28-handoff.md) |
| M29 Windows packaging | [#35](https://github.com/heetdalsania/openworld-moments/pull/35), [#36](https://github.com/heetdalsania/openworld-moments/pull/36), [#37](https://github.com/heetdalsania/openworld-moments/pull/37) | `5ca9d27`, `2a3cf92`, `c1a9bd7` | [M29](./M29-handoff.md), [client report](./M29-windows-client-report.md) |
| M10 phone fix | [#38](https://github.com/heetdalsania/openworld-moments/pull/38) | `2d52182` | M29 handoff |
| M30 Security and SBOM | [#39](https://github.com/heetdalsania/openworld-moments/pull/39) | `fff5466` | [M30](./M30-handoff.md) |
| M31 Accessibility and docs | [#40](https://github.com/heetdalsania/openworld-moments/pull/40) | `ecf30c5` | [M31](./M31-handoff.md) |

All are ancestors of `ccb1b79`. M00–M19, M21, M22, M24 and M33–M36 are also merged.

**Release-blocking issues:** none. The repository had no open issues on 2026-11-23. M32
found two blockers and fixed both in this branch:

- **RUSTSEC-2026-0594**, published that day, failed the Security scans gate. Fixed by
  updating `cookie` to 0.18.3.
- **CRLF `checksums.txt`.** Re-downloading the first draft showed that the Windows build
  wrote `checksums.txt` with CRLF line endings. `shasum -c` / `sha256sum -c` on macOS
  and Linux, as documented in `VERIFY.md`, read the carriage return as part of each file
  name and failed. This affected every candidate since M29. `artifacts.py` now writes
  LF; `release_check.py` refuses CRLF; and the packaging test asserts LF on the Windows
  CI runner too.

## 3. Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Every required milestone merged with handoff evidence; no release-blocking issue open | **Met** | Section 2 |
| A clean-machine user completes import, session reconstruction, event review, edit and both aspect-ratio renders | **Waived by maintainer decision** | Not run on clean Windows 11 hardware. Partial evidence: M29 clean client (import, session, project/trim, privacy review, 16:9 render with alpha.29); hosted Windows CI with this installer (import, session, project, privacy review, **16:9 and 9:16 renders**; event review is covered by automated browser/worker tests only). Deferred to M40 E |
| Release notes distinguish tested facts, experimental features and unsupported claims | **Met** | [Release notes](../releases/0.1.0-alpha.32/release-notes.md), sections *Tested facts*, *Experimental*, *Not claimed* |
| No GTA VI compatibility claim without profile version, fixture description and metrics | **Met** | No claim is made; [publication rule](../releases/0.1.0-alpha.32/detector-metrics.md#publication-rule); trademark review (section 6) |
| Downloaded artifacts match published checksums and produce the documented version report | **Met for the CI download; post-publication download waived** | `release_check.py verify-artifacts` on the downloaded CI set (section 5): every file matches `checksums.txt`, and the runtime inventory, SBOM and native smoke reports (the installed app's `app_info`) all report `0.1.0-alpha.32`. Download from the published release page deferred to M40 E |
| Rollback and data-migration constraints documented before publication | **Met** | [Publication, rollback and triage](../releases/0.1.0-alpha.32/rollback-and-triage.md) |

## 4. Required validation

| Validation | Status | Evidence |
|---|---|---|
| Full CI | **Pass** | Section 5 |
| Clean-machine matrix | **Waived** | Section 7 |
| Release artifact verification | **Pass** | Section 5; SBOM verified against every packaged file and the release checksums in CI; artifact secret/path scan in CI |
| Accessibility smoke test | **Automated pass; Windows screen-reader smoke waived** | Desktop accessibility tests (keyboard paths, live regions, themes, 200% text, reduced motion) in `pnpm check`; Narrator/NVDA waived in M31, still in M40 B |
| Security checklist | **Pass with one maintainer action** | Section 6 |
| Fixture licence/consent audit | **Pass** | [Detector metrics — audit](../releases/0.1.0-alpha.32/detector-metrics.md#fixture-licence-and-consent-audit) |
| Trademark wording review | **Pass** | Section 6 |
| Post-publication install and end-to-end smoke from the GitHub release | **Waived (deferred)** | M40 E; the release is not published by M32 |

## 5. Automated gates and artifact verification

### Local full gate (Apple M4, macOS)

`OWM_REQUIRE_FFMPEG=1 pnpm check` on the release-candidate tree: format, lint (ESLint,
Clippy, Ruff, REUSE), type checks (tsc, mypy), tests and contract drift all pass.

| Suite | Result |
|---|---|
| Worker (pytest) | 1,282 passed, 42 skipped: the OCR tests (Tesseract is not installed on this Mac; CI runs them with `OWM_REQUIRE_OCR=1`) and one Windows-only junction test |
| Python contracts | 368 passed |
| TypeScript contracts | 401 passed |
| Desktop (Vitest) | 294 passed |
| Rust | 77 passed |
| Release tooling (`tests/release`, part of the worker suite) | 27 passed (26 at the full local gate, plus the CRLF case added afterwards; all 27 also pass on the Windows CI runner) |

Worker mypy also passes for `--platform win32`.

### CI ([run 45325432445](https://github.com/heetdalsania/openworld-moments/actions/runs/45325432445), PR #57 head `ae4683c`, after merging `main` with M37)

`release_check.py ci-summary` on `gh run view --json ...` output: **ok**. All 12 jobs
succeeded: TypeScript (Linux); Python and Rust on Ubuntu and Windows (OCR and FFmpeg
required); contracts drift check; Security scans (pip-audit, cargo-audit, pnpm audit,
gitleaks, licence policy); REUSE; DCO; macOS arm64 and x86_64 builds; and
**Desktop production build (Windows)**. CodeQL (Python, TypeScript, Actions) passed in
its own workflow.

The Windows job, on hosted `windows-2025`, did the following with this installer:

- froze the worker twice with identical payload hashes;
- built the NSIS installer and installed it into a Unicode path, with the development
  overrides pointing at missing tools;
- drove the installed WebView2 app (Edge 157) through first-run setup, the system
  check, a synthetic import, playback preparation, session grouping, a project,
  privacy review, and the **16:9 and 9:16 renders**;
- repaired, upgraded to the test-only `0.1.0-alpha.32.1`, and uninstalled, keeping the
  library and leaving the database byte-identical;
- generated the SBOM and verified it against all packaged runtime files (1,829) and
  `checksums.txt`, and scanned the release for secrets and build paths.

PR builds are not attested; attestation happens on the `main` run after merge.

### Downloaded release set

`gh run download 45325432445 -n Windows-x64-alpha-candidate`, then
`release_check.py verify-artifacts --version 0.1.0-alpha.32`: **ok**, every check passed.

- Exactly one installer, of the expected version.
- Every file is listed in `checksums.txt` and matches it.
- The version report is consistent:
  - `runtime-inventory.json` application `0.1.0-alpha.32`;
  - the SBOM root component `0.1.0-alpha.32` (2,155 components);
  - the installed app's `app_info` in `native-import-render.json` and
    `native-repair.json`: `0.1.0-alpha.32`, stage "unsigned alpha candidate";
  - `native-upgrade.json`: `0.1.0-alpha.32.1`;
  - `reproducibility.json`: frozen payload identical.

The inventory records commit `5098ebd`, GitHub's merge of the PR head into `main`.

`shasum -a 256 -c checksums.txt` on macOS also passes for every file (LF line endings).
The draft's assets were downloaded again from the release and passed the same checks.

The draft's assets come from run 45325432445 at PR head `ae4683c`, and the draft targets
that commit. Every later commit on this branch only changes M32 documents (this report and the
handoff), not any build input.

These are the files attached to the draft release (to be replaced by the attested `main`
build before publishing, section 8):

| File | Bytes | SHA-256 |
|---|---:|---|
| `OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe` | 40,979,874 | `1b61cf9e699703cb1ed0f784c8b97ba89ccf3ecf7668a93b642e214b13bb4b0c` |
| `SECURITY.md` | 2,782 | `c8c25db16760acdb0d62c5bdfb9efeb94ce182d2d82eca3f4f67bf3559417418` |
| `THIRD_PARTY_NOTICES.txt` | 424 | `4367d39b60d7571d5a6088d329b0a91cbcbec5d172004cdaa0a5e21045668f70` |
| `VERIFY.md` | 3,518 | `ec36e0068eeb55ef20d068c6a7b7283479aae6db6ad1a3d01dcd4fa62a6bf23c` |
| `build-media.sh` | 1,483 | `8f594994fb83217704424291014add6fa336fe6fa538040e07ec6e9ef185ae8a` |
| `build-packages.txt` | 2,339 | `63ed169bdcbc135595493f7af052410bc24c38299ffaf6baaa68ceb770cacbd1` |
| `checksums.txt` | 1,840 | `74ad1a7bc9c2b04ccfd42e1dff10341519f589cf7c06658f2a035b65b67dc01a` |
| `compiler.txt` | 253 | `7091e6a9e7da9f7119dba5d159300d5639e3cfc711974dc5c1bb12492220e3ac` |
| `ffmpeg-9.0.2.tar.xz` | 12,040,788 | `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` |
| `freeze-worker.py` | 4,682 | `9af907feed0a57019a76056521c6136ad5dd22ee7cf6a8c36173fe351a42efdf` |
| `native-import-render.json` | 3,565 | `484e9fac6a6f77114e10e9a09432322150bf70f2b78fba1ca760c758c9426d96` |
| `native-repair.json` | 3,558 | `aea30e18749eefe691e5a72e26596f7d70ade8a4e39c66e63b2e83a8d65fb94a` |
| `native-uninstall.json` | 285 | `49b73b1ee0cb436a35d7e1c4ee2507442722e57773a38e0937e14b3dacc6700c` |
| `native-upgrade.json` | 3,561 | `b964cb3ca3e0ee7caf0e784a8ec81b47a55c55b9988c81b786796651fada9c79` |
| `python-notices.json` | 2,992 | `e5c8dad8728045a378dedf4c6da97aeefb614bec73b3dc680a30f4649c5fdcaf` |
| `reproducibility.json` | 103 | `66d2722c48a757a4471de423a27a850cd5b2d4a10f9109bfba6e1fbd0edc982e` |
| `runtime-inventory.json` | 243,959 | `5279ec1046e2f4fd27de913ac3640d04d2c2ec1d724d7af09f9252c66b040f50` |
| `runtime-notices.zip` | 1,831,041 | `1522e7411ce1da88a56879ea7bb78615ac5eaa1eab539f4ba761fe096153f751` |
| `runtime_bundle.py` | 9,273 | `ffac4b3a0a3123a24f4476ecdf4d6d691bc30e01d064b6594a421271196bf94d` |
| `sbom.cdx.json` | 802,044 | `70e2c4bbca0ea9e039cdb68c3a2efa8b47331805df21398c3ecb98d482ed42fe` |
| `sources.json` | 627 | `bd038f6ac8ef0c48df2728528337f6da237b43d4492e0a6aac70c0cedb6f1af6` |
| `x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz` | 1,035,587 | `090d730e867fc63631782a1287974635d1237d0fa7c6fd1d09fd543620a56689` |

## 6. Security, privacy and trademark review

- **Threat model:** [threat model](../security/threat-model.md) re-read for this
  release. M32 changes no runtime code path, network surface or file handling. Its
  only product change is the version number; packaging and test scripts gained the
  vertical render in the hosted smoke and a release verifier that reads local files only.
- **Dependencies:** pip-audit, cargo-audit and pnpm audit run in the CI *Security
  scans* job. RUSTSEC-2026-0594 (`cookie` private-jar nonce reuse after `fork()`; the
  app never forks and never uses private jars, and Windows is unaffected) is
  nevertheless fixed by updating to 0.18.3, so no exception is needed. Remaining warnings
  are informational: `glib` (unsound) and `proc-macro-error` (unmaintained) in the Linux
  GTK stack only, and `chrono` (unmaintained, RUSTSEC-2026-0543).
- **Secrets, licences, CodeQL:** gitleaks over full history, the licence policy and
  CodeQL (Python, TypeScript, Actions) pass.
- **Release set:** SBOM verified against the runtime and checksums, artifact scan clean
  apart from documented upstream-path exceptions, provenance attested on `main` builds.
- **Privacy:** [privacy statement](../releases/0.1.0-alpha.32/privacy-statement.md)
  checked against the code: model downloads are limited to `huggingface.co`/`*.hf.co`
  HTTPS origins and redirects; the phone gateway is opt-in and LAN-only; diagnostics are
  saved locally after preview; no telemetry exists.
- **Maintainer action before publishing:** GitHub *private vulnerability reporting* is
  **disabled** (checked 2026-11-23 with the repository API). M32 did not change
  repository settings; `SECURITY.md` documents the interim route.
- **Trademark wording:** the only such string in the desktop UI is its footer
  disclaimer, "Unofficial community project. Not affiliated with or endorsed by
  Rockstar Games."; no "GTA" or "Grand Theft Auto" text appears. The release notes and guides use them only in factual
  no-compatibility and no-affiliation statements; the app icon and screenshots contain
  no game assets. The unofficial/no-affiliation disclaimer opens the release notes.

## 7. Clean-machine matrix

| Check | `0.1.0-alpha.29` clean client (M29) | `0.1.0-alpha.32` hosted CI (windows-2025) | `0.1.0-alpha.32` clean client |
|---|---|---|---|
| Download and checksum verification | Pass | Pass (`release_check.py`) | Waived → M40 E |
| Install without elevation (per-user) | Pass (admin account, UAC on; no prompt) | Pass (silent, Unicode path) | Waived → M40 A/E |
| SmartScreen on a browser download | Not observed (`gh` download has no Mark-of-the-Web) | n/a | Waived → M40 A/E |
| First-run system check | Pass | Pass | Waived |
| Import, playback preparation | Pass | Pass | Waived |
| Session reconstruction | Pass | Pass | Waived |
| Event review | Not in M29 scope | Automated tests only | Waived |
| Project edit (trim) and privacy review | Pass | Pass (project + review) | Waived |
| 16:9 render | Pass (played in Media Player) | Pass | Waived |
| 9:16 render | Not in M29 scope | Pass (new in M32) | Waived |
| Model download, resume, cancel, remove | Pass (cancel UI defects fixed in #37) | Catalog only, no download | Waived → M40 A |
| Repair, upgrade, uninstall retention | Pass (6.2/6.3 by maintainer decision) | Pass | Waived → M40 A |
| Phone transfer | One video passed; second failed, fixed in #38 | Automated | Waived → M40 A |
| Standard (non-admin) account | Not run | n/a | Waived → M40 A |
| Narrator / NVDA | Not run | n/a | Waived → M40 B |
| Current Xbox / PlayStation transfer steps | Not run | n/a | Waived → M40 E |

## 8. Published artifact hashes

The draft release carries the set built by the PR's CI (section 5). Pull-request builds
are not attested, so before publishing the maintainer replaces the assets with the
attested set from the `main` CI run of the merge commit and verifies it with the same
tool ([procedure](../releases/0.1.0-alpha.32/rollback-and-triage.md#1-publishing-the-draft-maintainer-only)).
The checksums in the published release are authoritative; add them here when the release
is published.

## 9. Tag and commit

- The draft release names tag `v0.1.0-alpha.32`. GitHub creates it at publication on the
  draft's target, which the procedure moves to the merge commit. The tag is a
  lightweight, unsigned tag; integrity comes from the attested build provenance and the
  checksums, as described in `VERIFY.md`. Commits are DCO signed-off, not GPG-signed.
- The release is a **pre-release** and is not marked latest.

## Waivers

By maintainer decision (2026-11-23), because no Windows machine was available:

1. All clean-machine Windows 11 checks of `0.1.0-alpha.32` (section 7).
2. The post-publication install and end-to-end smoke test from the GitHub release.
3. Live validation of the Xbox and PlayStation transfer guides.

These are recorded in [M40 section E](./M40-windows-deferred-verification.md#e-windows-public-alpha-m32)
together with the earlier M29/M31 waivers (sections A and B). M40 gates no release.

## Follow-up issues

- M40 A, B and E on a physical Windows 11 PC (non-blocking).
- Enable private vulnerability reporting (repository owner).
- Replace the draft's PR-built assets with the attested `main` set, then publish (maintainer).
- Neutral FFmpeg build prefix with a Windows requalification (carried from M30; accepted risk).
- Authenticode signing once a certificate is procured (accepted risk).
- Real-gameplay detector evaluation for any game before a compatibility claim.
- M39 qualifies the combined Windows and macOS release.
