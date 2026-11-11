## Milestone handoff

- Milestone: M30 — Security hardening and SBOM
- Outcome: The Windows alpha now has a reviewed threat model, closed gaps in the LAN
  upload and local API, and automated supply-chain gates. Each alpha package carries
  a verified CycloneDX SBOM, checksums, a disclosure policy and verification
  instructions.
  - **Threat model:** trust boundaries plus an abuse-case checklist in which every
    row names its control, the test or scan that proves it, and a status (resolved,
    mitigated, accepted or open).
  - **Phone gateway:**
    - per-address rate limit (120 requests/min);
    - lockout after 20 wrong-token or unknown-path requests, and a safe session end
      after 1,000;
    - a 300-attempt cap per session, which bounds the records and folders a token
      holder can create;
    - Origin checks on uploads and finish;
    - bidi-override-safe names.
  - **Worker API:** request bodies capped at 32 MiB; unbounded chunked bodies are
    refused.
  - **CI "Security scans" job:** known vulnerabilities via pip-audit, cargo-audit and
    pnpm audit; gitleaks over the full history; the license policy. CodeQL covers
    Python, TypeScript and the Actions workflows.
  - **Windows build:**
    - generates `sbom.cdx.json`, verifies it against every packaged file and the
      release checksums, and scans release, runtime and desktop binary for secrets
      and absolute paths;
    - remaps Rust build paths, redacts build notes and no longer ships FFmpeg's
      environment-dumping `config.log`;
    - attests provenance for `main` builds.
  - **Fuzz corpus:** malformed media, hostile names and resource limits. It found and
    fixed two bugs: Windows device names in export filename suggestions, and bidi
    overrides in phone upload names.
- Files and modules changed:
  - **Worker:** `gateway/app.py`, `gateway/uploads.py` (rate limits, lockout, attempt
    cap, Origin, name sanitizing); `api/app.py` (body cap); `exports/formats.py`
    (device-safe filenames).
  - **Supply-chain tooling** (`scripts/security/`): `components.py` (shipped-component
    collection), `sbom.py`, `verify_sbom.py`, `check_licenses.py`,
    `audit_dependencies.py`, `scan_artifacts.py`.
  - **Packaging** (`scripts/windows/`): `build_paths.py` (redaction); `artifacts.py`
    (SBOM, SECURITY.md, VERIFY.md; drops config.log); `freeze-worker.py` (redacted
    FFmpeg version text). Both scripts now put their own folder on `sys.path`, so
    the shared helper imports whether they run as scripts or from tests.
  - **Policy files:** `security/license-policy.json`,
    `security/vulnerability-exceptions.json` (empty),
    `security/artifact-scan-exceptions.json`, `.gitleaks.toml`.
  - **CI:** `.github/workflows/ci.yml` (Security scans job; Windows SBOM, scan,
    RUSTFLAGS and attestation steps) and `.github/workflows/codeql.yml`.
  - **Docs:** `SECURITY.md`, [security README](../security/README.md),
    [threat model](../security/threat-model.md),
    [release verification](../security/release-verification.md), the Windows
    packaging doc, the architecture index, README and ledger.
  - **Tests:** `tests/security/` (corpus generator, supply-chain and no-shell
    tests), `tests/media/test_fuzz_corpus.py`, new gateway tests, an API body-cap
    test. The existing packaging-assembly test now also checks that the release
    carries the SBOM, SECURITY.md and VERIFY.md and no `config.log`.
  - **Dependencies and config:** `cyclonedx-python-lib[json-validation]` added to the
    worker dev group; mypy now type-checks the security scripts.
- Public contracts or migrations: No contract or schema change and no migration.
  - **Gateway:** may now answer 429 `slow_down` and `too_many_attempts`, and 403
    `bad_origin`. The phone page explains each.
  - **Worker API:** may now answer 413 `request.too_large` and 411
    `request.length_required`.
  - **Release set:** gains `sbom.cdx.json`, `SECURITY.md` and `VERIFY.md` and drops
    `config.log`.
