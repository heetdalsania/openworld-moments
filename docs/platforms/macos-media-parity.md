# macOS media parity

The pinned FFmpeg build enables Apple's system VideoToolbox framework and keeps
`libx264` for CPU exports and proxies. It still targets macOS 14 on Apple Silicon
and Intel. Network protocols and dependency autodetection are disabled in the build.
The Mach-O audit allows Apple's system frameworks and verifies that every shipped
binary is native to the target architecture. See [macOS packaging](./macos-packaging.md).

## Playback and export

- The existing proxy policy is shared across platforms. Supported SDR H.264 clips
  can play directly. HEVC and HDR clips get validated CPU SDR proxies. Rotation
  is honored and supported variable frame rates are preserved in proxies.
- An optional Apple VideoToolbox export becomes available after FFmpeg encodes
  a short H.264 High `yuv420p` fixture at that preset's exact dimensions, fixed
  rate and rate control. The probe disables FFmpeg's software encoder fallback.
  Eligible presets are up to 1920 × 1080 (or portrait equivalent) at up to 60 fps.
  Source-rate presets remain available through the CPU encoder.
- Apple Silicon uses VideoToolbox's constant-quality control. FFmpeg only supports
  that control on Apple Silicon. On Intel, CRF presets use a bitrate approximation
  based on 12 Mb/s at CRF 20 and 1080p30, scaled by pixel rate and by a factor of
  two per six CRF points. Values are bounded to 128 kb/s–50 Mb/s. The export
  panel explains the quality difference. Explicit bitrate presets use the
  requested bitrate on either architecture.
- When a VideoToolbox render fails at runtime or fails output validation, the
  job retains the reason and offers CPU retry with the same preset after any
  applicable review. Cancellation clears staging. Neither path alters sources.
- HDR tone mapping uses the existing Hable LUT and the source's declared full
  or limited range. Render engine 1.3.0 explicitly writes BT.709 SDR color tags to
  exports containing tone-mapped material and requires them during FFprobe
  validation. The editor's existing text and caption omission behavior applies.

## Test the packaged tools

Use synthetic fixtures generated from FFmpeg test patterns and tones. For HEVC
generation use an independent FFmpeg with `libx265` installed. It is a fixture
generator only. Every import, proxy, render, and verification below uses the
packaged FFmpeg/FFprobe under `Contents/Resources/runtime/tools`.

```bash
export OWM_FFMPEG="/absolute/path/to/runtime/tools/ffmpeg"
export OWM_FFPROBE="/absolute/path/to/runtime/tools/ffprobe"
export OWM_FIXTURE_FFMPEG="/absolute/path/to/fixture-generator/ffmpeg"
export OWM_MACOS_MEDIA_REPORT="/absolute/path/to/media-parity-report.json"
OWM_REQUIRE_FFMPEG=1 uv run --locked --directory services/media-worker pytest \
  tests/render tests/media/test_macos_media.py tests/media/test_derived.py \
  tests/media/test_render.py tests/media/test_vertical_render.py
```

The version 1 report records OS and architecture, tool versions, preset-level
encode probes, and VideoToolbox H.264 and HEVC decode results. The decoder probe
requires a decoded VideoToolbox surface. FFmpeg can permit an internal software
decode for HEVC, so the result establishes that this decode path works.
Proxy and render times include validation overhead. The report also records disk
usage for each export, the process-wide peak child RSS, and OS thermal warnings.
The architecture-specific CI build uploads the report alongside the unsigned app.
CPU results remain mandatory when a runner lacks accessible video hardware.

For native playback evidence, open the packaged app on each Mac, import the seven
matrix fixtures into a disposable library, and check the original or generated
proxy in the app player. Seek near the start, middle, and end; check orientation,
sound, and HDR brightness. Open each rendered orientation and record any
unexpected black frames, timing issues, or color shifts. Record the Mac model,
macOS version, artifact hash and whether VideoToolbox appeared for the three
fixed-rate presets in the export panel. Use a longer self-generated clip for
sustained timing and thermal checks. Attach a path-free report to the M36 handoff.
