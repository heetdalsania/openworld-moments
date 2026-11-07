# Analytic wanted-state detector (M16)

`wanted-indicators` 1.0.0 recognizes a calibrated regular row of bright mathematical
stars or discs. It produces `openworld.wanted_level_changed` observations through
the existing M14 analyze job. **Game compatibility is unvalidated**, including
GTA VI. Synthetic results do not establish gameplay precision/recall.

## Geometry and confidence

The M08 SDR playback proxy is cropped to the saved normalized `wanted_indicator`
ROI, then sampled as 200×40 grayscale at 2 fps (`gray-roi200x40-2fps-v1`). The crop
must retain at least 12 proxy pixels per indicator and 12 pixels of height. Do not
include unrelated HUD elements. The whole row must occupy uniform slots, with
radius 40% of the smaller slot dimension. All inactive slots need visible outlines.
The proxy check prevents a tiny 4K source ROI from passing after proxy downscaling.

Each slot uses analytic silhouette, rim, core and background masks. Five-point
stars alternate radii 1 and 0.45; discs use the unit circle. The estimator checks:

1. Median rim intensity ≥50 and rim/background contrast ≥30 (0–255 grayscale).
2. Normalized core fill ≥0.75 for active or ≤0.25 for inactive; intermediate is unknown.
3. Binary silhouette Dice agreement ≥0.78 against the filled shape or outline.
4. Filled slots form a contiguous prefix; gaps are unknown.

The slot score is `0.60 × Dice + 0.25 × fill certainty + 0.15 × contrast certainty`,
where fill certainty is `min(1, 2 × abs(fill - 0.5))` and contrast certainty is
`min(1, contrast / 60)`. Frame confidence is the minimum slot score. The transition
uses the minimum supporting-frame score with a 5% × misses/support penalty.
These are explainable heuristic scores, **not calibrated probabilities**. Unknown
frames carry a reason and never become a zero observation. All visible inactive
outlines are necessary for zero; HUD disappearance cannot safely mean cleared.

## Confirmation and time

The generic profile defaults to five stars; `wanted` settings are optional:

| Setting | Default | Bounds |
|---|---|---|
| `max_level` | 5 | Integer 1–10 |
| `shape` | `star` | `star` or `disc` |
| `max_missing_frames` | 1 | Integer 0–20 consecutive unknowns |
| `debounce_ms` | 1500 | Integer 0–30000 |
| `confirmation_frames` (common detector setting) | 3 | Integer 1–600 |
| `min_confidence` (common detector setting) | 0.8 | 0–1 |

The first confirmed level establishes a baseline without emitting an invented
transition. A change requires the configured number of supporting samples.
Allowed unknowns bridge those samples, never count as support, and reduce the
score. A return to the stable value or a different candidate clears confirmation.
Cooldown postpones a change until it is still supported; old misses age out with
the bounded confirmation window. Sustained unknowns or sample gaps over 750 ms
lose the baseline and require reacquisition without guessing the unseen change.
Each source asset starts with a fresh state; cross-clip transitions are not inferred.

With three uninterrupted samples at 2 fps, confirmation follows first observation
by 1000 ms. Intervals run from the oldest retained supporting sample through the
confirmation sample plus 500 ms, clipped to source duration. This is sampled
analysis, not exact source-frame timing. Existing M14 mapping projects unique
source intervals into session time and preserves source coordinates in attributes.

## Events and local crop references

Each event includes `from`, `to`, `max_level`, `direction`, `confirmed_at_ms` and
`compatibility: unvalidated`. Evidence consists of a `region_template` score with
normalized region and source `frame_ms`, plus `temporal_consistency` with supporting
frame count and support/(support+misses). The event asset ID, region, timestamp
and input provenance locate a reconstructable crop locally. Image bytes and local
filesystem paths are absent from shareable events. A copied event requires the
matching local library/proxy to reconstruct its crop.

The runtime supplies detector/profile/SDK/sampler/FFmpeg versions and input keys.
Calibration, settings, profile lineage, tool or session layout changes invalidate
cache entries. Failures and cancellation preserve previously successful events.
No database migration or new API route is introduced.

## Local replay and benchmark

From the repository root, select an already imported, lawfully obtained asset:

```bash
uv run --directory services/media-worker owm analyze ses_<ULID> --library /absolute/library --profile generic-wanted
uv run --directory services/media-worker owm wanted replay ast_<ULID> --library /absolute/library --output /absolute/new-report-directory
uv run --directory services/media-worker owm wanted benchmark --seconds 3600 --repeats 5
```

