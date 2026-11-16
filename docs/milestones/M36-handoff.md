## Milestone handoff

- Milestone: M36 — macOS media and render parity
- Outcome: Implementation and Apple Silicon synthetic validation are in place.
  Full completion requires the Intel hardware results and packaged-player walkthrough.
- Files and modules changed: macOS FFmpeg build and native CI matrix, worker
  encoder probe and render validation, Export panel and host allowlist, synthetic
  media tests, README and milestone ledger.
- Public contracts or migrations: `GET /v1/render/encoders` now accepts the optional
  catalog `preset_id` and returns the existing `render-encoders` shape. Render engine
  1.3.0 covers HDR color tagging and the updated VideoToolbox settings. No shared
  schema, generated contract, or database migration changes.
- Commands run: `git pull --ff-only origin main`, `bash scripts/macos/build-media.sh arm64`,
  the [packaged-tool matrix](../platforms/macos-media-parity.md#test-the-packaged-tools),
  and repository quality checks. M25 (#31), M33 (#51), and M34 (#52) are merged into
  base `c599986`. M35 was already in progress in
  [draft PR #53](https://github.com/heetdalsania/openworld-moments/pull/53).
- Test and validation results:
  - Apple M4, macOS 26.6.2, pinned FFmpeg/FFprobe 9.0.2 linked to Apple's system
    frameworks. VideoToolbox H.264 and HEVC decode probes returned frames and the
    three fixed-rate H.264 encode probes passed with software encoding disabled.
  - 80 focused tests passed against the rebuilt native FFmpeg/FFprobe. Seven
    fixtures covered 14 CPU renders and four VideoToolbox renders across both
    orientations. PQ and 10-bit HEVC HLG exports carried BT.709 limited-range
    tags. The M25 crop goldens retain the two-pixel tolerance.
  - A separate picture-and-tone fixture checks sync after trimming in both
    orientations. A fault injected after partial output exercises explicit CPU
    retry and staging cleanup. On available hardware, cancellation also exercises
    the VideoToolbox path.
  - A native Apple Silicon WKWebView smoke loaded and sought within the H.264,
    silent, VFR, rotated, HEVC proxy and PQ proxy samples from local files.
    The rotated sample reported 180 × 320. Native playback through the packaged
    app's media protocol still needs the walkthrough.
  - A native Apple Silicon bundle passed the Mach-O verification and
    `scripts/macos/runtime-smoke.py`. The bundled worker imported a synthetic
    clip, rendered it on CPU, and refused missing and damaged media tools.
  - The repository `pnpm check` passed with FFmpeg required. It recorded 1,238
    worker tests passing and 42 skips for existing OCR/platform prerequisites.
    Python contracts (366), TypeScript contracts (399), desktop (286), and the
    Rust suites passed. Formatting, lint, types, REUSE, and contract drift passed.
  - 20-second 1080p30 H.264 synthetic input, including output validation.

    | Output | CPU time | VideoToolbox time | CPU output | VideoToolbox output |
    |---|---:|---:|---:|---:|
    | 1920 × 1080 | 6.67 s | 2.69 s | 20.86 MB | 20.60 MB |
    | 1080 × 1920 | 3.76 s | 2.60 s | 4.13 MB | 5.44 MB |

    The maximum child RSS for that run was 805 MB. macOS reported no thermal warning.
- Decisions made: Fixed-rate VideoToolbox availability uses the exact preset and
  requires hardware. Intel uses a disclosed bitrate mapping because FFmpeg's
  VideoToolbox constant-quality mode is Apple Silicon only. Source-rate presets
  use CPU encoding. Proxies and analysis continue to use software decoding to
  preserve their reference behavior.
- Known limitations: Native Intel test, full packaged-player walkthrough, and
  extended thermal observations remain pending. Synthetic clips
  establish basic timing, color, and layout behavior. The short sample timings
  include process startup and output validation. The M24 explicit text/caption
  omission path still applies.
- Follow-up milestones affected: M37 consumes the audited media binaries for
  signing and notarization after M35 and M36. M39 needs release-hardware playback
  and encoder evidence for each supported architecture.
- Screenshots, reports, or artifacts: Both native CI jobs are configured to archive
  `media-parity-<arch>.json` with the unsigned bundle. The report includes encoder
  availability, CPU results, wall-clock time, output bytes, child peak RSS and
  available thermal warnings. All test media is generated from FFmpeg test
  patterns and tones. Local reports are in ignored `output/packaging/macos/`.
  No generated media, user library, or build outputs are
  included in the change.
