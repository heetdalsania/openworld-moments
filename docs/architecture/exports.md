# Open exports and manifests (M27)

Saved projects can be exported in documented formats that other tools read, so a
project is never locked into this application. Every export is built from the
**saved** revision (never an unsaved recovery draft) and is deterministic: exporting
unchanged data twice gives identical bytes. Nothing reads the clock, so the only
timestamps are stored ones (`saved_at`, a render's finish time).

In the editor's **Export** panel, **Open formats** offers each format and a **Save
export…** button. Each completed render has **Save manifest…**. The desktop host
fetches the export from the worker and writes it through a native save dialog with
a fixed extension; it never overwrites an existing file and the web view never
names a path.

## Formats

| Format | File | Version | Stability | Carries | Paths |
|---|---|---|---|---|---|
| Project JSON | `<title>.owm.json` | `openworld-moments.project` 1.0 | stable | everything in the project (lossless) | optional |
| Session events | `<title>.jsonl` | `openworld-moments.events` 1.0 | stable | every current event with evidence, provenance, review and project times | never |
| Captions | `<title>.srt` / `.vtt` | 1.0 | stable | caption text and timing | never |
| Markers | `<title>.csv` | 1.0 | stable | cuts, events, captions, text/blur overlays, gain/mute ranges | never |
| OpenTimelineIO | `<title>.otio` | 1.0 | stable | cuts (video + audio tracks), events and captions as markers, metadata | optional |
| FCPXML | `<title>.fcpxml` | 1.10-experimental | **experimental** | cuts, events and captions as markers | optional |
| Render manifest | `<render>.manifest.json` | `export-manifest` (contracts 1.21) | stable | source hashes, segments, preset, encoder, tools, output hash, detectors, profiles | never |

The API returns an `ExportResult` (`export-result` contract): `format`,
`format_version`, `stability`, `filename`, `media_type`, `content`, `sha256`,
`capabilities` (what the format carries), `warnings` and `includes_paths`.

Examples: every format is checked byte-for-byte against the goldens in
[`services/media-worker/tests/exports/goldens/`](../../services/media-worker/tests/exports/goldens/),
exported from a synthetic project with Unicode captions, events, overlays, audio
ranges, crops and vertical framing.

### Project JSON (`project-export` contract)

```json
{
  "format": "openworld-moments.project",
  "format_version": "1.0",
  "schema_version": "1.21",
  "generator": { "name": "openworld-moments", "version": "0.0.0" },
  "project_revision": 3,
  "saved_at": "2026-11-21T11:00:00.000Z",
  "capabilities": ["audio_gain", "…", "vertical_crop"],
  "warnings": [],
  "document": { "…": "the portable editor-project envelope (M21)" },
  "extensions": {}
}
```

The `document` is exactly the M21 portable envelope, so it imports back through
`POST /v1/projects/import`. Source paths appear only in `source_locations`
(`file:` URIs) when requested.

### Event JSONL (`event-export` contract)

The first line is a header (`record: "header"`, session, layout key, event count).
Each following line is one event, ordered by effective start then ID:

- `observation`: the original detector/model/user event, unmodified;
- `effective`: the audited view (latest review decision: label, interval, state,
  revision);
- `status`: `current`, `stale` or `legacy` timing (M19);
- `project_ranges`: where it lands on the project timeline (empty when outside).

Rejected events are included, marked `rejected`. Lines use compact canonical JSON
with sorted keys.

### SRT and WebVTT

The same plain-text subset as the M23 desktop serializer, byte-for-byte (the worker
re-serializes the desktop's shared fixtures exactly):

- sequential cue numbers and `HH:MM:SS,mmm` (SRT) or `HH:MM:SS.mmm` (WebVTT);
- WebVTT escapes `&`, `<` and `>`;
- no styling or cue settings;
- Unicode is kept as UTF-8.

Cue times are the project's exact milliseconds. Placement, style and burn-in are not
part of these formats and produce a warning.

### CSV markers

UTF-8 without BOM, CRLF line endings (RFC 4180), columns:

```text
kind,label,start,end,start_ms,end_ms,duration_ms,detail
```

- `kind` is one of: `cut`, `event`, `caption`, `text`, `blur`, `gain`, `mute`.
- Rows are sorted by start time.
- Text that would start a spreadsheet formula (`= + - @`, tab or CR) is prefixed
  with `'` (CSV injection guard).

### OpenTimelineIO

- One timeline with a video track and an audio track of `Clip.2` items referencing
  each source.
- Times use the first clip's frame rate (30 fps if unknown), expressed exactly from
  milliseconds; values may be fractional frames.
- Media references are `ExternalReference` with the URL-encoded original file name
  (or a `file:` URI when locations are included), or `MissingReference` for sources
  that need relinking. Hashes are kept in clip metadata.
- Events (except rejected ones) and captions are `Marker.2` on the video track.
- Crops, vertical framing, blur, text overlays and audio changes are kept under
  `metadata.openworld_moments` with warnings.

### FCPXML (experimental)

FCPXML 1.10 with one format, one asset per source (`uid` = SHA-256) and a spine of
`asset-clip` elements; events and captions become `marker` elements in clip source
time. Times are milliseconds (`n/1000s`) and may not fall on frame boundaries of the
importing project; there is no Apple DTD validation here. Treat it as a starting
point and check timing after import.

### Render manifest (`export-manifest`)

Written next to every completed render and stored with the render record (migration
0017), with the same canonical bytes. It contains:

- `render_id`, `project_id` and `project_revision`;
- source SHA-256 and original names, and segments;
- preset, size, frame rate and layout;
- `encoder`;
- `tools.ffmpeg` and `tools.render_engine`;
- `output` (SHA-256, size, duration);
- the `detectors` and `profiles` (ID and version) behind the session's events at
  render time;
- the app version.

It contains no paths. `GET /v1/renders/{id}/manifest` re-exports the stored copy.

## Versions and compatibility rules

- Each file names its format and version. Readers accept every `1.x`. Additions in a
  later minor version are optional fields or live under `extensions`, which readers
  preserve and may ignore. A `2.0` would be a breaking change.
- Contracts 1.21 add `export-result`, `project-export` and `event-export`, and extend
  `export-manifest` with optional provenance fields. Older manifests remain valid.

## Privacy

- No format includes an absolute path unless **Include file locations** is ticked,
  and only project JSON, OTIO and FCPXML offer it. Missing files are left out with
  an `export.paths_unavailable` warning.
- Caption, marker and event exports refuse the option.
- Exports contain project text, captions and on-screen text (OCR) because the user
  asked for them; nothing is sent anywhere.

## Warnings instead of silent loss

| Code | When |
|---|---|
| `export.crop_not_supported` | safe/fill/manual crops (OTIO, FCPXML, CSV) |
| `export.vertical_crop_not_supported` | vertical 9:16 framing (OTIO, FCPXML) |
| `export.blur_not_supported` | privacy blur regions (OTIO, FCPXML): check privacy before publishing elsewhere |
| `export.text_overlay_not_supported` | text overlays (OTIO, FCPXML) |
| `export.audio_gain_not_supported` | project gain or gain ranges (OTIO, FCPXML; project gain in CSV) |
| `export.audio_mute_not_supported` | mute ranges (OTIO, FCPXML) |
| `export.captions_as_markers` | captions exported as markers (OTIO, FCPXML) |
| `export.caption_style_not_supported` | caption placement/style/burn-in (SRT, WebVTT) |
| `export.no_captions` | the project has no captions (SRT, WebVTT) |
| `export.source_missing` | a source needs relinking (referenced by name and hash only) |
| `export.paths_unavailable` | a requested source location cannot be found |

Refusals (HTTP 422/404/409):

- `export.unknown_format` and `export.paths_not_supported`;
- `export.captions_invalid`: a cue a plain caption file cannot hold;
- `export.no_session`: event export of a project without a session;
- `export.not_found`;
- `export.manifest_unavailable`: the render did not complete.

## Validation

```bash
uv run --directory services/media-worker pytest tests/exports tests/media/test_caption_playback.py
uv run --directory services/media-worker otiostat tests/exports/goldens/timeline.otio
OWM_UPDATE_GOLDENS=1 uv run --directory services/media-worker pytest tests/exports   # deliberate golden update
```

- **Byte stability:** goldens and repeated exports; unrelated changes and unsaved
  drafts leave every export identical.
- **Contracts:** each export validates against its contract, including every JSONL
  line.
- **Reference library:** OpenTimelineIO 0.18 (a test-only dependency) reads the
  timeline, clip ranges, duration and markers, and writes it back; `otiostat` reports
  2 tracks, 4 clips, 43.3 s (00:00:43:18 at 60 fps) for the golden.
- **Captions:** round trips, and the desktop's shared SRT/WebVTT fixtures
  re-serialize byte-for-byte. FFprobe reads both formats with the project's exact cue
  times (playback spot check).
- **CSV:** parses back and neutralizes formulas.
- **FCPXML:** parses as XML with the expected spine.
- **Fixtures:** missing sources and unsupported operations, privacy (no paths
  without opt-in), and the real FFmpeg render manifest (sidecar = stored = API
  bytes).

## Out of scope

Importing third-party editor projects, and lossless transfer of effects the target
format cannot represent.
