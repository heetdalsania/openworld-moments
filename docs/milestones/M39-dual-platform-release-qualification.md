# M39 — Dual-platform release qualification

## Objective

Qualify and publish a single release whose supported downloads provide the complete OpenWorld Moments workflow on Windows x64, macOS Apple Silicon, and macOS Intel.

## Dependencies

M32 and M37–M38 merged.

## Required context

Read the complete specification, macOS delivery plan, MILESTONES.md, SECURITY.md, CONTRIBUTING.md, and all platform milestone handoffs.

## In scope

- Cross-platform release-candidate freeze and version identity.
- Windows x64, macOS `arm64`, and macOS `x86_64` clean-machine qualification.
- Platform/architecture compatibility and performance matrix.
- Signed/notarized DMGs, Windows installer, checksums, per-platform SBOMs, notices, and manifests.
- Architecture-labelled GitHub Release assets and download guidance.
- Cross-platform project/database portability and upgrade checks.
- Published qualification report, known limitations, rollback instructions, and post-release smoke tests.

## Out of scope

- Linux, Mac App Store/Microsoft Store, automatic updating, mobile native apps, and declaring perfect detector coverage.

## Implementation steps

1. Freeze shared versions, schemas, database migrations, profiles, models, and platform dependencies.
2. Build all three artifacts from the tagged source using the approved release workflows.
3. Run the full import-to-render matrix on clean physical systems.
4. Move the same portable project/library fixture between Windows and macOS and validate compatibility.
5. Independently verify signatures, notarization, checksums, SBOMs, licenses, and architecture labels.
6. Publish platform-specific limitations, metrics, download selection, release notes, and rollback instructions.
7. Publish the release and repeat installation/import/render smoke tests from downloaded artifacts.

## Acceptance criteria

- A nontechnical user completes the primary workflow on every supported platform/architecture without developer tools.
- The same project contract and database version behave consistently across Windows and macOS.
- macOS downloads pass Gatekeeper without bypass instructions and run natively on their labelled architecture.
- Release assets cannot be confused by filename, UI copy, or download documentation.
- All artifacts match published checksums/SBOMs and report the same product/schema versions.
- No cross-platform support claim exceeds the published clean-machine evidence and detector metrics.

## Required validation

- Full CI and clean-machine qualification matrix from the macOS delivery plan.
- Cross-platform project/database portability, upgrade, accessibility, security, and artifact-verification tests.
- Post-publication download, install, import, CPU render, hardware probe/fallback, and uninstall smoke tests.

## Handoff

Publish the cross-platform qualification report, machine/OS matrix, portability results, compatibility metrics, known limitations, release notes, checksums, SBOMs, signing/notarization evidence, tag/commit details, and follow-up issue list. M39 is complete only after all downloaded release artifacts pass their post-publication smoke tests.
