# Detector runtime and local profiles (M14)

M14 supplies the runtime through which **trusted, shipped built-in detectors**
read derived media and emit validated observations. The only shipped detector is
`synthetic-bright-region`, an example for generated fixtures. It does not detect
gameplay. The GTA profile directories remain unvalidated placeholders.

## Entry points

- `services/media-worker/openworld_moments/detectors/sdk.py`: Apache-2.0 protocol
  and immutable input/output types; the execution engine remains AGPL.
- `profiles.py`: bounded JSON loading, local inheritance, compatibility and digest.
- `inputs.py`: bounded, cancellable sampling of a checked M08 proxy.
- `service.py`: registry, validation, independent transactions and cache.
- `example.py`: synthetic temporal detector.
- `__main__.py`: the `owm` CLI, also runnable with
  `python -m openworld_moments.detectors`.

No downloader, arbitrary-code plugin loader, cloud inference, model, OCR engine,
game-specific detector, calibration UI or event-review UI is introduced.

## Profile manifest

The canonical profile contract remains `packages/contracts/schemas/profile.schema.json`
(contracts 1.9). Older 1.x manifests remain contract-readable. To **run analysis**,
the resolved profile must also declare its license and capabilities.

| Field | Meaning |
|---|---|
| `id`, `profile_version`, `display_name`, `game_family` | Identity and semantic version |
| `license` | Recorded license identifier/expression; not a legal clearance check |
| `frame` | Minimum upright source dimensions and permitted aspect ratios (1% tolerance) |
| `regions` | Named normalized `[x,y,w,h]` regions, checked fully inside the frame |
| `capabilities` | Allowed input capabilities; currently only `frames.gray` |
| `detectors` | Built-in IDs, enable flags, confidence threshold, confirmation frames, optional locale |
| `locales` | Language tags → `{version, license, vocabulary}`; vocabulary maps named categories to strings |
| `safe_zones` | Named regions for downstream layout use |
| `extends` | An optional local catalog profile ID; never a URL, path or code entry point |

Profiles are JSON only in this implementation. Each catalog entry is
`<catalog>/<id>/profile.json`; catalog IDs use lowercase, hyphen-separated slugs.
The development default is the repository's `profiles/` directory. An installed
worker can use `--profiles <catalog>` on the CLI; bundling and production catalog
discovery are M29's responsibility.

The loader reads at most 256 KiB, rejects duplicate JSON keys, non-finite numbers,
non-object roots and non-files, and never fetches references from the network.
Catalog paths that resolve outside the configured catalog are refused.

### Inheritance

- Parents resolve recursively inside the same catalog, with a depth limit of eight. Cycles and missing parents fail.
- A child declares its own `id`, `profile_version` and `display_name`.
- `regions` and `locales` merge by name; a child replaces a named entry in full.
- Other fields, including the detector array, replace the parent's value in full.
- The fully resolved document passes the shared schema and semantic validator.
  Errors retain paths such as `regions.signal` and `locales.en.version`.
- Duplicate detector IDs, an unknown enabled built-in ID, a missing analysis
  license/capability declaration, and a detector locale without a pack fail before
  any media preparation. Missing required ROIs/capabilities and incompatible
  resolution/aspect/locale produce explicit per-detector `skipped` outcomes.

The digest includes the complete resolved content and parent digests, not just a
version string. A parent or locale change invalidates descendants even if someone
forgot to bump the version. Contributors should still bump versions deliberately.

## Read-only analysis context and lifecycle

A built-in implements `id`, semantic `version`, `capabilities`,
`required_regions`, `setup(context)`, `detect(context)` and `close()`.
The registry is fixed in source. A profile cannot import Python, execute a command,
choose an input file, obtain a database connection or specify a writable path.

Each unit receives a frozen `AnalysisContext` containing:

- asset ID and duration;
- immutable frames (`Frame.source_ms`, width, height, packed grayscale `bytes`);
- read-only region/settings/vocabulary maps (regions and vocabulary use tuples);
- cancellation and progress callbacks.

The context exposes **no source path, file handle, filesystem writer or database**.
This is a capability boundary for cooperating built-ins, not an OS sandbox for
hostile Python code. Third-party executable plugins remain out of scope.

The orchestrator obtains an M08 proxy with `proxy_policy: always`, preserving the
original. It checks the derived path, verifies the proxy's SHA-256 against its row,
and decodes only that proxy. Detectors never open the original. Sampling v1 is
64×36 grayscale at 2 fps; timestamps are source milliseconds at 500 ms intervals.
The sampling granularity is not a claim of source-frame-accurate detection.

FFmpeg uses argument arrays, file-only input protocols, a 600-second timeout and
a 64 MiB raw-output cap per asset. Samples are retained for one asset at a time,
reused across its detectors, and released before the next asset. Peak memory also
includes the raw output and Python object overhead. The current SDK supports
frames only; audio/transcription capabilities arrive in M18.