Use `--profiles /absolute/catalog` and `--profile <id>` for a local catalog/profile.
The replay applies saved calibration, validates and hashes the derived proxy,
and uses the production estimator/filter. It writes `trace.jsonl` (per-sample
estimate/reason/scores/state/candidate/transition) and `report.json` (input identity,
versions, timing, complete marker and observations). It does not save events into
the library. Proxy preparation may populate replaceable M08 derived artifacts.

`--crops` explicitly adds separate 200×40 PGM files at transition confirmations,
referenced by relative `crop_ref` in trace rows. These are local media, distinct
from the media-free event evidence. Existing output directories are refused.
Cancellation before publication creates no report directory. `report.json` is
written last: a directory without it is an incomplete filesystem write, not a
successful replay. Traces and crops are not committed or uploaded automatically.

Settings → Calibrate detector profile regions saves coordinates. M15's single-frame
SDK preview supports the synthetic bright-region example only; temporal wanted
inspection uses this CLI. No new UI is introduced in M16.

## Exact synthetic validation

[Manifest wanted-v1](../../fixtures/manifests/wanted-v1.json) records all recipes.
The original scanline polygon fixture renderer is separate from the estimator's
point-in-polygon masks. No official art, models, fonts, screenshots or game footage
are used. Renderer/media fixture pixels are AGPL-3.0-or-later; the reference JSON
profile is Apache-2.0. Generated media stays in scratch directories.

| Case | Expected and validated result |
|---|---|
| Stars/discs, maximum 1/3/5/10, every level, brightness 0.55/0.8/1 (138 cases) | Correct known level; score ≥0.8 |
| 0→2→5→0, each held for six 500 ms samples | One event per change after three supporting samples |
| Isolated changed samples and one unknown during confirmation | No flicker; unknown never counted as support |
| Sustained missing/low-confidence input and timestamp gap | Baseline discarded; no guessed clear/change |
| Debounce flips and early misses during long cooldown | Current confirmed change only; recovery succeeds |
| Missing HUD, rectangles, non-prefix fills, ambiguous fill, wrong shape | Unknown, no false state |
| Real H.264: 720p CRF18; 1080p CRF32 at 70% brightness; 4K CRF38 | Exactly 0→2→5→0 after real import/proxy/decode |
| 75% HUD scale at relocated ROI | Uncalibrated empty result; saved calibration yields three changes |
| Compressed moving FFmpeg `testsrc2` | All unknown, no transitions |
| Invalid ROI/sample, decode failure/cancel, mixed whole-frame/ROI consumers | Bounded refusal/isolation; completed units and cache preserved |
| Replay/API/CLI and source preservation | Correct events, local crops, media-free metadata, stable source SHA-256/mtime |

The replay trace was inspected on the encoded 75%-scale fixture: baseline zero;
changes confirmed at 4000, 7000 and 10000 ms, with first supports at 3000, 6000
and 9000 ms; 24 samples and exactly three crop references. This is synthetic media,
not evidence of GTA HUD compatibility.

On local Apple M4 / macOS arm64, Python 3.12.14, five runs of one hour (7,200 ROI
frames) produced 900 events each. Median processing time was **5.599 s** (range
5.594–6.919 s), approximately **642.9× real time**, exceeding the 2× processing
budget on this reference machine. This is the estimator and temporal loop only;
it excludes proxy generation, decoding and I/O. It is not a minimum Windows CPU
or end-to-end throughput qualification. M16 has no prior wanted-detector baseline.

## Limitations and lawful local evaluation

This estimator expects the documented geometry and high-contrast regular row.
Color-only state, animation, text, irregular spacing, outlines that vanish at zero,
very small HUDs, motion/background interference and game-specific designs are
unsupported. Similar analytic rows could still match; the negative fixture set
is not an exhaustive false-positive study. A 2 fps sample can miss brief states.
The existing 64 MiB decoded-output cap and 600-second tool timeout apply; the ROI
sampler cap permits about 70 minutes per asset, including Python memory overhead
outside that raw-byte cap.

No lawful gameplay capture was supplied/selected for this milestone, so the
conditional local gameplay smoke test was not performed. Do not search user
libraries for footage. To evaluate locally: explicitly choose a legitimate
capture, import it, calibrate the complete row, replay with optional local crops,
and compare every transition/unknown against manual annotations. Record profile,
HUD scale, resolution, locale, tool versions and false positives/negatives. Keep
media outside the repository and never commit official or leaked material.
Compatibility stays unvalidated until measured legitimate evaluation supports a
specific claim. M19 owns review, corrections and reproducible gameplay metrics.
