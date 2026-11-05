# Media probing

M04 turns one explicitly selected local file into a normalized, validated
`MediaProbe` (contract `media-asset.schema.json#/$defs/MediaProbe`) without
modifying it. Import, hashing, proxies, and thumbnails come later (M05, M06, M08).

Code: `services/media-worker/openworld_moments/media/`:

- `tools.py`: discovery and the capability report.
- `process.py`: the safe subprocess runner.
- `probe.py`: probing and normalization.
- `fixtures.py`: the synthetic fixture generator.

## FFmpeg requirement

| | |
|---|---|
| Minimum | **FFmpeg 6.0**: `libavformat` ≥ 60 and `libavcodec` ≥ 60 |
| Needed for probing | `ffprobe` |
| Needed for fixtures (tests) and later milestones | `ffmpeg` with `libx264`; `libx265` optional (HEVC fixture) |
| Tested | Ubuntu 24.04 package (6.1), Chocolatey on Windows (current release), Homebrew on macOS (9.0) |

Library majors are checked instead of the release string because Git and
distro builds report versions such as `N-118000-g1a2b3c` or `6.1.1-3ubuntu5`.
FFmpeg 6.0 is the floor because older builds lack `-display_rotation` and
report rotation inconsistently.

The app does not bundle FFmpeg yet; packaging decides whether to bundle or resolve it (M29).

### Discovery

For each of `ffprobe` and `ffmpeg`, the first match wins:

1. Worker flag `--ffprobe PATH` / `--ffmpeg PATH`.
2. Environment variable `OWM_FFPROBE` / `OWM_FFMPEG`.
3. `PATH`.

A tool that is missing or too old is looked up again on the next use, so
installing FFmpeg does not require restarting the worker.

## `doctor` and `/v1/capabilities`

```bash
pnpm media:doctor          # human-readable; exit 0 when probing works, 1 otherwise
uv run --directory services/media-worker python -m openworld_moments.doctor --json
```

The worker serves the same report at `GET /v1/capabilities` (authenticated
like every endpoint; `?refresh=true` re-runs discovery). Fields:

| Field | Meaning |
|---|---|
| `probe_ready` | `ffprobe` is present and new enough |
| `minimum` | `{ffmpeg_release: "6.0", libavformat: 60, libavcodec: 60}` |
| `ffprobe`, `ffmpeg` | `{status, source, path?, version?, libraries?, problem?}` |
| `status` | `ok`, `missing`, `too_old`, `unusable` (does not run or no version) |
| `source` | `flag`, `env`, or `path` |
| `decoders` | `{h264, hevc, av1, vp9, aac, opus}` → bool (from `ffprobe -decoders`) |
| `encoders` | `{libx264, libx265, aac}` → bool (from `ffmpeg -encoders`) |

The report is not a versioned contract yet. The first-run system doctor in packaging (M29) is its first UI consumer and may promote it to one.

## Probe job

Submit `POST /v1/jobs` with `{"kind": "probe", "params": {"path": "<absolute path>"}}`.

- `path` must be an absolute string (≤ 4096 characters, no NUL). Anything
  else is rejected at submit time with 422 `job.invalid_params`.
- States: `queued` → `probing` → `ready` | `failed` | `cancelled`.
- On `ready`, the job's `result` is the `MediaProbe`.
- The job is idempotent (read-only), so a worker crash requeues it, up to
  3 attempts.
- Timeout: 30 seconds per probe. Cancellation kills FFprobe within about 50 ms
  and the job ends `cancelled` without an error.

### Safety

- **Never writes.** The pre-check opens the file read-only. FFprobe reads only
  the header, and nothing is written next to the source. Tests compare SHA-256,
  size, and `mtime_ns` before and after for every fixture.
- **Arguments, not a shell.** The path is a single argument, `file:<path>`. The
  `file:` prefix keeps names like `concat:a|b`, `http…`, or `-x.mp4` from being
  read as protocols or options. `-protocol_whitelist file` blocks network and
  playlist fetches.
- **Bounded.** FFprobe's JSON is capped at 4 MB (the tool is killed past it).
  stderr keeps an 8 KB tail. The process is always killed and reaped on
  timeout, cancellation, or error.
- **Redacted.** The probed path is removed from stderr tails along with the
  usual user-path patterns. Messages never contain it. The result contains
  neither the path nor free-form container tags (titles, encoder strings,
  location).

## Normalization

