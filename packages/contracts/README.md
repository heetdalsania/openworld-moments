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
| `src/generated/validators.{js,d.ts}` | Static Ajv validators for CSP-restricted runtimes | `pnpm contracts:generate` |
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
| Fingerprints | `fingerprint.schema.json` | `AssetFingerprints` (+ `DuplicateCandidate`, `FingerprintRequest`, `FingerprintResult`) | `generated.fingerprint_schema.AssetFingerprints` | M06, M12 |
| Derived media | `derived-media.schema.json` | `AssetDerivedMedia` (+ `DerivedArtifact`, `ProxyDecision`, `ToneMap`, `Recipe`, `DerivedMediaRequest`, `DerivedMediaResult`, `DerivedCleanupResult`) | `generated.derived_media_schema.AssetDerivedMedia` | M08 |
| Overlap | `overlap.schema.json` | `AssetOverlap` (+ `AlignRequest`, `AlignResult`, `OverlapOverride`) | `generated.overlap_schema.AssetOverlap` | M12 |
| Session | `session.schema.json` | `Session` (+ `SessionMember`, `SessionGrouping`, `GroupingLink`, `GroupRequest`, `GroupResult`, `MergeRequest`, `SplitRequest`, `ReorderRequest`, `RemoveRequest`, `SessionCorrection`) | `generated.session_schema.Session` | M11 |
| Watched folder | `watched-folder.schema.json` | `WatchedFolder` (+ `WatchedFolderRequest`, `WatchedFileReport`, `WatchedFileDecision`, `WatchedFile`, `ScanReport`) | `generated.watched_folder_schema.WatchedFolder` | M07 |
| Import | `import.schema.json` | `ImportResult` (+ `ImportRequest`, `RelinkRequest`, `RelinkResult`, `SourceCheckResult`) | `generated.import_schema.ImportResult` | M05 |
| Event and evidence | `event.schema.json`, `evidence.schema.json` | `Event`, `Evidence` | `generated.event_schema.Event` | M14, M16–M19 |
| Analysis result | `analysis.schema.json` | `AnalysisResult` | `generated.analysis_schema.AnalysisResult` | M14 |
| Profile patch | `profile-patch.schema.json` | `ProfilePatch` | `generated.profile_patch_schema.ProfilePatch` | M15 |
| Profile | `profile.schema.json` | `Profile` (including optional `WantedSettings`/`OcrSettings`) | `generated.profile_schema.Profile` | M14–M16 |
| Editor project | `editor-project.schema.json` | `EditorProject` | `generated.editor_project_schema.EditorProject` | M21, M22, M24 |
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

M19 adds review and evaluation contracts at schema version 1.14; see [event review](../../docs/architecture/event-review.md) and [local evaluation](../../docs/evaluation/README.md).

M20 adds `story-candidate` and `story-candidates`; see [story engine](../../docs/architecture/stories.md). The `story` job kind generates candidates without editing source media.

M21 adds `editor-project`, text overlays and optional gain ranges at 1.16; see [editor model](../../docs/architecture/editor-projects.md) for strict editor invariants and explicit legacy migration.

M23 adds optional caption placement/style/output intent at **1.17**; existing timed captions and audio ranges retain their units. See [captions and audio](../../docs/architecture/captions-and-audio.md).

TypeScript `load()` uses generated standalone validators. Ajv compilation happens
only during generation; browser validation needs no `unsafe-eval`. The generator
normalizes the two module systems used by Ajv runtime helpers through static
imports, and `pnpm contracts:check` covers validator drift. The CSP regression
executes fixtures with Node string code generation disabled.
