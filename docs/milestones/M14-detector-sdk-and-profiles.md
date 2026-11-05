# M14 — Detector SDK and profile schema

## Objective

Create the versioned, testable runtime through which game profiles and detectors consume derived media and emit evidence-backed events.

## Dependencies

M01, M03, and M08 merged.

## Required context

Read specification sections 8.4, 18, 19.2, and the safety boundaries.

## In scope

- Detector interface and lifecycle.
- Profile manifest/schema, normalized regions, locale packs, capabilities, and license metadata.
- Read-only analysis context.
- Event/evidence validation.
- Per-detector failure isolation, progress, cancellation, and versioned cache.
- Generic synthetic example profile and detector.
- Profile validation CLI.

## Out of scope

- Third-party arbitrary-code plugins, downloader, actual GTA detectors, and calibration UI.

## Implementation steps

1. Define detector protocol and immutable analysis inputs.
2. Define manifest/profile loading and inheritance rules.
3. Validate compatibility against resolution/aspect/locale.
4. Implement detector job orchestration and failure isolation.
5. Persist detector/profile/tool versions with every event.
6. Add synthetic detector demonstrating temporal evidence.
7. Document authoring and test requirements.

## Acceptance criteria

- Invalid profiles fail before analysis with exact schema paths.
- One failed detector does not discard events from successful detectors.
- Events without valid evidence/version data are rejected.
- Cache invalidates when detector, profile, or relevant derived input changes.
- Detector context cannot write source media.
- Contributor can run the synthetic example from CLI.

## Required validation

- Profile schema fixtures.
- Compatibility, cancellation, isolation, and cache tests.
- End-to-end synthetic detector run.

## Handoff

Document SDK API, context paths, manifest fields, cache key, failure model, and extension boundary. Update M14.

