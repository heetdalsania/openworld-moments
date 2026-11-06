# M32 — Windows public alpha qualification

## Objective

Qualify and publish the first honest, reproducible Windows public alpha after all required workflows pass on clean Windows systems. This remains a valid early release gate; M39 later qualifies the combined Windows and macOS release.

## Dependencies

M20, M23, and M25 through M31 merged.

## Required context

Read the complete specification, MILESTONES.md, SECURITY.md, CONTRIBUTING.md, and every merged milestone handoff.

## In scope

- Release-candidate freeze and traceable qualification checklist.
- Clean-machine end-to-end workflow tests using legally shareable fixtures.
- Public compatibility matrix, detector metrics, known limitations, and privacy statement.
- Versioned release notes, migration notes, artifacts, checksums, SBOM, and notices.
- Tagged source release and GitHub release draft/publication.
- Post-release issue triage labels and rollback instructions.

## Out of scope

- macOS qualification, declaring v1.0, promising complete GTA VI compatibility, app-store distribution, and direct social publishing.

## Implementation steps

1. Freeze release scope, versions, dependency locks, schemas, models, and profiles.
2. Run automated quality gates and archive machine-readable results.
3. Execute import-to-render journeys on clean supported Windows configurations.
4. Validate console-transfer documentation using current PlayStation and Xbox workflows.
5. Publish measured detector compatibility only for legally obtained, consented fixtures.
6. Assemble and independently verify artifacts, checksums, SBOM, licenses, and manifests.
7. Draft the release, conduct final security/privacy review, tag, publish, and smoke-test downloads.

## Acceptance criteria

- Every required milestone is merged with its handoff evidence and no release-blocking issue remains open.
- A clean-machine user completes import, session reconstruction, event review, edit, and both aspect-ratio renders.
- Release notes distinguish tested facts, experimental features, and unsupported claims.
- No GTA VI compatibility claim appears without published profile version, fixture description, and metrics.
- Downloaded artifacts match published checksums and produce the documented version report.
- Rollback and known data-migration constraints are documented before publication.

## Required validation

- Full CI, clean-machine matrix, release artifact verification, accessibility smoke test, and security checklist.
- Fixture licenses/consent audit and trademark wording review.
- Post-publication install and end-to-end smoke test from the GitHub release artifact.

## Handoff

Publish the Windows qualification report, compatibility matrix, metrics, known limitations, release notes, artifact hashes, SBOM, signed/tagged commit details, and follow-up issue list. Mark M32 complete only after the published Windows artifact passes the smoke test.
