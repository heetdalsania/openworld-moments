# Verifying an OpenWorld Moments release

Every Windows alpha package ships with files that let you check it independently
before installing. This file is included in each release as `VERIFY.md`.

| File | What it is |
|---|---|
| `OpenWorld-Moments_<version>_Windows_x64-setup.exe` | The installer (unsigned alpha) |
| `checksums.txt` | SHA-256 of every other file in the release |
| `sbom.cdx.json` | CycloneDX 1.6 software bill of materials: every shipped library, native component and packaged file with its hash; optional models listed as not bundled |
| `runtime-inventory.json` | Packaged runtime files and hashes, pinned sources, tool versions |
| `THIRD_PARTY_NOTICES.txt`, `runtime-notices.zip` | License notices |
| `ffmpeg-<version>.tar.xz`, `x264-<commit>.tar.gz`, `build-media.sh`, `sources.json`, `compiler.txt`, `build-packages.txt` | Corresponding source and build instructions for the GPL FFmpeg/x264 binaries |
| `SECURITY.md` | How to report a vulnerability |

## 1. Check the checksums

Windows PowerShell, in the folder with the downloaded files:

```powershell
Get-Content checksums.txt | ForEach-Object {
  $hash, $name = $_ -split '  ', 2
  $actual = (Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $hash) { "MISMATCH $name" } else { "ok       $name" }
}
```

macOS or Linux:

```bash
sha256sum -c checksums.txt
```

Every line must be `ok`. A mismatch means the file is not the one that was built:
do not install it.

## 2. Check where it was built (provenance)

Packages built from the `main` branch carry a signed GitHub build-provenance
attestation, which proves the file came from this repository's CI workflow at a
specific commit. With the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify OpenWorld-Moments_0.1.0-alpha.29_Windows_x64-setup.exe \
  --repo heetdalsania/openworld-moments
```

Pull-request builds are not attested; only use packages from `main`, and later
from published releases.

## 3. Read the SBOM

`sbom.cdx.json` is standard CycloneDX JSON. Any CycloneDX tool can read it, for
example [OWASP Dependency-Track](https://dependencytrack.org/) or:

```bash
# Libraries and their licenses
jq -r '.components[] | select(.type=="library") | "\(.name) \(.version // "") \(.licenses[0].expression // "")"' sbom.cdx.json
# The hash recorded for a packaged file
jq -r '.components[] | select(.name=="runtime/tools/ffmpeg.exe") | .hashes[0].content' sbom.cdx.json
```

To check the SBOM against an installed copy, compare the SHA-256 of files under the
install folder's `runtime\` with the `file` components (`runtime/<path>`). The
project's CI runs the full check (`scripts/security/verify_sbom.py`) on every build.

## 4. What the alpha does not give you yet

- The installer is not Authenticode-signed, so Windows SmartScreen may warn about
  an unknown publisher. Verify the checksum and provenance instead of disabling
  security software.
- There is no automatic update. Install new versions by hand after verifying them.
