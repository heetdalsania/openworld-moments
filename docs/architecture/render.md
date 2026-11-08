# Render engine (M24–M25)

The render engine compiles a saved editor project revision (M21) into a safe FFmpeg
argument array, renders a horizontal or vertical H.264/AAC MP4, validates it, and only then
marks it complete.

Code: `services/media-worker/openworld_moments/render/`:
- `plan.py`: the render IR and compiler;
- `encoders.py`: the encoder registry, quality mapping and capability probe;
- `presets.py`: the preset catalog;
- `validate.py`: output validation;
- `service.py`: orchestration and records.

Presets live in [`presets/render/`](../../presets/README.md).

## Pipeline

1. **Read the committed project.** The renderer reads the last saved revision, never
   unsaved edits; the desktop flushes autosave before submitting. It refuses
   sources that are missing, mismatched, or `requires_relink` (M21).
2. **Verify the originals.**
   - Each referenced original is read in full and its SHA-256 compared with the
     project's source identity. A changed file fails with `render.source_changed`.
   - Originals are opened for reading only. Their size and mtime are compared again
     before completion.
   - Rendering uses originals, not proxies, for quality.
3. **Plan.** `build_plan` produces the IR (below) from:
   - the editor document, preset and encoder;
   - source facts: audio presence, average frame rate, HDR transfer.
4. **Check free space.** The output-size estimate (below) plus 64 MiB must be free in
   the library folder, or the render fails early with `render.disk_full`.
5. **Encode.**
   - The graph is written to `graph.txt` inside an owned staging folder,
     `<library>/staging/renders/<job>/`.
   - FFmpeg runs as an argument array, with `cwd` set to that folder, a timeout of
     the larger of 600 s and 20× the duration, the paths redacted from logs, and
     `-progress pipe:1`.
   - `out_time_us` drives job progress, from 5% to 90%.
