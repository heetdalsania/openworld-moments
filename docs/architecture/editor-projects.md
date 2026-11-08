# Editor project model (M21)

M21 supplies the document, commands and persistence used by M22's focused editor
and M24's renderer. It introduces no timeline UI or rendering. Manual selection
works without events, transcripts, profiles or successful detectors.

## Renderer-facing document and invariants

Contracts 1.16 add `editor-project`, with `model_version: 1`, a nested existing
`Project` EDL, `layout`, and `sources`. `layout.aspect_ratio` is `16:9`, `9:16` or
`1:1`; a calibration/profile reference supplies both `profile_id` and
`profile_version`. It is metadata, never an instruction to download or execute a
profile. Each source records asset ID, original basename, SHA-256 and original
source duration. An explicitly confirmed replacement also records
`replaces_sha256`. Unbound portable sources carry `requires_relink: true`.
There are no machine paths, media bytes or external URLs.

The renderer uses the nested Project's source in/out, timeline start, crop,
captions, blur/text overlays and audio settings. Global audio gain applies outside
optional, non-overlapping `gain_ranges`; a range overrides it and mute takes
precedence. All annotation times are project-relative, not session-relative.
Crop keyframes are segment-relative and hold their value until the next keyframe;
the crop mode applies before the first keyframe. Manual crop requires a keyframe
at zero. M25 can add a versioned interpolation policy.

Both SDKs validate the same invariants and shared fixtures:

- Exactly one primary video track, which may be empty. Segments are contiguous
  from zero, in array order; no negative times, gaps, overlaps or empty ranges.
- Each segment ID is unique. Every segment has a source binding and
  `0 <= source_in_ms < source_out_ms <= source.duration_ms`.
- Timeline arithmetic stays inside JavaScript's safe integer range. Source
  durations are positive safe integers. Crop keyframes strictly increase inside
  the segment and regions remain normalized inside the image.
- Captions, overlays, mute and gain ranges are non-empty and lie inside the
  project duration. Captions/overlays/mutes may overlap; gain ranges may not.
- At most 1,000 source bindings, 4,096 segments, 1,000 keyframes per segment and
  10,000 entries per annotation category. Persistence accepts at most 4 MiB of
  canonical UTF-8 JSON per document. Unused source bindings are retained so a
  deleted clip can be added again and undo never loses source identity.

The existing `project` contract remains compatible with older 1.x documents.
Text overlays and optional gain ranges are additive; strict single-track editor
rules live in the **new** envelope rather than invalidating legacy projects.

## Commands and undo

`apps/desktop/src/editor.ts` exports `applyCommand(document, command)` and
`EditorHistory`. Commands are `add` (explicit segment ID and insertion index),
`trim` (source in/out), `split` (segment-relative offset and explicit new ID),
`delete`, `reorder` (exact ID permutation), and `settings` (title, layout,
captions, overlays or audio). Callers supply IDs; commands perform no IO or clock
reads. Add uses array position and recomputes timeline starts.

Commands clone and validate the input and output. Failure leaves the document,
undo and redo stacks untouched. Trim/split carry the active crop into the new
origin. Timed annotations follow retained **source content**: ranges crossing a
split become separate pieces, clips carry those pieces on reorder, and deleting
or trimming footage removes its annotation pieces. Extending a trim does not
invent captions or privacy regions for newly exposed footage. Repeated source
ranges remain distinct segment instances.

`EditorHistory.execute`, `undo`, `redo`, `document`, `canUndo` and `canRedo` return
detached values. Before/after snapshots make reversal exact, including crop and
annotations; redo never reruns a clock or allocates an ID. A successful new command
clears redo. History defaults to 100 commands (configurable 1–1,000), with an
additional 16 MiB serialized snapshot budget; the newest command remains
reversible. History is in memory and resets on reopen. The committed EDL and
previous recovery snapshot survive reopen.

## Autosave and recovery

`ProjectAutosave` in `apps/desktop/src/projectAutosave.ts` accepts the worker save
function and current revision. `schedule` uses a trailing **750 ms** debounce;
`flush` serializes pending writes, and `close` flushes before closing. A later
edit arriving in flight is retained and saved after its predecessor. Failure
keeps dirty state and exposes `error`/`pending`; another edit or explicit flush
retries. A revision conflict requires user-directed reload/reconciliation or
export of the pending document. There is no automatic overwrite/rebase.
`discard` explicitly clears pending state and timers; it cannot cancel a write
already submitted. Instantiate this controller in M22; M21 does not create a
background editor or start saves without user editing.

Migration `0014_editor_projects.sql` adds `editor_projects`, keyed by the same
`prj_` ID as `stories`. The autosave lives in the configured library's
`database.sqlite3`, not beside source footage. Current document, monotonically
increasing revision, previous committed recovery document, save time, and the
Story EDL/title/`edited` state change in **one** `BEGIN IMMEDIATE` transaction.
SQLite WAL handles process crashes. The previous committed snapshot can be
restored by explicitly saving it against the current revision, producing a new
revision. It is never restored automatically. Existing SQLite pre-upgrade backups
and health checks apply. Process-crash tests do not claim power-loss or faulty
storage durability beyond the existing SQLite WAL/NORMAL policy.

