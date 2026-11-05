# Contracts

Versioned contracts shared by the React UI, Rust host, Python worker, project
files, profiles, events, and jobs. Licensed under Apache-2.0
([LICENSE.md](./LICENSE.md)).

- Rules for versions and breaking changes: [VERSIONING.md](./VERSIONING.md)
- History: [CHANGELOG.md](./CHANGELOG.md)
- Tool choices: [ADR-0002](../../docs/architecture/adr/0002-contract-schemas-and-generation.md)

## Layout

| Path | What | Edited by |
|---|---|---|
| `schemas/*.schema.json` | JSON Schema 2020-12 sources of truth | hand |
| `fixtures/<contract>/valid/` | Documents that must load | hand |
| `fixtures/<contract>/invalid/` | `{description, expect, path?, message_contains?, document}` cases that must fail for the stated reason | hand |
| `src/generated/types.ts` | TypeScript types | `pnpm contracts:generate` |
| `src/{versioning,semantic,validate}.ts` | TypeScript `load()` / `normalize()` | hand |
| `python/openworld_moments_contracts/generated/` | Pydantic v2 models | `pnpm contracts:generate` |
| `python/openworld_moments_contracts/schemas/` | Vendored copy of `schemas/` | `pnpm contracts:generate` |
| `python/openworld_moments_contracts/{versioning,semantic,validate}.py` | Python `load()` / `normalize()` | hand |

## Contracts later milestones must use

| Contract | Schema | TypeScript type | Python model | First used by |
|---|---|---|---|---|
| Error | `error.schema.json` | `ErrorInfo` | `generated.error_schema.ErrorInfo` | M03 |
| Job | `job.schema.json` | `Job` | `generated.job_schema.Job` | M03 |
| Job event | `job-event.schema.json` | `JobEvent` | `generated.job_event_schema.JobEvent` | M03 |
| Media asset | `media-asset.schema.json` | `MediaAsset` | `generated.media_asset_schema.MediaAsset` | M04, M05 |
| Event and evidence | `event.schema.json`, `evidence.schema.json` | `Event`, `Evidence` | `generated.event_schema.Event` | M14, M16–M19 |
| Profile | `profile.schema.json` | `Profile` | `generated.profile_schema.Profile` | M14, M15 |
| Project (EDL) | `project.schema.json` | `Project` | `generated.project_schema.Project` | M21 |
| Render preset | `render-preset.schema.json` | `RenderPreset` | `generated.render_preset_schema.RenderPreset` | M24 |
| Export manifest | `export-manifest.schema.json` | `ExportManifest` | `generated.export_manifest_schema.ExportManifest` | M24, M27 |

Shared primitives (IDs, `UtcTimestamp`, `TimelineMs`, `Rational`, `Region`,
`Confidence`, ...) live in `common.schema.json`.

## Using them

Always read documents through `load()`, which checks, in order: version →
schema → semantic rules. It throws `ContractVersionError` for version problems
and `ContractError` otherwise, each with a list of `path: message` issues.

```ts
import { load, type Event } from "@openworld-moments/contracts";
const event: Event = load("event", JSON.parse(text));
```

```python
from openworld_moments_contracts import load
from openworld_moments_contracts.generated.event_schema import Event

event = load("event", data)
assert isinstance(event, Event)
```

`normalize()` returns the canonical JSON value (sorted keys, integral floats
as integers). Both languages return the same value for the same document; the
fixture suites check this.

## Changing a contract

1. Edit the schema in `schemas/` and decide minor vs major per
   [VERSIONING.md](./VERSIONING.md).
2. Add or update fixtures, including an invalid case for any new rule.
3. If the rule cannot be expressed in JSON Schema, add it to both
   `semantic.py` and `semantic.ts`.
4. `pnpm contracts:generate`, then `pnpm check`.
5. Add a `CHANGELOG.md` entry.
