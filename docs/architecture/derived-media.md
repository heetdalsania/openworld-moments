# Derived media: proxies, thumbnails, and waveforms

M08 creates the media the app plays and draws from, without touching the
original file:

- a **proxy** (when the source would not play smoothly in the app),
- a **filmstrip** of thumbnails,
- a **waveform** of the audio.

All three are replaceable files in the library. The database records which file
is current and exactly how it was made.

Code:

- **Worker:** `services/media-worker/openworld_moments/derived/`, split into
  `policy.py` (when a proxy is needed), `tonemap.py` (HDR to SDR), `recipes.py`
  (presets, FFmpeg arguments, cache keys), `waveform.py`, `layout.py` (paths and
  cleanup), and `service.py` (the job).
- **Contract:** `derived-media.schema.json` (contracts 1.6).
- **Migration:** 0007 (`derived_artifacts`).
- **Job:** `proxy` (state `proxying`).

## When an asset gets a proxy

The app plays video in the system web view (WebView2 on Windows, WKWebView on
macOS, WebKitGTK on Linux). The only video all of them play smoothly is 8-bit
4:2:0 H.264 in MP4 or MOV, with AAC or MP3 audio, up to 1080p and 60 fps.

Any other source gets a proxy, and each rule that applies is recorded as a
reason in `proxy_decision` (policy version 1):

| Reason | When |
|---|---|
| `container` | Not MP4 or MOV (for example MKV, WebM, MPEG-TS) |
| `codec` | Video is not H.264 (for example HEVC, AV1, VP9) |
| `pixel_format` | Not 8-bit 4:2:0 (for example 10-bit or 4:2:2) |
| `hdr` | PQ or HLG transfer, or flagged HDR |
| `resolution` | More pixels than 1920×1080 (after rotation) |
| `frame_rate` | Faster than 60 fps |
| `audio_codec` | First audio stream is not AAC or MP3 |
| `requested` | `proxy_policy: "always"`, or the asset already has a proxy |

A typical 1080p60 H.264 Xbox clip needs no proxy. A 4K HDR HEVC capture gets
one. Once an asset has a proxy, it is kept current, and its thumbnails come from
it.

## Proxy preset (`proxy-h264-sdr` v1)

| Setting | Value |
|---|---|
| Video | libx264, `-preset veryfast`, CRF 23, High profile, yuv420p |
| Size | Longer edge at most 1280 px, never upscaled, even dimensions. Rotation is applied, so the proxy is upright |
| Timing | Source timing kept (`-fps_mode passthrough`, so VFR stays VFR). Above 60 fps, constant 60 fps |
| Keyframes | One per second (`-force_key_frames expr:gte(t,n_forced*1)`), for fast seeking |
| Audio | First audio stream as AAC stereo, 128 kb/s, 48 kHz. None when the source has none |
| Container | MP4 with `+faststart`, no metadata or chapters copied |
| Determinism | `-threads 4` (fixed), `-fflags +bitexact`, `-flags +bitexact` |

The same toolchain and preset always produce byte-identical proxies (tested).

### HDR tone mapping

HDR sources get an SDR BT.709 proxy. The original keeps its HDR signal.

