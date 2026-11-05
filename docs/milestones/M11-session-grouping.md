# M11 — Session grouping

## Objective

Group imported assets into explainable candidate play sessions using metadata and provenance, with durable user corrections.

## Dependencies

M06 merged.

## Required context

Read specification sections 8.2.1, 8.2.2, 8.2.4, and database session tables.

## In scope

- Capture-time estimation and basis/confidence.
- Metadata grouping by source, time gap, format compatibility, and import order.
- Session creation/update job.
- Grouping reasons and confidence.
- Manual merge, split, reorder, and “never regroup” corrections through API.
- Synthetic session fixture generator.

## Out of scope

- Visual/audio overlap, session player, and game detection.

## Implementation steps

1. Implement capture-time extractors for filesystem and filename patterns.
2. Define deterministic grouping rules and threshold settings.
3. Persist grouping decision evidence.
4. Add manual correction records that override future automatic runs.
5. Implement recompute command for unreviewed groups only.
6. Add boundary and ambiguity fixtures.
7. Document confidence semantics.

## Acceptance criteria

- Same-source adjacent fixtures group deterministically.
- Large gaps and incompatible sources split.
- Ambiguous time metadata lowers confidence rather than fabricating precision.
- Manual split/merge survives recomputation.
- Asset order is stable and user-correctable.
- No grouping action modifies media.

## Required validation

- Fixture matrix for gaps, missing timestamps, filenames, mixed folders, and time zones.
- Idempotent recomputation test.
- Manual override persistence test.

## Handoff

Document rules, default gap, confidence calculation, timestamp parsers, and manual-override model. Update M11.