- Commands run:
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`, worker
    `mypy --platform darwin|win32|linux`, `pnpm build`.
  - `audit_dependencies.py`, `gitleaks git --config .gitleaks.toml`,
    `check_licenses.py --live`.
  - Downloaded the merged M29 candidate (CI run 42978883576, `c1a9bd7`) and extracted
    the installer with 7-Zip. On it: `scan_artifacts.py`; `sbom.py` +
    `check_licenses.py --sbom`; `verify_sbom.py` against the extracted runtime, and
    against a tampered copy (expected to fail); CycloneDX strict schema validation.
  - `cargo tree --target x86_64-pc-windows-msvc -i glib` / `-i proc-macro-error`.
- Test and validation results:
  - **Full gate** (`OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`): passes.
    - Worker: 1,177 passed, 1 skipped (the same existing environment skip as M29).
    - Contracts: 340 Python and 371 TypeScript tests.
    - Desktop: 254 tests.
    - Rust: 53 tests.
    - Lint, formatting, REUSE and contract drift are clean.
  - **Worker mypy** for darwin, win32 and linux: clean. **`pnpm build`:** passes.
  - **Dependency scans:** 0 known vulnerabilities.
    - Python runtime closure: 24 packages, pip-audit.
    - JavaScript production dependencies: 0 advisories at any severity.
    - Rust: 0 vulnerabilities; 2 warnings (`glib` unsound, `proc-macro-error`
      unmaintained), both only in the Linux GTK stack and absent from the Windows
      target.
  - **Secrets:** none. All 80 raw gitleaks hits were SHA-256 content hashes in
    `layout_key`, `cache_key`, `input_key` and M28 review `token` fields, covered by
    two narrow allowlists.
  - **Licenses:** 302 live components and 326 SBOM components pass.
  - **SBOM on the real M29 package:**
    - strict CycloneDX 1.6 valid;
    - 3 applications, 321 libraries, 2 excluded models and 1,936 files;
    - every one of the 1,935 inventoried runtime files matches by SHA-256;
    - a tampered `ffprobe.exe` and an extra DLL are both detected.
  - **Artifact scan of the real M29 package (before the M30 fixes):** 33 findings:
    - our desktop binary's cargo paths (fixed: RUSTFLAGS remap);
    - FFmpeg's configure paths in the inventory and `config.log` (fixed: redaction,
      and `config.log` dropped);
    - third-party upstream build paths and the FFmpeg binary's CI path (documented
      exceptions).
    `config.log` also carried 309 CI environment variables, with no credentials.
  - **Fuzz corpus:** 63 media cases and 16 hostile names, all handled. Two bugs found
    and fixed.
  - **Gateway:** 48 tests, including 7 new ones for lockout, guessing, flood, attempt
    cap, Origin and token replay.
- Decisions made:
  - **Spec references:** the brief's sections 15, 18, 19.3 and 22.2 don't match the
    current spec. Security is section 14, licensing and SBOM are 15.5, and governance
    is 19.4; I worked from those.
  - **"Shipped" is defined once** (`components.py`) and shared by the SBOM, verifier
    and license check: the locked runtime closure for Windows, the desktop crate's
    normal-dependency closure for `x86_64-pc-windows-msvc`, and production JavaScript.
  - **SBOM format:** CycloneDX 1.6, which models file hashes, excluded ML models and
    source distributions directly. Deterministic serial (UUIDv5 of commit and
    version) and the commit timestamp.
  - **Vulnerability policy:** any Python or Rust vulnerability fails; JavaScript fails
    on high or critical. Exceptions need a reason and a review date.
  - **FFmpeg binary path:** not rebuilt in M30, since the binaries were qualified on
    Windows 11 in M29. The public CI path in them is a documented exception, with a
    neutral prefix deferred to M32.
  - **`config.log` dropped:** autoconf dumps the environment into it; it isn't needed
    for corresponding source.
  - **Phone lockout returns the same 404 as a wrong token,** so it reveals nothing.
    Mass guessing ends the session, a safe failure the user recovers from by
    reopening the screen.
- Known limitations:
  - **Accepted risks:**
    - third-party binaries keep their upstream build paths;
    - the FFmpeg binaries keep the public CI path until M32;
    - no TLS on the LAN gateway;
    - no per-process memory limit for tools;
    - no automatic update;
    - an unsigned installer (signing not procured).
  - **FFmpeg CVE tracking is manual:** FFmpeg isn't in the PyPI, RustSec or npm
    feeds.
  - **Private vulnerability reporting isn't enabled yet.** The repository owner
    (`@heetdalsania`) must turn it on (Settings → Code security). `SECURITY.md`
    documents an interim route meanwhile.
  - **Open, deferred to M40 (non-blocking):** the Windows firewall prompt for a
    standard user, and a Windows retest of the #38 multi-upload fix.
  - **Not exercised here:** the SBOM generation, scan, attestation and Security scans
    steps were validated locally against the real M29 package. Their first runs in CI
    happen on this PR, and attestation only on pushes to `main`.
- Follow-up milestones affected:
  - **M32:** neutral FFmpeg build prefix and requalification; publish the SBOM and
    attestation with the release; enable private vulnerability reporting.
  - **M37 (macOS signing):** reuse the SBOM, verification and scan tooling.
  - **M40:** standard-user firewall and #38 retest.
- Pull request: [#39](https://github.com/heetdalsania/openworld-moments/pull/39)
- Screenshots, reports, or artifacts:
  - [Threat model](../security/threat-model.md),
    [security engineering](../security/README.md) and
    [release verification](../security/release-verification.md).
  - No secrets, user libraries, private paths, footage, generated media, models,
    databases or build outputs are included.
