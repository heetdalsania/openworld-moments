# M29 — Windows packaging and model manager

## Objective

Deliver a clean-machine Windows alpha package with predictable runtime dependencies and an auditable optional-model installation flow.

## Dependencies

M03, M08, M18, and M24 merged. M18 owns the speech-model registry and optional
whisper.cpp adapter extended by this milestone.

The GPL packaging exception in [ADR-0007](../architecture/adr/0007-windows-ffmpeg-packaging.md) was accepted through PR #35. Implementation may proceed; M29 completion still requires every acceptance criterion and validation below.

## Required context

Read specification sections 8.3, 10.7, 11.3, 14, 15.5, and 28; the M03, M08,
M18 and M24 merged handoffs; and ADR-0007. The former references to 6.5, 15.3,
19.1 and 19.2 describe search, game interaction and contribution rules rather
than runtime packaging and model management.

## In scope

- Reproducible Windows x64 application packaging.
- Bundled or explicitly installed worker and FFmpeg dependencies.
- First-run system doctor and actionable capability report.
- Optional model catalog with size, source, license, checksum, and disk estimate.
- Resumable model download, verification, removal, and version pinning.
- Upgrade/uninstall behavior that preserves user libraries unless requested.

## Out of scope

- Microsoft Store publication, macOS/Linux installers, and paid code-signing procurement.

## Implementation steps

1. Choose and document the Windows installer and application packaging format.
2. Produce deterministic build scripts and artifact metadata in CI.
3. Bundle or resolve FFmpeg and worker runtimes with license notices.
4. Build first-run checks for storage, codecs, acceleration, permissions, and ports.
5. Implement a signed-manifest model catalog with checksum verification.
6. Exercise install, upgrade, repair, uninstall, and data-retention paths.
7. Document unsigned-alpha/SmartScreen expectations until signing is available.

## Acceptance criteria

- A nontechnical tester can install and launch on a clean supported Windows machine without a terminal.
- Required executables are version-pinned and reported by the system doctor.
- A corrupt or mismatched model is never marked installed.
- Uninstall clearly distinguishes application files from user libraries and media.
- Upgrade preserves supported database and project versions.
- Artifact checksums and third-party notices accompany every package.

## Required validation

- Clean Windows VM install, first launch, import, render, upgrade, and uninstall run.
- Interrupted model download, low disk, offline, corrupt manifest, and path-with-Unicode tests.
- Artifact reproducibility comparison where toolchains permit it.

## Handoff

Document supported Windows versions, build commands, installer identity, runtime/model inventory, VM evidence, unsigned warnings, upgrade matrix, and artifact hashes. Update M29.
