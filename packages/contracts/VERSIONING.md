# Contract versioning

## Two kinds of version

| Version | Where | Format | Meaning |
|---|---|---|---|
| `schema_version` | Inside every persisted or exchanged document (all top-level contracts except `error`) | `"MAJOR.MINOR"`, e.g. `"1.0"` | Shape of that document |
| API version | Worker URL prefix (`/v1/...`, spec §9.4), added in M03 | `v` + MAJOR | Shape of requests and responses as a whole |

All versioned contracts share one `schema_version` series. Today every
contract is written at **1.18** (`SUPPORTED_VERSION` in `versioning.py` and
`src/versioning.ts`; a test keeps them equal).

## Reading rules

A reader that supports `M.n` accepts a document at version `M.k` when `k ≤ n`.
Everything else is rejected before schema validation, with a message the UI can
show as-is:

| Document version | Result |
|---|---|
| missing or not `MAJOR.MINOR` | rejected: missing or malformed version |
| older major (e.g. `0.9`) | rejected: needs migration with the release that introduced the new format |
| same major, newer minor (e.g. `1.18` today) | rejected: written by a newer app; update |
| newer major (e.g. `2.0`) | rejected: written by a newer app; update |

Newer minors are rejected rather than half-read because top-level objects are
closed (`additionalProperties: false`): unknown fields would fail validation
anyway, and a clear "update the app" message beats a field error.

Writers always write the current `SUPPORTED_VERSION`.

## What needs which bump

**Minor bump (`1.0` → `1.1`):** backward compatible for readers of the new
version, i.e. every `1.0` document is still valid `1.1`.

- Add an optional field.
- Add an enum value or evidence kind *that old documents do not use*.
- Relax a constraint (larger `maxLength`, wider range).

**Major bump (`1.x` → `2.0`):** anything that can make an existing document
invalid or change its meaning.

- Remove or rename a field, or make an optional field required.
- Tighten a constraint or remove an enum value.
- Change units, coordinate systems, or ID formats.

**No bump:** descriptions, titles, examples, and fixture additions.

## Breaking-change process

1. Open an issue describing the change, why a minor bump cannot work, and every
   affected contract and consumer.
2. Record the decision in an ADR.
3. In one pull request: update the schemas, raise `SUPPORTED_VERSION` in both
   languages, add a migration from the previous major (worker-side, for
   persisted files and database rows), add fixtures for the old version that
   prove the migration and the rejection message, regenerate, and add a
   `CHANGELOG.md` entry under the new version.
4. Projects, profiles, and manifests on disk are migrated on open with a backup
   copy kept (spec §9.7: never mutate silently).

## Conventions every contract follows

- **IDs:** opaque `prefix_` + 26-char Crockford ULID. Prefixes: `ast` asset,
  `ses` session, `evt` event, `job` job, `prj` project, `seg` segment, `cor`
  correlation. Never parse meaning out of an ID.
- **Wall-clock time:** RFC 3339 UTC with a literal `Z` and at most millisecond
  precision (`2026-11-20T05:40:10.250Z`).
- **Timeline positions and durations:** non-negative integer milliseconds.
- **Frame rates:** exact rationals `{num, den}` (e.g. `30000/1001`), never
  floats.
- **Regions:** normalized `[x, y, width, height]`, origin top-left, width and
  height > 0, fully inside the frame.
- **Confidence and scores:** numbers in `[0, 1]`.
- **Open maps** (`attributes`, `details`) hold scalars only.
- **Observations vs suggestions:** an event's `source.kind` is `detector` or
  `user` for observations and `model` for suggestions. Model suggestions must
  cite `sampled_frames_ms` and stay suggestions until reviewed.
- **No game assets or names:** schemas and fixtures stay game-neutral (enforced
  by a test).
