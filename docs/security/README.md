# Security engineering (M30)

- [Threat model and abuse-case checklist](./threat-model.md): trust boundaries,
  every abuse case with its control, evidence and status, and accepted risks.
- [Verifying a release](./release-verification.md): checksums, provenance, SBOM
  (shipped in every release as `VERIFY.md`).
- [Security policy and reporting](../../SECURITY.md).

## Automated gates

| Gate | Where | Tool and configuration | Fails on |
|---|---|---|---|
| Known vulnerabilities | CI "Security scans" (Linux) | `scripts/security/audit_dependencies.py`: pip-audit 2.10.1 on the worker's runtime closure from `uv.lock`; cargo-audit 0.22.2 on `Cargo.lock`; `pnpm audit --prod` | any Python or Rust vulnerability; high/critical JavaScript; any expired exception in `security/vulnerability-exceptions.json` |
| Secrets in history | CI "Security scans" | gitleaks 8.30.1 (downloaded, checksum-verified), `.gitleaks.toml` (default rules + two narrow allowlists for SHA-256 content hashes) | any finding |
| Licenses | CI "Security scans" and Windows build | `scripts/security/check_licenses.py` with `security/license-policy.json` | denied, unknown or unapproved licenses |
| Static analysis | CI (all jobs) and `codeql.yml` | Ruff `S` rules (Bandit), Clippy `-D warnings`, ESLint; CodeQL security-extended for Python, TypeScript and Actions | lint errors; CodeQL alerts appear in code scanning |
| No shell strings | Python tests | AST guard over the worker, contracts and `scripts/`; Rust and desktop checks | any `shell=True`, `os.system`, shell plugin or shell spawn |
| SBOM matches the package | Windows build | `scripts/security/verify_sbom.py` | schema errors, drift from inputs, unlisted, missing or changed packaged files, checksum mismatch |
| Secrets and paths in artifacts | Windows build | `scripts/security/scan_artifacts.py` with `security/artifact-scan-exceptions.json` | unexplained findings or stale exceptions |
| Provenance | Windows build on `main` | `actions/attest-build-provenance` for every release file | — |

Exceptions are reviewed files in `security/`. Each needs a reason, and
vulnerability exceptions need a review date. An expired or stale exception fails
its gate.

### Results at M30

- **Vulnerabilities:** none known.
  - Python runtime closure: 24 packages.
  - JavaScript production dependencies: 0 advisories at any severity.
  - Rust: 0 vulnerabilities, plus two Linux-only warnings (`glib` unsound,
    `proc-macro-error` unmaintained). Both come from Tauri's GTK stack and are absent
    from the Windows package.
- **Secrets:** none. The 80 raw gitleaks hits were all SHA-256 content hashes in
  `layout_key`, `cache_key`, `input_key` and privacy-review `token` fields.
- **Licenses:** all 326 SBOM components pass (302 in the live check). Copyleft is
  limited to:
  - the project's own AGPL;
  - FFmpeg and x264, GPL-2.0-or-later (ADR-0007);
  - the PyInstaller bootloader, GPL with its distribution exception.

  The rest is MIT, Apache-2.0, BSD, ISC, Zlib, Unicode-3.0, MPL-2.0, PSF-2.0 and
  similar.

## SBOM

- **Format:** CycloneDX 1.6 JSON, `sbom.cdx.json` in each Windows release. It is
  validated with the strict CycloneDX schema validator.
- **Generator:** `scripts/security/sbom.py`, which is deterministic for the same
  inputs: the runtime inventory, `uv.lock`, `Cargo.lock` and the model catalog.
- **Shipped libraries:**
  - Python: the worker's locked runtime closure, evaluated for 64-bit CPython on
    Windows, plus the two workspace packages.
  - Rust: the desktop executable's normal-dependency closure for
    `x86_64-pc-windows-msvc`. Build and dev dependencies are excluded.
  - JavaScript: production packages recorded at freeze time.
- **Native components:**
  - CPython 3.12.14 and the libraries it bundles (OpenSSL, SQLite, libffi, bzip2,
    liblzma, expat, mpdecimal, zlib), each listed only if its file ships;
  - the PyInstaller bootloader;
  - FFmpeg 9.0.2 and x264, with source URLs, source hashes and binary hashes.
- **Models:** the signed catalog's whisper.cpp models as
  `machine-learning-model` components with `scope: excluded` (download-only, never
  shipped), with license, revision, size and SHA-256.
- **Files:** every packaged runtime file with its SHA-256 (1,936 in
  0.1.0-alpha.29).
- **Not included:** WebView2, a Microsoft-managed Windows component (recorded on the
  root component).

The verifier regenerates the SBOM, re-hashes every packaged file on disk and checks
the release checksums. The M29 candidate (`c1a9bd7`) verified with all 1,935
inventoried files matching; the inventory itself is covered by `checksums.txt`.

## Fuzz and resource-limit corpus

`services/media-worker/tests/security/corpus.py` generates the corpus at test time,
seeded, so no media is committed:

- **13 structural cases:**
  - empty and one-byte files;
  - 64 KiB of random bytes;
  - text, PNG and ZIP disguised as video;
  - an EBML header followed by garbage;
  - an `ftyp` box alone, or declaring 4 GiB;
  - a `moov` box declaring 2 GiB;
  - zero-size box loops;
  - a 64-bit size overflow;
  - deeply nested boxes.
- **10 truncations** of a real MP4.
- **40 seeded mutants** (bit flips, zeroed blocks, duplicated chunks, header damage).
- **16 hostile file names:** traversal, Windows device names, a bidi override,
  NULs, newlines, URL-encoding, empty and 400-character names.

`tests/media/test_fuzz_corpus.py` sends every case through FFprobe, a managed
import and the phone gateway, and checks:

- every result is contract-valid or carries a stable error code;
- each probe finishes within 20 s;
- no path leaks into errors;
- source files are unchanged;
- nothing is written outside the library or the staging folder;
- every hostile name becomes one safe component.

The corpus found and fixed two issues: Windows device names in export filename
suggestions, and bidi overrides in phone upload names.

Related existing tests:

- cancellation of FFprobe, imports, renders and transcription;
- timeouts and output caps (`test_process.py`);
- oversized, interrupted and concurrent uploads (`tests/gateway`).

## Commands

```bash
uv run --directory services/media-worker python ../../scripts/security/audit_dependencies.py
gitleaks git --config .gitleaks.toml --redact .
uv run --directory services/media-worker python ../../scripts/security/check_licenses.py --live
# After a Windows build (paths as in CI):
uv run --directory services/media-worker python ../../scripts/security/sbom.py \
  --inventory <runtime>/inventory.json --installer <setup.exe> --output sbom.cdx.json
uv run --directory services/media-worker python ../../scripts/security/verify_sbom.py \
  --sbom sbom.cdx.json --inventory <runtime>/inventory.json --runtime-dir <runtime> --release-dir <release>
python3 scripts/security/scan_artifacts.py <release> <runtime> <desktop.exe>
```
