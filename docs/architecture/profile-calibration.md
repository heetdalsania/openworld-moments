# Profile calibration (M15)

Open **Settings → Calibrate detector profile regions** (`#/calibration`). Choose an
installed profile and an imported clip. Prepare a playback copy if needed; the job
center owns progress, cancellation and retry. Check again after it finishes.
Seek with the player or the millisecond field and choose **Capture this frame**.
The captured picture stays fixed while you seek. Clear it or capture again to replace it.

## Coordinates and controls

Regions are `[x, y, width, height]` in the upright picture, from its top left.
Rotation is accounted for using the imported asset's video metadata. Playback
copies are upright SDR; the overlay has precisely the picture's aspect ratio,
without letterbox bars. Source resolution determines keyboard increments, while
crop samples use the playback copy's actual pixels. No source is written.

- Tab to a named region, then use arrows to move one source pixel.
- Shift + arrows moves ten pixels; Alt + arrows changes width/height from the
  bottom right (Shift also multiplies resize increments).
- Select **Move selected region** or **Resize selected region**, then drag.
- To draw, enter an unused region name, choose **Draw new region**, and drag.
  Dragging backwards works. Names use the shared contract's lowercase slugs
  (letters/numbers, separated by hyphens or underscores, maximum 64 characters).
- **Add region** creates a centered region without requiring pointer input.
  All bounds also have labelled numeric fields. Custom regions can be removed.
  Base names stay fixed because detectors and safe zones refer to them.
- Escape or pointer cancellation abandons a drag. Movement/resizing clamps to
  picture bounds. Invalid numeric edits remain visible, but cannot be saved.
- Dashed outlines show base regions; the selected override has a thicker border.
  The textual diff is available without relying on color. Reset one base region
  or reset all, which also removes custom regions.

Coordinates round-trip across 720p, 1080p and 4K without resolution-dependent
rounding. Pixel rounding happens only when displaying a derived crop. Crops are
in-memory only until **Export crop sample…** explicitly writes a PNG. Color,
BT.601-style grayscale, and threshold previews are local inspection tools;
these controls do not change installed detector preprocessing.

**Preview built-in detector** sends one bounded 64×36 grayscale sample and the
current regions to the shipped synthetic detector's real SDK lifecycle. It does
not save events or run a job. One frame cannot satisfy the example's default
three-frame confirmation rule. The UI also displays a single-frame brightness
signal for orientation. No gameplay detection or temporal-quality claim follows
from this preview. Other profiles report an unavailable preview until a built-in
adapter exists; arbitrary executable code cannot be loaded.

## Persistence and profile updates

The worker stores a sparse patch in SQLite's existing `settings` table at
`calibration.roi.v1.<profile-id>`. No migration is needed. It never edits an
installed manifest. Only differing and new regions are stored; untouched defaults
track updates. The analyzer resolves this patch before constructing its versioned
input/cache key. Reset restores the exact current base and its original cache key.

A patch retains the original base version and resolved SHA-256 key. If the base
changes, show a review notice and apply saved coordinates over new defaults.
Changing game family or frame compatibility fails closed; the patch is retained,
and the user can reset or import a compatible patch. Invalid combinations do not
run analysis. Save/preview reject an old base key so an old tab cannot overwrite a
new profile unknowingly. **Reload installed profile and saved overrides** reads
fresh state and discards unsaved UI edits. Successful mutations update the shared
query cache, so navigation does not restore an old edit.

## Patch format and API

`ProfilePatch` is the new **1.10** shared JSON contract. It contains only:

- `schema_version`, `profile_id`, `base_version`, `base_key`;
- `game_family` and `frame` compatibility (aspect ratios, minimum dimensions);
- sparse named normalized `regions`;
- `provenance`: `tool: "owm-calibration"`, format version `"1"`, UTC `created_at`.

Unknown fields, image bytes, asset IDs, filenames and paths are not permitted.
Import is bounded at 64 KiB, 128 overrides, and validated through the shared
schema/semantics and M14 resolved-profile validator before storage. Incompatible
or invalid imports leave the previous patch untouched. Import replaces the local
patch for the explicitly selected profile; it does not install a profile.

| Method | Route | Data |
|---|---|---|
| GET | `/v1/profiles` | Up to 128 local catalog entries; directories without manifests are omitted |
| GET | `/v1/profiles/{id}/calibration` | `base`, `base_key`, `effective`, `patch`, `base_changed`, `conflict` |
| PUT | `/v1/profiles/{id}/calibration` | `{base_key, regions}` → authoritative state |
| POST | `/v1/profiles/{id}/patch` | `ProfilePatch` → authoritative state |
| POST | `/v1/profiles/{id}/reset` | Empty body → exact current base state |
| POST | `/v1/profiles/{id}/preview` | `{base_key, regions, gray, source_ms}`; exactly 2,304 bytes as integers; ephemeral SDK result |

All use the existing authenticated loopback guard and explicit host allowlist.
`profile.invalid` returns 422, with field paths. Broken manifests report errors
without hiding valid profiles. No API takes an arbitrary profile filesystem path.
The preview result reports availability, producer ID/version, sample count,
required confirmation frames, and evidence/confidence for any observations.

The host's `calibration_export_patch(profile_id)` re-reads the saved validated
patch from the worker and offers a native JSON save dialog. Unsaved edits cannot
be exported as a patch. `calibration_export_sample(data)` is a separate PNG save
dialog, bounded at 4 MiB. The UI receives a boolean: saved or picker cancelled.
Both require a new filename of the expected extension. Exclusive creation refuses
existing files, symlinks and hardlinks, including source footage.

## Validation and boundaries

- Coordinate units: 720p/1080p/4K, 4:3, portrait, ultrawide, letterbox transforms,
  edges, subpixel drag, keyboard increments, grayscale/threshold.
- UI components: loading/empty/error/retry, invalid edits, save failure, custom
  names, keyboard across five frame shapes, export cancellation, import/reset,
  preparation and decode errors, changed profiles, navigation persistence.
- Worker: API authentication, JSON export/import/reset round-trip, restart,
  sparse defaults/update survival, stale keys, invalid imports, immutable catalog,
  analyzer integration and ephemeral SDK preview.
- Rust `calibration_e2e`: real supervised worker via allow-listed routes, exported
  JSON file round-trip, restart, rejection, exact reset, catalog preservation.
- Real Chromium: generated FFmpeg video through a temporary host bridge; capture,
  keyboard, pointer drawing, crop/preprocessing, save/export/import/reset. This
  checks browser video/canvas behavior. Native dialog interaction and WKWebView /
  WebView2 behavior are separate platform validation; no Windows/macOS release
  support claim is made here.

The canvas edits rectangles only. There is no model training, automatic upstream
editing, marketplace, gameplay detector or full temporal replay UI. A captured
frame is a browser-decoded proxy sample, not a guarantee of source-frame-exact
seeking. Base compatibility describes analysis support; adjusting coordinates
does not establish a game's supported aspect ratio or detector accuracy.

Run the automated lanes from the repository root:

```bash
OWM_REQUIRE_FFMPEG=1 pnpm check
pnpm build
cargo test -p openworld-moments-desktop --test calibration_e2e
uv run --directory services/media-worker pytest tests/detectors/test_calibration.py
```