`close()` runs even if setup/detection fails. Built-ins check cancellation between
samples, and the orchestrator also checks between outputs/units and before commit.
FFmpeg cancellation kills and reaps the subprocess through the existing runner.
A hung arbitrary Python implementation is not forcibly preempted: built-ins must
honor the cooperative contract and have bounded work.

## Event validation and time

Detectors yield source-coordinate `Detection` values. Every output must have:

- a valid namespaced type, non-empty evidence and confidence in `[0,1]`;
- a strictly positive interval within its source clip;
- a valid producer semantic version; the runtime supplies profile identity/version,
  `tool_versions` (SDK, sampler and FFmpeg), and `input_key`.

Every output passes the shared event schema/semantic checks before filtering.
An invalid output fails the **entire unit**, even if earlier outputs were valid.
No partial event list is committed for that unit.

The runtime maps events into M13's gap-free unique session time. Fully hidden
duplicate intervals are dropped; crossing intervals are clipped to the first
unique moment. `attributes.source_start_ms`/`source_end_ms` preserve the detected
source interval, and evidence stays in source coordinates. Other attributes are
scalars. Session layout is checked again under the commit transaction so a
concurrent correction cannot commit obsolete event timing.

Events are **persisted analysis snapshots**, not live promises that a later edited
session has the same timing. M14 does not automatically analyze after import or
session correction. Re-run analysis after changing a layout. M19 owns the review
UI and correction/re-analysis reconciliation.

## Cache, persistence and failures

Migration **0010** adds detector provenance columns on `events` and a
`detector_runs` table keyed by session, asset and detector.

A cache key includes:

- complete resolved profile and parent digests, settings and selected locale;
- detector ID/version;
- derived proxy recipe key and verified byte digest;
- SDK, sampler and FFmpeg versions;
- ordered session membership, asset durations and applied overlaps.

A hit returns the same event IDs and does not decode or run the detector again.
Missing cached event records force recomputation. Failed/skipped/cancelled units
are never cached as successful. `force` runs detectors again without bypassing
input checks. Successful results, including empty results, commit independently,
so an interrupted job resumes with completed units cached.

Successful recomputation replaces only that producer's **unreviewed** events for
the asset/session. Reviewed, rejected and user-created events are preserved.
Previously successful results remain intact if a replacement fails or is cancelled.
Disabling a detector does not delete its historical snapshots.

The result contract `analysis.schema.json` reports `computed`, `cached`, `failed`
or `skipped` per clip/detector. Failure/skip entries include an error and no event
IDs. Unhandled detector exception text is not exposed (it may contain private
data). A job with failed units is `failed` with `analysis.partial_failure` **and**
the detailed result; successful events remain committed. Skipped incompatibilities
are explicit in a completed result. There are no fabricated fallback events.

## API and CLI

- `POST /v1/sessions/{id}/analyze` with
  `{profile_id, locale?, force?, idempotency_key?}` returns the durable `analyze`
  job. Invalid profiles fail submission with 422 and useful field paths. Profiles
  are revalidated at execution in case local data changed after submission.
- `GET /v1/events?session_id=<id>&limit=200&offset=0` returns event snapshots,
  ordered by time and ID (limit capped at 1000). It has the existing worker token,
  loopback, Host and correlation protections. No webview allowlist is widened.

From the repository root:

```bash
uv run --directory services/media-worker owm profiles validate ../../profiles/generic-open-world/profile.json
uv run --directory services/media-worker owm demo
uv run --directory services/media-worker owm analyze ses_<ULID> --library /absolute/library --profile generic-open-world
```

CLI output is JSON; errors use nonzero exit codes. `demo` uses a temporary directory,
generates three seconds of white video, imports it, creates a proxy and persists a
temporal observation. It cleans up on exit. No media, model or database is committed.

## Validation

- Shared TypeScript/Python fixtures cover profile metadata, locale versions, event
  provenance, and analysis-result success/failure contracts.
- `tests/detectors/test_runtime.py` covers inheritance, hostile manifests,
  compatibility, immutable inputs, temporal flicker, cache changes, detector lifecycle
  failures, cancellation/resume, reviewed-event retention and layout races.
- `tests/media/test_detectors.py` exercises real FFmpeg/proxy input, source hash/mtime,
  tampered derived bytes, decode cancellation, the authenticated job/API and CLI.
- Every migration fixture upgrades through 0010; existing events retain their data.

These are local synthetic/automated results. They do not validate game compatibility,
physical-device quality, desktop playback, or release packaging.

### Synthetic processing measurement

On the local arm64 development machine, five runs over 7,200 in-memory 64×36
white frames (one hour at 2 fps) produced one temporal event in a median **0.099 s**
(range 0.097–0.130 s). This measures only the simple example's processing loop; it
excludes proxy generation, decode and I/O and is not gameplay-detector performance
evidence.
