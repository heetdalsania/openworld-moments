# Security Policy

## Supported versions

OpenWorld Moments is pre-release. Security fixes go to the `main` branch and the
newest Windows alpha candidate built from it (currently `0.1.0-alpha.29`). There are
no long-term supported releases yet; older candidates are not patched.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability in media parsing, FFmpeg
invocation, path traversal, local API authentication, LAN uploads, model downloads,
update or artifact integrity, credential storage or arbitrary code execution.

Report it privately:

1. **Preferred:** open a private advisory with **Security → Report a vulnerability**
   on the [repository](https://github.com/heetdalsania/openworld-moments/security/advisories/new).
   *(Interim: until GitHub private vulnerability reporting is enabled on this
   repository, that button may not appear.)*
2. **Interim method:** contact a maintainer privately through their GitHub profile
   (repository owner `@heetdalsania`, maintainer `@Arun-Velkumar19`) and ask for a
   private channel. Do not put details in public issues, discussions or pull
   requests.

Include:

- A concise description and the potential impact.
- The affected version (or commit) and component.
- Reproduction steps, expected and actual behavior.
- Any suggested mitigation.

Do not include private gameplay footage, credentials, tokens or personal data
unless a maintainer asks for them through a private channel. Synthetic files that
reproduce the problem are best.

## What to expect

- Acknowledgement within 7 days.
- An initial assessment and planned fix or mitigation within 30 days, sooner for
  actively exploited issues.
- Credit in the advisory and release notes if you want it.

This is a volunteer project. There is no bug bounty, and we ask for coordinated
disclosure until a fix is available.

## Verifying releases

Each release includes `checksums.txt`, a CycloneDX SBOM (`sbom.cdx.json`) and
`VERIFY.md`. Builds from `main` also carry a GitHub build-provenance attestation.
See [docs/security/release-verification.md](./docs/security/release-verification.md).

## Security boundaries

The [threat model](./docs/security/threat-model.md) has the full list. In short:

- Source footage is untrusted input and is never modified.
- The desktop API binds only to loopback and requires a per-launch token.
- Phone upload is off by default, temporary, tokenized, rate-limited and isolated
  from the desktop API and the library.
- FFmpeg and other tools run with argument arrays, never shell strings.
- Models and binaries have verified checksums and documented licenses.
- There is no telemetry or automatic crash upload.
- Plugins are deferred until a permissions and isolation model exists.