**How:** the worker computes a 3D LUT in Python, and FFmpeg applies it with its
built-in `lut3d` filter. This needs no optional FFmpeg library (`zscale`/zimg is
missing from many builds, Homebrew's included). The exact curve is part of the
recipe.

The filter graph:

```text
scale=W:H:in_color_matrix=bt2020:in_range=tv, format=gbrp16le,
lut3d=file=tonemap.cube:interp=tetrahedral,
scale=out_color_matrix=bt709:out_range=tv, format=yuv420p,
setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv
```

For each LUT entry (BT.2020 RGB, PQ- or HLG-encoded):

1. **Decode to nits.**
   - **PQ:** the SMPTE ST 2084 EOTF.
   - **HLG:** the BT.2100 inverse OETF plus the OOTF for a 1000-nit display.
2. **Tone-map with the Hable curve** on the largest channel, which preserves hue.
   The 1000-nit source peak maps to SDR white, with 100-nit reference white.
3. **Convert to BT.709 primaries** in linear light (BT.2087 matrix) and clip.
4. **Encode** with the BT.709 OETF.

Every tone-mapped proxy records these settings as `tone_map`, with the LUT's
SHA-256: transfer, method `lut3d`, curve `hable`, peak and reference white,
output primaries and transfer, LUT size 33, tetrahedral interpolation, and
version 1.

## Filmstrip (`filmstrip-jpeg` v1)

- **Count:** one thumbnail about every 5 seconds, between 1 and 120. Each one
  shows the middle of its slice of the asset (`times_ms`).
- **Size:** longer edge 160 px.
- **Format:** JPEG (`mjpeg`, `-q:v 4`).
- **Source:** the proxy when the asset has one (fast, already SDR and upright),
  otherwise the original.
- **How:** one FFmpeg run with `fps=N/D:round=near:eof_action=pass`. Files are
  `0001.jpg`, `0002.jpg`, and so on.

## Waveform (`waveform-peak-rms` v1)

- **Input:** the first audio stream, mixed to mono and decoded to 16-bit PCM at
  8 kHz. Samples are streamed and never held in memory.
- **Buckets:** 50 per second, each storing peak and RMS amplitude as one byte
  (0 to 255).
- **File:** `owm-waveform` v1, a 16-byte header (`OWMW`, version, buckets per
  second, sample rate, bucket count) followed by the byte pairs. About 360 KB
  per hour.
- **No audio:** an asset without audio has no waveform (`not_applicable`).

## Cache keys and versions

An artifact's **recipe** contains:

- the preset with its version,
- the policy version (proxy only),
- the FFmpeg build (release and library versions, not its path),
- the parameters chosen for this asset: size, frame-rate cap, audio, tone map,
  and the filmstrip source.

The **cache key** is the SHA-256 of the asset's SHA-256, the artifact kind, and
the recipe as canonical JSON.

- **Cache hit:** a `ready` artifact with the current key whose file still exists.
  Nothing runs.
- **Invalidation:** bumping a preset version, `POLICY_VERSION`, or
  `TONEMAP_VERSION`, or using a different FFmpeg build, changes the key. Stored
  artifacts then show as `stale` and are regenerated on the next `proxy` job.
  The filmstrip's key includes the proxy's key, so a new proxy also refreshes
  the thumbnails.

Bump the relevant version whenever its output would change.

## Artifact layout

```text
library/derived/<asset-id>/proxy-<key16>.mp4
library/derived/<asset-id>/filmstrip-<key16>/0001.jpg ...
library/derived/<asset-id>/waveform-<key16>.bin
library/staging/derived/<job-id>/        (work in progress only)
```

- **Names carry 16 hex digits of the cache key.** A regenerated artifact gets a
  new name, so a player never reads a file while it is being replaced. (The
  spec's layout uses `proxy.mp4`; key-suffixed names are what make replacement
  atomic.)
- **Building and promotion:** each artifact is built in the job's staging folder,
  validated, then moved into place with one rename on the same volume. Its row
  is written in one transaction, and the previous file is deleted only after
  that.
- **A crash or cancel leaves no partial artifact in `derived/`.** Leftover
  staging is removed when the job ends and when the worker starts.
- **Missing files:** a deleted derived file shows as `missing` and is rebuilt by
  the next job. Canonical state (the asset and its probe) is enough to recreate
  it.

## Validation (spec 13.4)

Before a proxy is promoted:

- **FFprobe** must report:
  - H.264, yuv420p, the planned size, and no rotation;
  - AAC stereo exactly when the source has audio;
  - a BT.709 transfer when tone-mapped;
  - a duration within max(250 ms, three frames) of the source.
- **Sampled decodes:** one frame at 10%, 50%, and 90% from the proxy and from the
  source, each decoded to 32×18 grayscale, must agree:
  - **SDR:** mean brightness within 40 levels;
  - **any source:** no black frame where the source has picture;
  - **SDR:** no white frame where the source is not white.
- **Filmstrip:** must have exactly the planned number of JPEG files.
- **Waveform:** must parse, with one bucket per 160 samples.

A failure is `derived.validation_failed`, and nothing is promoted.

## Job and API

`proxy` job params (`DerivedMediaRequest`):

```json
{
  "asset_id": "ast_…",
  "artifacts": ["proxy", "filmstrip", "waveform"],
  "proxy_policy": "auto",
  "force": false
}
```

- **What it does:** each artifact is committed on its own and current ones are
  cache hits. The job is safe to requeue after a crash.
- **Progress:** the proxy reports through FFmpeg's `-progress pipe:1`; the
  waveform by samples decoded.
- **Cancelling:** kills FFmpeg and removes the staging folder.
- **Result:** `DerivedMediaResult`, an outcome per artifact: `generated`,
  `cached`, `not_needed`, or `not_applicable`.

| Method | Path | Result |
|---|---|---|
| GET | `/v1/assets/{id}/derived` | `AssetDerivedMedia`: the proxy decision, and per artifact its status (`ready`, `stale`, `missing`, `failed`, `not_generated`, `not_needed`, `not_applicable`), path, digest, recipe, and info |
| POST | `/v1/assets/{id}/derived` | Starts a `proxy` job. Body: optional `artifacts`, `proxy_policy`, `force`, `idempotency_key` |
| POST | `/v1/derived/cleanup` | `DerivedCleanupResult`: removes files in `derived/` that no row points at |

## Cleanup

`POST /v1/derived/cleanup` removes, inside `library/derived/` only:

- folders of deleted assets,
- old artifact versions,
- leftovers of crashed promotions.

Its safety rules:

- **Paths read from the database are checked** to be exactly
  `derived/<asset-id>/<artifact-name>`.
- **Links are never followed.** A symlink or junction inside `derived/` is
  removed as a link, never its target. A `derived/` that is itself a link is left
  alone.
- **Never alongside a promotion:** a lock shared with the job keeps cleanup from
  running while an artifact is being promoted.

## Minimum FFmpeg capabilities

FFmpeg 6.0 or newer (as for probing), with:

- **encoders:** `libx264`, `aac`, `mjpeg`, `pcm_s16le`;
- **filters:** `scale`, `format`, `setparams`, `lut3d`, `fps`;
- **muxers:** `mp4`, `image2`, `s16le`.

`doctor` and `/v1/capabilities` report `derived.ready` and anything missing. A
job on an FFmpeg build without them fails with `derived.ffmpeg_incapable`
(retryable once FFmpeg is replaced). `zscale` is not required. Hardware encoders
are not used for proxies yet.

## Error codes

| Code | When | Retryable |
|---|---|---|
| `asset.not_found` | Unknown asset | No |
| `derived.source_unavailable` | The original cannot be read (moved, deleted, offline, replaced) | Yes |
| `tool.ffmpeg_missing`, `tool.ffmpeg_unusable`, `tool.ffprobe_*` | Tools missing or broken | Yes |
| `derived.ffmpeg_incapable` | Required encoder or filter missing | Yes |
| `derived.disk_full` | Not enough free space (checked before work), or the disk filled up while writing | Yes |
| `derived.write_failed` | Another write error | Yes |
| `derived.timeout` | FFmpeg ran past its time limit | Yes |
| `derived.ffmpeg_failed` | FFmpeg could not process the file (stderr tail redacted of paths) | No |
| `derived.validation_failed` | The new artifact failed its checks | No |
| `derived.proxy_required` | Thumbnails need a current proxy that is not available | Yes |

A failure is recorded on the artifact (`last_error`). If an older artifact
exists, it stays current.
