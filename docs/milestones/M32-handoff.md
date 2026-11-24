## Milestone handoff

- Milestone: M32 — Windows public alpha qualification
- Outcome: **Complete by maintainer decision; draft release only.** The
  `0.1.0-alpha.32` release candidate is frozen, qualified by every automated gate and
  by the hosted Windows install/run/uninstall smoke. The GitHub pre-release
  `v0.1.0-alpha.32` is a **draft** with the CI-built Windows release set attached; it
  was not published, not marked latest and not posted anywhere. The maintainer
  waived the clean-machine Windows checks and the post-publication smoke test (no
  Windows PC available); they are listed in the
  [qualification report](./M32-windows-qualification-report.md#waivers) and in the
  non-blocking [M40 section E](./M40-windows-deferred-verification.md#e-windows-public-alpha-m32).
  No clean-machine pass of this build is claimed.
- Files and modules changed:
  - **Release candidate:** `apps/desktop/src-tauri/tauri.packaged.conf.json` →
    `0.1.0-alpha.32`. New `scripts/windows/release_version.py` makes that file the only
    place the version is written. `artifacts.py`, `freeze-worker.py`,
    `native-smoke.py`, `lifecycle-smoke.ps1` and the CI upgrade-test staging step read
    it, and the upgrade test uses `<version>.1`. Before this, the version was repeated
    in seven places.
  - **Packaged smoke:** `scripts/windows/native-smoke.py` also renders the 9:16 preset
    (`vertical-1080x1920-30`, layout reviewed) and checks that both renders are ready.
  - **Release tooling:** new `scripts/release/release_check.py`:
    - `verify-artifacts`: completeness, checksums both ways, one installer of the
      expected version (never the upgrade-test build), and version agreement across
      the inventory, SBOM and native reports;
    - `ci-summary`: every job in a `gh run view` result succeeded.
  - **Tests:** `services/media-worker/tests/release/test_release_check.py` (27 tests:
    success, tampering, missing/unlisted files, wrong versions, malformed and CRLF
    checksums, links/folders, CLI exit codes, CI summaries, triage labels, no
    hard-coded version left in Windows scripts). The packaging assembly test now proves the upgrade-test
    installer is excluded. mypy covers `scripts/release`.
  - **Release documents** (`docs/releases/0.1.0-alpha.32/`): release notes (the draft's
    text), compatibility matrix, detector metrics with fixture licence/consent audit,
    privacy statement, and publication/migration/rollback/triage.
  - **Milestone documents:** [qualification report](./M32-windows-qualification-report.md),
    this handoff, and M40 section E.
  - **Triage:** `.github/labels.json` (adds `detector` and `milestone`, which the
    issue templates already used but the repository lacked, plus the release labels).
  - **Updated docs:** compatibility and known-limitations guides (new alpha.32 section),
    `SECURITY.md`, release verification, security README, Windows packaging,
    README status/next step, and the ledger.
  - **Prerequisite repair (called out per AGENTS.md):** `Cargo.lock` updates `cookie`
    0.18.2 → 0.18.3. RUSTSEC-2026-0594 was published on 2026-11-23 and failed the
    Security scans gate on this branch. The release must ship with no open
    vulnerability. No code changes.
  - **Prerequisite repair:** `scripts/windows/artifacts.py` writes `checksums.txt` with
    LF line endings. Before, CRLF from Windows text mode broke the documented
    `sha256sum -c` / `shasum -c` verification on macOS and Linux (since M29). This was
    found by downloading the first draft's assets. The first draft's assets were
    replaced.
- Public contracts or migrations: none. Contracts stay at 1.27; the schema stays at 19.
  The release set's file list is unchanged except for the version in the installer name.
- Commands run: `OWM_REQUIRE_FFMPEG=1 pnpm check`; worker `ruff`, `mypy` (darwin,
  win32); `cargo update -p cookie`; CI on PR #57; `gh run download` of the
  `Windows-x64-alpha-candidate` artifact; `release_check.py ci-summary` and
  `verify-artifacts` on it; `gh release create --draft --prerelease --latest=false`.
- Test and validation results: see the
  [qualification report, section 5](./M32-windows-qualification-report.md#5-automated-gates-and-artifact-verification).
- Decisions made:
  - **Version `0.1.0-alpha.32`.** It continues the `alpha.<milestone>` series and stays
    above the M29 `alpha.29` candidate, so in-place upgrades work and downgrades stay
    refused.
  - **Draft release only.**
    - The draft carries the PR CI build and targets the PR head commit.
    - PR builds are not attested. The documented procedure therefore has the maintainer
      merge, verify the attested `main` build with `release_check.py`, replace the
      assets, retarget the tag to the merge commit and then publish.
    - It is a pre-release and is never marked latest.
  - **FFmpeg unchanged.** M30's neutral build-prefix follow-up is not applied: it would
    rebuild the M29-qualified binaries without Windows hardware to requalify them. It
    stays an accepted risk.
  - **No repository settings changed.** Private vulnerability reporting is off and is
    listed as a maintainer action. Triage labels are a checked-in file with a creation
    command; none were created.
- Known limitations:
  - The maintainer waived all clean Windows 11 checks of this build, a standard-account
    install, SmartScreen observation, Narrator/NVDA, live Xbox/PlayStation guide
    checks and the post-publication smoke test.
  - Event review in the packaged app is covered by automated browser/worker tests, not
    the packaged smoke.
  - Unsigned installer; no automatic updates; detector quality unmeasured on real games.
- Follow-up milestones affected:
  - **M39:** builds on this Windows release.
  - **M40:** gains section E.
  - **M37:** must apply the same `cookie` lock update if it branches before M32
    merges.
- Screenshots, reports, or artifacts:
  - [Release documents](../releases/0.1.0-alpha.32/README.md) and the
    [qualification report](./M32-windows-qualification-report.md).
  - The draft release has the CI release set plus `release-verification.json`.
  - No footage, models, databases, build outputs or secrets are committed.