| Field | Source | Rule |
|---|---|---|
| `container` | `format_name` | As reported, e.g. `mov,mp4,m4a,3gp,3g2,mj2` |
| `duration_ms` | `format.duration`, else video stream duration | Exact decimal → integer ms. Missing or ≤ 0 → `media.invalid_duration` |
| `size_bytes` | file size | |
| `bit_rate` | `format.bit_rate` | When reported |
| `creation_time` | `creation_time` tag (format, then video stream) | Converted to UTC with ms precision. Zero epochs (1904/1970) and junk are dropped. Only an input to capture-time estimation (M05) |
| `video` | First video stream that is not cover art | None → `media.no_video_stream` |
| `video.frame_rate` | `r_frame_rate` / `avg_frame_rate` | **Exact rational**, reduced (`30000/1001` stays `30000/1001`). The base rate for constant-frame-rate media, the average for VFR |
| `video.average_frame_rate` | `avg_frame_rate` | Exact rational |
| `video.variable_frame_rate` | base vs average | `true` when they differ by more than 0.1%. Header heuristic; frames are not decoded |
| `video.rotation` | display-matrix side data, else legacy `rotate` tag | **Clockwise** degrees for upright display, snapped to 0/90/180/270. FFprobe's display matrix is counter-clockwise, so `-display_rotation 90` reads as `270`. `width`/`height` stay the coded size |
| `video.color` | `color_primaries`, `color_transfer`, `color_space`, `color_range`, side data | `unknown`/`unspecified`/`reserved` omitted. `mastering_display` (nits), `content_light_level` (MaxCLL/MaxFALL), `dolby_vision` (profile/level) kept when present |
| `video.color.hdr` | transfer, Dolby Vision | `true` for `smpte2084` (PQ), `arib-std-b67` (HLG), or a Dolby Vision record |
| `audio[]` | audio streams | `{codec, channels, sample_rate_hz, channel_layout?}`. Unusable audio streams are skipped and counted in `other_streams` |
| `other_streams` | | Subtitles, data, attachments, cover art, extra video, skipped audio |
| `probed_with.ffprobe_version` | | For traceability |

**Not covered by probing:** decode errors in the middle of a file (the header
can be intact while the frames are damaged), exact VFR timing, and HDR10+
dynamic metadata. Decode validation is part of import and render checks (M05,
M24, spec 13.4).

## Stable error codes

All codes are `ErrorInfo.code` on a failed probe job. `retryable` is `false` unless marked.

| Code | When |
|---|---|
| `media.not_found` | The path does not exist |
| `media.not_a_file` | Directory, device, pipe, or other non-regular file |
| `media.permission_denied` | The file cannot be opened for reading |
| `media.unreadable` | Other OS error while opening |
| `media.empty_file` | Zero bytes |
| `media.damaged` | Recognized but broken or incomplete (e.g. `moov atom not found` after an interrupted recording), or a video extension whose contents are not readable media |
| `media.unsupported_format` | Not a container FFprobe recognizes |
| `media.unsupported_codec` | The video codec is unknown to this FFprobe build |
| `media.still_image` | An image, not a video |
| `media.no_video_stream` | Audio only, or only cover art (`details.audio_only`) |
| `media.invalid_duration` | No positive duration (possibly still being written) |
| `media.invalid_dimensions` | Width or height missing, 0, or above 16384 |
| `media.invalid_frame_rate` | Neither base nor average frame rate is usable |
| `media.probe_timeout` | FFprobe exceeded the timeout (**retryable**) |
| `media.probe_output_too_large` | FFprobe's metadata exceeded 4 MB |
| `media.probe_failed` | Any other FFprobe failure (`details.ffprobe_error` holds FFmpeg's error number) |
| `tool.ffprobe_missing` | FFprobe not found (**retryable**: install it and retry) |
| `tool.ffprobe_too_old` | Older than FFmpeg 6.0 (**retryable**) |
| `tool.ffprobe_unusable` | FFprobe does not run (**retryable**) |

Failures caused by FFprobe also carry a redacted `stderr_tail`.

## Fixtures

Tests generate tiny synthetic clips (about 1 second, 320×180) from FFmpeg's
`testsrc2` and `sine` sources. They contain no real footage and are never
committed (`media-fixtures/` and media extensions are git-ignored). To
generate them by hand:

```bash
pnpm media:fixtures media-fixtures     # writes services/media-worker/media-fixtures/
```

| Fixture | Expectation |
|---|---|
| `h264_aac.{mp4,mov,mkv,ts}` | H.264 + AAC stereo, exact `30000/1001` |
| `no_audio.mp4` | No audio streams |
| `vfr.mp4` | `variable_frame_rate: true`, exact average rate |
| `rotated.mp4` | `rotation: 270` (written with `-display_rotation 90`) |
| `hdr_pq.mp4` | BT.2020 / PQ tags retained, `hdr: true` |
| `hevc.mp4` | HEVC; only when FFmpeg has `libx265` (skipped otherwise, recorded in `manifest.json`) |
| `audio_only.m4a`, `still.png` | `media.no_video_stream`, `media.still_image` |
| `truncated.mp4`, `garbage.mp4` | `media.damaged` |
| `garbage.bin`, `empty.mp4` | `media.unsupported_format`, `media.empty_file` |

Mastering-display, content-light-level, Dolby Vision, legacy rotation, and
odd timestamps cannot be produced reliably by every FFmpeg build. They are
covered by recorded FFprobe JSON in `tests/media/test_normalize.py`.

Media tests skip when FFmpeg is missing locally. CI sets
`OWM_REQUIRE_FFMPEG=1`, which turns those skips into failures.