6. **Validate.** The output is checked (see [Validation](#validation)).
7. **Complete atomically.**
   - The export manifest (`export-manifest` contract; no paths) is written. Since M27 it also
     records the render ID, project revision, encoder, FFmpeg and render-engine versions,
     output hash and the session's detector/profile versions, and is stored in
     `render_jobs.manifest_json` with the same canonical bytes ([exports](./exports.md)).
   - The MP4 and manifest are moved into `<library>/renders/<project>/<job>.{mp4,manifest.json}`.
   - **Only then** is the record set to `ready`.
   - The staging folder is always removed, including on failure and cancellation,
     and also at worker start.

## Render IR (`plan_version` 1)

Stored with every record (contract `render`, `$defs.RenderPlan`). Its fields:

- `preset`: the complete validated preset document.
- `encoder`: `{id, kind, quality_note?}`.
- `output`: width, height, fps and `audio`.
- `duration_ms`.
- `sources`: index, asset ID, SHA-256, original name, audio, tone-mapped.
- `segments`: the timeline in pieces. A crop keyframe splits a segment, because
  keyframes hold until the next one. Each piece has:
  - `source`, `in_ms`, `out_ms` and a contiguous `timeline_start_ms`;
  - an exact `frames` and `samples` count;
  - `crop` `{mode, region?}`.
- `audio`: global gain, gain ranges and mute ranges.
- `blur_overlays`: privacy blurs, always rendered.
- `omitted`: only `text_overlays` or `burned_captions`, and only by explicit request.
- `notes`: shown to the user, for example "safe renders as fit" or "HDR tone-mapped".
- `command`: `{argv, filter_complex}`. The argument template uses `{source:N}` and
  `{output}` placeholders and contains no paths or user text.
- `tools`: `{ffmpeg, render_engine}`.

The plan is a pure function of the project revision, preset, encoder and FFmpeg
version. It is reproducible, and it is what a bug report needs.

### Exact durations

Frame and sample counts are computed from **cumulative** timeline positions:
- video frames: `round(end·fps) − round(start·fps)` per piece;
- audio samples: `end·48 − start·48` per piece, at 48 kHz.

So rounding never drifts across pieces, and total video duration is within half a
frame of the target. Each piece is then constrained exactly:
- **Video:** input-seeked (`-ss`/`-t` with a 1 s margin), set to the output fps,
  extended by up to 2 s by cloning its last frame (`tpad`) if the source ends early,
  then cut to exactly `frames` (`trim=end_frame`).
- **Audio:** resampled to 48 kHz stereo, padded (`apad`), then cut to exactly
  `samples` (`atrim=end_sample`).

A clip without audio gets generated silence (`anullsrc`) so the track stays
continuous. A project whose clips all lack audio is rendered video-only.

## Compiler

**Per piece:**
1. **HDR clips** first get the M08 LUT tone map: BT.2020 → `gbrp16le` →
   `lut3d=tonemap-{pq,hlg}.cube` → BT.709. The LUT files are written into staging.
2. **Crop regions** (source-normalized) become `crop=iw*w:ih*h:iw*x:ih*y`.
3. **Layout:**
   - `fill` scales to cover and centre-crops to the output size;
   - `fit`, `manual` and `safe` scale to fit and pad with black;
   - `safe` renders as `fit` with a note. HUD-aware safe layouts are M25.
4. **Normalize:** `setsar=1`, then `fps`, `tpad`, `trim`, and `format=yuv420p`.

**After concat:**
- **Blur overlays** (output-normalized regions):
  - converted to integer pixel rectangles, at least 8×8 px, shifted to stay inside
    the frame;
  - blurred with `boxblur` (radius ¼ and ⅛ of the short side) and overlaid with
    `enable='between(t,s,e)'`.
- **Audio:** `asetnsamples` gives 10 ms resolution. Then:
  - project gain applies outside the gain ranges;
  - each range's gain applies inside it;
  - mute (`volume=0`) is last, so it dominates.

**Encode:** `-movflags +faststart -map_metadata -1 -map_chapters -1`, so no source
metadata (titles, locations, creation tags) reaches the output.

**Graph file:** the graph is read from a file, because large graphs exceed Windows'
32,767-character command line. FFmpeg 7 and later use `-/filter_complex graph.txt`;
FFmpeg 6 uses `-filter_complex_script graph.txt`. FFmpeg 8 removed the latter.

**Limits:**
- at most 120 pieces, because each is one FFmpeg input;
- at most 100 blurs and 500 audio ranges;
- on Windows, the materialized argument list is capped at 30,000 characters.

Exceeding a limit is refused with `render.too_complex`.

**Text is a hook.**
- Drawing text overlays and burned-in captions needs `drawtext`/libass, which common
  FFmpeg builds (including Homebrew's) lack. M24 therefore records them in the IR
  but does not draw them.
- A project containing them is refused with `render.text_unsupported`, unless the
  request sets `omit_text: true`. The plan then lists them in `omitted`, and the UI
  requires an explicit checkbox.
- Privacy blurs are never omitted.

**Argument safety:**
- Only validated numbers and constants enter the graph.
- Titles, captions, overlay text and file names never do.
- Paths reach FFmpeg only as single `file:<path>` argv elements; there is no shell.
- `-protocol_whitelist file,pipe,lavfi` blocks network protocols.

A unit test renders a project whose title, caption and file name contain shell
metacharacters, and asserts none of them appears in the command.

## Presets

| Preset | Output | Video | Audio |
|---|---|---|---|
| `horizontal-1080p30` | 1920×1080, 30 fps | CRF 20 | AAC 192 kb/s |
| `horizontal-source-fps` | 1920×1080, first clip's average fps | CRF 20 | AAC 192 kb/s |
| `horizontal-720p30` | 1280×720, 30 fps | CRF 23 | AAC 160 kb/s |

- **Format:** each preset is a `render-preset` JSON file. The catalog skips links,
  files over 64 KiB, invalid documents, an ID that does not match the file name,
  and HEVC.
- **CPU encoder:** H.264 High, `-preset medium`, CRF or bitrate (bitrate mode sets
  `maxrate` and `bufsize = 2×`), yuv420p.
- M25 adds `vertical-1080x1920-30` and `vertical-source-fps` (1080×1920).
- **Not shipped yet:** Discord-size presets remain M27.

## Hardware encoders

The supported encoders are:
- `libx264` (CPU, always available);
- `h264_videotoolbox`;
- `h264_nvenc`;
- `h264_qsv`;
- `h264_amf`.

**Probe:** an encoder is offered only if it is built into this FFmpeg
(`-encoders`) **and** a real 0.5 s test encode succeeds. Brand or GPU presence never
counts. Results are cached per FFmpeg version (`GET /v1/render/encoders`).
Unavailable encoders carry a reason:
- "Not built into this FFmpeg";
- "The test encode failed… (no supported hardware or driver)".

**Quality mapping:** hardware encoders use their own quality scales, mapped from the
preset's CRF. Each has a `quality_note` shown before rendering:

| Encoder | Mapping |
|---|---|
| VideoToolbox | `-q:v round(100 − 1.75·CRF)` (CRF 20 → 65) |
| NVENC | `-rc vbr -cq CRF -b:v 0` |
| Quick Sync | `-global_quality CRF` |
| AMF | `-rc cqp -qp_i CRF -qp_p CRF` |

**Failure:** if a hardware encode fails, the render fails with
`render.hardware_encoder_failed`. The record and job error carry
`fallback: {encoder: "libx264"}`, and the UI offers **Render with the CPU encoder
instead**. Nothing retries silently, so quality never changes without the user
choosing.

## Validation

| Check | Rule |
|---|---|
| container | MP4/MOV family |
| duration | within **100 ms** of the plan duration |
| video_stream, resolution, pixel_format, frame_rate | exactly one H.264 stream at the plan size, yuv420p, fps within 1% |
| rotation | no rotation side data or tag; FFmpeg auto-rotates, so the output is upright |
| audio_stream | one AAC stereo 48 kHz stream if the plan has audio, otherwise none |
| metadata | only `major_brand`, `minor_version`, `compatible_brands` and `encoder` tags |
| decode_start / middle / end | one frame decodes at 100 ms, the middle, and the end minus 150 ms |
| black_frames | a sample with mean luma below 20 is a filter error if the source frame at that moment has mean luma of at least 40 |

- **Empty or malformed output:** if the output is empty or FFprobe cannot read it,
  every check fails.
- **Failed validation:** fails the render (`render.validation_failed`). The output is
  discarded and the record lists the failed checks.
- **Audit:** the FFprobe audit (`validation.probe`) is stored: format, duration,
  stream counts, codec, profile, size, pixel format, fps, rotation, audio, and tag
  names.

## Free-space estimate

`duration × (video + audio bitrate) / 8 × 1.25`. With CRF, the video bitrate is taken
as `width × height × fps × 0.15` bits/s, which is deliberately generous. FFmpeg's
"No space left on device" and OS error 28 also map to `render.disk_full`.

## Records, API and UI

**Records:** migration **0015** extends `render_jobs` with:
- project revision, encoder;
- plan, validation and output JSON;
- fallback and finish time.

The record ID is the job ID. Outputs are library-relative; the contract pattern
refuses absolute paths.

| Surface | What |
|---|---|
| `GET /v1/render/presets` | Installed presets |
| `GET /v1/render/encoders` | `render-encoders` probe results |
| `POST /v1/projects/{id}/render` | `{preset_id, encoder?, omit_text?, idempotency_key?}` → `render` job (state `rendering`). Refused with 422 for an unknown preset or project, unavailable sources or encoder, or text without `omit_text` |
| `GET /v1/projects/{id}/renders` | Records, newest first |
| `GET /v1/renders/{job}` | One record |
| Desktop | Editor **Export** panel, described below |

The Export panel offers:
- preset and encoder choice, with unavailable encoders disabled and explained;
- hardware quality notes;
- an explicit text-omission checkbox;
- Render, which saves pending edits first;
- progress, with cancel in Background jobs;
- results with validation, notes, library path and the CPU fallback button.

The host allow-list adds exactly these five routes.

**Job behaviour:** a failed render is a failed job whose `result` is the record.
After a worker crash the job is requeued once and starts over in a clean staging
folder.

## Golden outputs

Generated projects, rendered with `horizontal-720p30` and FFmpeg 9.0.1 on an Apple M4
(`tests/media/test_render.py`):

| Golden | Target | Output | Notes |
|---|---|---|---|
| Single segment (trimmed 700–4700 ms) | 4000 ms | 4000 ms | AAC 48 kHz stereo, H.264 High; 1.7 s render |
| Two clips, one without audio, manual crop keyframes, blur | 5500 ms | 5500 ms | 3 pieces; silence generated for the silent clip |
| Mute 0.5–1.5 s, −6 dB project gain, +6 dB 2–4 s | 6000 ms | 6000 ms | muted below −80 dB; gains within ±1 dB of target |
| Unicode folder and file name, no audio | 3000 ms | 3000 ms | video-only output |

Every golden is exact to the millisecond here. The contract budget is 100 ms.

## Failure fixtures

- **Cancellation:** cancelling mid-encode kills FFmpeg. The record is `cancelled`, no
  MP4 exists under `renders/`, and staging is removed.
- **Hardware failure:** a hardware-kind encoder that fails mid-render gives a failed
  record with a CPU fallback. The CPU render is then a separate, successful,
  explicit choice.
- **Disk full:** refused at the preflight; stderr and errno mapping are also tested.
- **Validation:** empty, truncated, wrong-duration, and black-where-the-source-is-not
  outputs fail. Black source footage rendered black passes.
- **Changed source:** a same-size modified original is refused before rendering.
- **Text:** refused without `omit_text`; rendered and listed in `omitted` with it.

## Limits

- **Output:** horizontal and M25 vertical H.264/AAC MP4.
- **Not in M24:**
  - M25 now supplies vertical and HUD-aware layouts through independent variants;
  - text drawing (a hook here);
  - OTIO and sidecar export (M27);
  - HDR-preserving output (HDR is tone-mapped to SDR);
  - direct publishing.
- **Hardware encoders:** only VideoToolbox was exercised on real hardware, on an
  Apple M4. NVENC, QSV and AMF paths are covered by argument and probe tests, not
  by GPUs.
- **Long timelines:** pieces are limited to 120.
- **Getting the file out:** a render stays in the library (`renders/…`). Saving a copy
  elsewhere and opening the folder from the app are follow-ups (M27).

## M25 vertical extension

See [vertical layouts](./vertical-layouts.md) for independent per-cut framing,
new presets, smoothstep graph expressions, review/revision refusal, and foreground
black-frame validation. The horizontal pipeline above retains its existing behavior.
