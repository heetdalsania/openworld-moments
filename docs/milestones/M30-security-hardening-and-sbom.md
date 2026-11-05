# M30 — Security hardening and SBOM

## Objective

Close high-priority threats, inventory shipped components, and make alpha artifacts independently auditable.

## Dependencies

M10 and M29 merged.

## Required context

Read specification sections 15, 18, 19.3, and 22.2.

## In scope

- Updated threat model for desktop, worker, LAN upload, media parsing, and update/model flows.
- Dependency, model, codec, and license inventory.
- CycloneDX or SPDX software bill of materials.
- Secret, dependency, and static-analysis CI checks.
- Media/path fuzz cases and resource-limit enforcement.
- Release checksums and security reporting workflow.

## Out of scope

- Formal penetration-test certification, bug-bounty funding, and automatic self-update.

## Implementation steps

1. Convert architectural trust boundaries into an abuse-case checklist.
2. Audit loopback/LAN binding, authentication, token expiry, origins, and upload limits.
3. Audit FFmpeg invocation, path handling, temporary files, archives, and derived media.
4. Generate machine-readable SBOMs and human-readable license/model notices.
5. Add CI gates for known vulnerabilities, secrets, and prohibited licenses.
6. Add malformed media, oversized input, traversal, and cancellation test corpora.
7. Publish the supported disclosure path and release verification instructions.

## Acceptance criteria

- No known critical vulnerability remains in a shipped dependency without a documented exception.
- LAN upload is off by default and cannot bypass pairing, expiry, origin, size, or rate controls.
- User-controlled values never become shell command strings.
- SBOM contents match packaged artifacts and include transitive dependencies.
- Secrets and private absolute paths are absent from release artifacts and manifests.
- Security policy provides a private reporting route or a clearly documented interim method.

## Required validation

- Automated scans plus manual threat-model review.
- Path traversal, token replay, oversized upload, malformed media, and resource exhaustion tests.
- Fresh-package SBOM and checksum verification.

## Handoff

Document resolved/open threats, accepted risks, scan configurations, SBOM format, license findings, fuzz corpus, disclosure process, and artifact verification commands. Update M30.
