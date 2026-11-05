# M01 — Contracts and versioning

## Objective

Define canonical versioned contracts shared by the React UI, Rust host, Python worker, project files, profiles, events, and jobs.

## Dependencies

M00 merged.

## Required context

Read specification sections 8.4.1, 8.4.5, 8.9.3, 9.4, 9.5, 11.1, and 18.

## In scope

- JSON Schema source files for identifiers, errors, jobs, media metadata, events, detector evidence, profiles, projects, render presets, and export manifests.
- Schema-version and API-version policy.
- Generated TypeScript and Pydantic types.
- Contract fixtures and compatibility tests.
- Stable ID format and timestamp/timebase conventions.

## Out of scope

- Database tables, API endpoints, detector behavior, and rendering.

## Implementation steps

1. Choose JSON Schema draft and generation tools; record the decision in an ADR.
2. Define UTC timestamps, millisecond timeline coordinates, rational frame rates, normalized regions, and opaque IDs.
3. Create schemas with `additionalProperties` rules chosen deliberately.
4. Generate TypeScript and Python types through reproducible root commands.
5. Add valid and invalid fixtures for every top-level contract.
6. Add backward-compatibility tests and a documented breaking-change process.
7. Add a contract changelog.

## Acceptance criteria

- Both language runtimes parse the same fixtures to equivalent normalized values.
- Invalid evidence regions, negative durations, unknown required versions, and malformed IDs are rejected.
- Generated files are deterministic and CI detects drift.
- Contracts distinguish observed events from model suggestions.
- No schema contains a game-specific copyrighted value or asset.

## Required validation

- Generate contracts twice and confirm no diff.
- Run schema fixture tests in TypeScript and Python.
- Run an intentional old-version fixture and verify a useful compatibility error.

## Handoff

Document the schema entry points, generation command, versioning rules, and the exact contracts later milestones must use. Update the M01 ledger entry.