Saves compare `expected_revision`. Stale writes fail with
`project.revision_conflict` (409). An exact retry of the immediately preceding
save, ignoring the server-owned `updated_at`, returns the existing revision;
this covers a lost acknowledgement. Save cannot change project ID, creation time
or session binding, or silently replace existing source identity. M20 candidate
review refuses changes once an editor save marks its Story `edited`.

## Migration, missing sources and portable projects

Opening a legacy Story migrates its Project into model v1 in memory, obtaining
source metadata from the library. Empty legacy tracks become one empty track;
IDs, ranges, captions and other edits are preserved. There is no silent flatten,
ripple repair or dropping of unsupported tracks/annotations: invalid editor
layouts and missing legacy source metadata give an actionable refusal and leave
the stored story intact. The first successful editor save commits the envelope.
Future model versions are refused. Future changes to editor invariants require an
explicit model migration; applied SQL migrations stay immutable.

`GET /v1/projects/{id}` reports each source as `missing`, `mismatch`, or
`available_unverified`. Unavailable sources never delete or shorten edits. The
last state means current path/size and stored metadata are available; it is **not**
a fresh full-content verification. Consumers must gate preview/render on source
identity, and M24 must verify referenced originals and refuse `requires_relink` bindings before rendering. M05's existing verified
file relink can restore an original asset path without changing the EDL.

Portable export is exactly the validated envelope. Import creates a new project
ID and creation time and detaches the original session reference, retaining edit
segment IDs/ranges. Explicit `bindings` map portable source IDs to local library
asset IDs; there is no implicit filename or asset-ID match. Unmapped bindings are
retained with `requires_relink: true`, even if an identical local asset ID exists; a colliding local ID with a different hash is blocked
as a mismatch, never silently used. Selected bindings are read and SHA-256 checked
against the imported library identity. A hash mismatch requires the original
source ID in `confirm_replacements`; a shorter replacement still cannot put an
edit outside its source. Unavailable, changed, conflicting or invalid replacements
fail atomically. `relink` applies the same checks to an existing project, retaining
its ID/session and creating a revision/recovery snapshot. Hash reads happen
outside the write transaction; revision is checked again before commit. Library
methods accept a cancellation event and cancellation leaves no project write.
The visual cancellation/confirmation flow belongs to M22. Source media is only
opened for reading; no operation rewrites, renames or deletes it.

## Worker API and desktop host

All routes use the existing token/loopback guard and are narrowly allow-listed in
the Rust host. Request models forbid extra fields. Errors use `ErrorInfo`.

| Method and route | Request / result |
|---|---|
| `POST /v1/sessions/{id}/projects` | `{title, layout_key, start_ms, end_ms}` → new state (201) |
| `GET /v1/projects/{id}` | State plus source availability |
| `PUT /v1/projects/{id}` | `{document, expected_revision}` → committed state |
| `GET /v1/projects/{id}/portable` | Portable envelope |
| `POST /v1/projects/import` | `{document, bindings?, confirm_replacements?}` → new state (201) |
| `POST /v1/projects/{id}/relink` | `{expected_revision, bindings, confirm_replacements?}` → committed state |

State is `{document, revision, recovery}` (plus availability on GET). Manual
selection uses M13's unique, gap-free session time: later clips skip their hidden
overlap prefix. `layout_key` prevents selections from a stale session layout.
Creating a project is independent of detector/story generation. These are document
operations, not new job kinds, render endpoints or filesystem access routes.

## Validation

The worker tests cover manual overlap mapping, invalid/stale selection,
transactional save/reopen/recovery, two concurrent writers, missing/restored files,
legacy migration, accepted-story protection, portable round-trip, changed and
short replacements, explicit confirmation, cancellation and HTTP errors. A
subprocess exits after updating the Story but before committing the editor row;
reopening retains the entire last committed save and its recovery snapshot.
Temporary synthetic byte files establish no source mutation, not real-media
playback or recognition quality.

Desktop tests cover all commands and annotation/crop behavior, atomic rejection,
undo/redo, bounded history and autosave debounce/in-flight/failure/discard paths.
Fast-check generates 150 deterministic sequences of up to 60 commands (seed
`0x21`), validates each state and round-trips each command and the full history.
Shared TS/Python fixtures cover portable schema and semantic boundaries. No new
visual UI or real-game media is needed for this model milestone.

## M23 caption and audio extension

Contracts 1.17 add optional caption settings without changing model version or earlier invariants. Explicit caption/audio commands, current-preview behavior and sidecar serialization are documented in [captions and audio](./captions-and-audio.md). Existing retiming carries their timed data through edits.
