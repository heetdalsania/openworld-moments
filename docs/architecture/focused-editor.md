# Focused editor

M22 connects the [M21 project model](./editor-projects.md) to a single-primary-track
editor. Sources remain immutable. Captions, gain, compositing, final crops and
rendering belong to later milestones.

## Routes and data flow

- `#/projects`: `ProjectsView` lists 50 projects per page, including legacy story
  drafts. Loading, retry, empty and offline states are explicit. Unsaved drafts
  retained in this window appear above the saved list.
- `#/session/<id>`: `CreateProject` obtains the current layout key and duration,
  accepts a title and end-exclusive millisecond range, and calls M21 creation.
  Layout changes refuse creation without losing the selection. Cancellation
  changes no saved project; committing creation disables cancellation.
- `#/project/<id>`: `EditorView` opens a `ProjectWorkspace`, shows preview, cut
  inspector and proportional primary track, and exposes save/recovery status.

Additive authenticated metadata endpoints (also allow-listed by Rust):

| Method | Route | Response |
|---|---|---|
| GET | `/v1/projects?limit=50&offset=0` | `{items, total, offset}`; items have `id`, `title`, `session_id`, `updated_at`, `revision` (legacy draft: 0). Limit 1–100, offset 0–100000. |
| GET | `/v1/sessions/{id}/project-selection` | `{layout_key, duration_ms}` for M21 manual creation; stale keys remain rejected by the create endpoint. |

No schema version or database migration changes. Existing project reads/saves and
source binding rules remain authoritative.

## Commands and durability

`ProjectWorkspace` freezes the visible validated snapshot and routes trim, split,
delete, reorder and aspect settings through M21 `EditorHistory`. Undo/redo restore
snapshots and playback source mapping. Trim gestures commit on pointer release or
range-key release; pointer cancellation resets local fields. Numeric controls are
available for exact times. Every draggable cut also has Move earlier/later buttons
and a selected-cut dropdown, including very short cuts.

M21 `ProjectAutosave` debounces 750 ms and serializes revision-checked saves. The
workspace distinguishes Saved, Unsaved, Saving and error states, including edits
made while a save is running. Save now retries retained dirty state. Worker errors,
revision conflicts and hash navigation never replace local edits with a fetched
document. Recovery JSON exposes the complete local document for copying. On a
conflict, copy that JSON before reloading to inspect the newer saved version;
there is no automatic conflict merge.

The window retains up to ten workspaces/pending opens, evicting only clean
histories. If every slot is dirty, opening another project fails visibly. A
before-unload warning protects pending saves; it cannot guarantee writes during
process termination. After a successful save, a full reload restores the EDL;
undo history is intentionally in memory.

## Preview and context

`projectTimeline.ts` maps cut IDs and end-exclusive source ranges to the M13
`SessionPlayer`. Stable cut keys distinguish multiple instances of one source.
Edits preserve the source moment in the same retained cut, clamping to its new
range when trimmed away. Removed cuts fall back to project start. Sessions
retain their earlier asset-based mapping. Boundary seeks and frame steps use the
existing player and source frame rate (average for variable-rate material).

`projectMedia.ts` checks binding identity against library SHA/duration metadata
and refuses unresolved bindings or identity differences. Ready proxies are
preferred. An original is a fallback only when M21 reports `available_unverified`
and the library has not marked it missing. This is availability, not a fresh hash
verification. Missing/offline media blocks that preview and keeps editing usable;
Refresh preview rechecks metadata without replacing the EDL. Prepare playback
copy requests M08's always-proxy policy. Background jobs expose cancellation;
Library exposes original restoration. Portable project binding selection still
uses the M21 API; this milestone adds no portable-import dialog.

Filmstrips and waveforms display retained source ranges. Track proportions and
pointer time use the same inner scrollable track, with no timing gaps between
cuts. Read-only event context requires matching session IDs and layout digest;
stale/rejected items are omitted. The first 50 reviewed items are inspected, with
that limit stated. Intersections map through source ranges into every retained
cut. Markers seek only; they never edit events.

The preview frame supports 16:9, 9:16 and square with fit/letterboxing. It explicitly
does not represent final crops, captions, overlays or gain. Two decoders may
buffer during clip switches; gapless real-time playback is not guaranteed. Native
codec support and real-game variable-rate precision require platform validation.

## Keyboard controls

Shortcuts apply while focus is in the editor, outside text/numeric/select fields.
Native button Space/Enter activation is preserved. Keyboard help opens and focuses
a details panel without changing the project hash.

| Key | Action |
|---|---|
| Space or K | Play/pause |
| Comma / period | Previous / next source frame |
| `[` / `]` | Previous / next cut boundary |
| Home / End | Project start / end |
| S | Split selected cut at playhead |
| Delete | Remove selected cut |
| Ctrl/Cmd Z; Shift Ctrl/Cmd Z | Undo; redo |
| Ctrl/Cmd S | Save now |

Tab reaches all commands. Range handles support arrows/Home/End/Page keys, and
numeric trim/split/seek controls provide precise alternatives. The global skip
link focuses main content without overwriting the hash route.

## Validation and synthetic browser fixture

`EditorView.test.tsx` covers command interactions, pointer cancellation, keyboard
editing, undo/redo, save/reload, conflicts, missing sources, worker restarts,
recovery and navigation. `projectTimeline.test.ts` covers source mapping, repeated
assets, retained-cut clamping, boundaries and current context. Rust's
`editor_create_trim_split_reorder_and_reopen` drives a real worker and FFmpeg,
restarts the worker, compares the EDL and checks unchanged source bytes.

For manual Chromium verification, run the frontend on `127.0.0.1:1420`, then:

```sh
uv run --locked --directory services/media-worker python tests/editor_browser.py --artifacts ../../output/playwright
```

The manual fixture makes temporary synthetic clips and library data, starts a real
worker and emits a local IPC bootstrap script plus fixture manifest. Playwright
CLI loads that script before navigation and redirects the Windows-style media
origin to the closed loopback test bridge, which supports byte ranges. This
replaces only native transport; it is never shipped as a production API. The
worker token is not exposed to the page or printed. Close the fixture process to
remove its temporary library. Browser screenshots/reports stay in ignored
`output/playwright/`; never commit generated media.
