# Banner and subtitle OCR (M17)

`region-banner-ocr` and `region-subtitle-ocr` 1.0.0 use local Tesseract to inspect
calibrated text regions. They share the M14 analyze job, M15 local overrides and
M16's derived-only sampling boundary. **Game compatibility is unvalidated**,
including GTA VI. All reported quality measurements use synthetic text.

## Inputs, engine and preprocessing

Each detector owns a fixed named ROI: `mission_banner` or `subtitle`. The runtime
validates the profile and upright picture compatibility, prepares/verifies the M08
SDR proxy, then crops only that region at 2 fps to 640×128 grayscale
(`gray-roi640x128-2fps-v1`). A proxy crop smaller than 80×16 is refused. No full
source frame or original filename reaches OCR. Calibrating a region changes its
input key. Frame reuse also checks sampler dimensions to isolate the 200×40 wanted
sampler from the text sampler even when coordinates are identical.

Tesseract 5+ is an optional system executable. Install it and the selected language
data explicitly; set `OWM_TESSERACT` to an absolute executable path if needed.
Otherwise use PATH or the standard Windows `Program Files/Tesseract-OCR` location.
The adapter discovers the installed data directory from `--list-langs`, checks the
language ID, bounds a regular `.traineddata` file at 128 MiB and hashes it.
It never downloads, extracts or installs a model. The selected model's metadata is
checked during OCR and its hash is verified again before computed events commit.

Preprocessing stretches the crop's grayscale contrast and inverts a dark
background to white. Banner `contrast` mode keeps grayscale; subtitle `threshold`
mode maps at the midpoint to black/white. Both add an 8-pixel white border.
A flat crop (range <20) is absent/unreadable and does not invoke OCR.
Only the resulting PGM enters a fresh owned scratch directory. A fixed argument
array invokes LSTM OCR (`--oem 1`, `--psm 6`, 150 dpi, TSV to stdout). The existing
runner enforces a 10-second call timeout, 256 KiB output cap, cancellation/kill/reap
and redacted stderr. Temporary files are removed on success, failure and cancel.

The TSV parser validates its exact columns, finite 0–100 scores, positive word
boxes, crop bounds, ≤512 rows, ≤32 lines and ≤500 total text characters. It groups
word boxes by line, removes the border and maps each line into global normalized
upright coordinates. Invalid output fails the unit; it cannot become a fallback
mission label. Events and shared fixtures validate line containment in both TS
and Python. No private model path is stored in event provenance.

## Locale packs and classification

Contracts 1.12 add optional `LocalePack.ocr_language` and `DetectorSettings.ocr`.
Use a licensed, versioned locale pack. `ocr_language` is an installed Tesseract
language ID such as `eng`, never a path/URL. Existing `locales` vocabulary maps
categories to phrases; a local pack can replace it without loading Python code.
English `en` 1.0.0 in `generic-text` is the initial synthetic pack.

| Vocabulary category | Event type |
|---|---|
| `failure` | `openworld.failure` |
| `arrest` | `openworld.arrest` |
| `mission-started` | `openworld.mission_started` |
| `mission-objective` | `openworld.mission_objective` |
| `mission-completed` | `openworld.mission_completed` |
| `mission-failed` | `openworld.mission_failed` |

Matching compares the **whole** NFKC/case-folded text with punctuation/spacing
normalized. Sequence similarity defaults to ≥0.9; the best category must exceed
the runner-up by ≥0.08. Phrases shorter than eight characters require exact
normalized equality. Long unrelated text and ambiguous categories stay unknown.
Known categories also require OCR confidence ≥0.75. There is no substring match
against an entire screen, story reasoning, translation or full-screen OCR.

A recognized unknown banner emits `openworld.ocr_text`, with its original OCR text
and confidence capped at 0.49. Text below the configured recognition threshold is
discarded. Subtitle output is `openworld.subtitle`, retaining recognized text and
an explicit visible `speaker:` prefix when present. Speaker identity is never
inferred from audio or appearance.

| Setting | Default | Bounds/meaning |
|---|---|---|
| `ocr.preprocess` | Banner `contrast`, subtitle `threshold` | Fixed preprocessing enum |
| `ocr.min_text_confidence` | 0.6 | 0–1, minimum recognized text quality |
| `ocr.match_threshold` | 0.9 | 0.8–1, whole-text vocabulary similarity |
| `ocr.max_missing_frames` | 1 | 0–20 consecutive missing/unreadable samples |
| `confirmation_frames` | 2 | Common profile setting, 1–600 supporting samples |
| `min_confidence` | Generic profile 0.3 | Common event filter; raising it can hide unknown OCR |

OCR confidence is the minimum word score per line and minimum line score for the
region. Known-event confidence is the minimum of OCR and match score over its
supporting samples; unknown-event confidence is capped at 0.49. These are
explainable heuristic scores, not calibrated probabilities. A high-quality OCR
reading is not itself evidence of mission meaning.

## Temporal intervals, evidence and privacy

A candidate requires confirmation before becoming active. Persistent text emits
one interval, finalized on confirmed replacement, sustained absence, a sample gap
>750 ms, or clip end. Brief misses bridge observations without counting as support.
A return to active text clears a competing candidate. Confirmed OCR spelling
variants that match the same vocabulary phrase retain one banner interval;
distinct configured phrases remain distinguishable. Close subtitle variants use
≥0.94 normalized similarity to avoid tiny OCR fluctuations, which can also merge
very similar real subtitle changes and is a known limitation.

Intervals use the first supporting sample through the last supported sample plus
500 ms, clipped to source duration. `confirmed_at_ms`, `last_seen_ms` and
`closed_by` expose appearance/confirmation/disappearance behavior. Source ranges
and line evidence stay in source coordinates while the runtime maps the event
interval into M13 unique session time. State resets per asset; cross-clip text
continuity is not inferred. Sampling is not exact source-frame timing.

OCR evidence contains text, normalized parent region, source `frame_ms`, confidence
and line text/boxes/scores. Temporal evidence records support count and sample
coverage. Mission categories set `spoiler_risk: true` and `spoiler_reason:
mission_text`; this flags visible text for review without classifying story
meaning. No image bytes, source filenames or private paths are embedded.
Recognized text itself can be private/spoiler-sensitive: it stays local and is not
logged or uploaded automatically. Inspect it before explicitly sharing events.

The source records detector/profile versions plus engine, language-data SHA-256,
OCR language, locale-pack version, preprocessing and sampler versions. These join
the complete resolved profile/settings/calibration and session layout in cache
identity. Changing data, locale or input recomputes the producer. Successful old
snapshots remain when a replacement fails, is skipped or is cancelled. Missing
OCR skips only OCR units; other producers remain usable. CLI analysis exits nonzero
on skipped/failed units rather than disguising unavailability as an empty success.

## Commands and development dependencies

From the repository root:

```bash
uv run --directory services/media-worker owm text doctor
uv run --directory services/media-worker owm analyze ses_<ULID> --library /absolute/library --profile generic-text
uv run --directory services/media-worker owm text benchmark --samples 60 --repeats 3
OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check
pnpm build
```

`doctor --language <id>` checks an installed language and prints media-free versions
and hash metadata. `benchmark` is a development diagnostic needing the development
OpenCV/NumPy dependencies (`uv sync --all-packages --locked`). Runtime OCR itself
adds no Python dependency on those libraries. Source calibration uses the existing
UI; M15's one-frame SDK preview still supports the bright-region example only.
M19 owns the OCR evidence/review UI.

Tesseract and official language data are Apache-2.0. OpenCV is Apache-2.0 with
retained BSD terms for its Hershey renderer; NumPy uses BSD terms. Synthetic
phrases/recipes are original, profiles Apache-2.0 and fixture code AGPL. No font,
engine, language model, screenshot or text corpus is copied into the repository.
M29/M34 must inventory and verify packaged runtime/data licenses and architectures;
custom installed data requires its own provenance review. See [ADR-0005](../architecture/adr/0005-local-ocr.md).

## Exact synthetic validation

[Manifest text-v1](../../fixtures/manifests/text-v1.json) versions the recipes and
case table. OpenCV draws explicit Hershey Simplex/Duplex strokes into scratch
images. Stroke width scales with source dimensions; the unrelated canvas uses
brightness-scaled 64 to stay away from M08's black cutoff, while the text ROI
keeps dark background 20. No official font or game text is used.

| Case | Validated result |
|---|---|
| Six banner categories × base/small/dim-contrast/outline/duplex/multiline | 36 correct categories, confidence ≥0.75 with the real local OCR engine |
| 720p CRF18; 1080p CRF30 at 70% brightness with outline; 4K CRF32 | Exactly one mission-completed, one unknown OCR, one arrest and two subtitle intervals |
| Two-line `MORGAN:` subtitle, then changed text | One interval per text: 1000–3000 and 3000–5000 ms; two line boxes and visible speaker |
| Banner relocated outside the configured ROI | No banner event before calibration, three after saving the ROI |
| Unknown text, ambiguous vocabulary, short fuzzy matches, longer unrelated phrase | Unknown/low-confidence OCR, no fabricated mission event |
| Repeated text, flicker, misses, absence/reappearance, OCR spelling variation | Confirmed intervals with bounded temporal deduplication |
| Malformed/oversized TSV, invalid boxes, missing engine/model, timeout/cancel | Bounded rejection or explicit skip; scratch cleanup and successful producer preservation |
| Model change/cache, authenticated job/API, CLI and source identity | Provenance invalidation, real events through the existing API, unchanged source SHA-256/mtime |

The benchmark performs uncached banner **and** subtitle OCR for each sampled
moment, plus preprocessing and vocabulary matching. It excludes proxy/decode/I/O
and is a local reference-machine processing measurement, not minimum Windows CPU
or gameplay accuracy qualification. Exact measurements are recorded in the M17
handoff. A separate held-out gameplay precision/recall dataset is not claimed.

## Known limits

The default English pack and synthetic renderer do not establish support for any
game, HUD, font family or locale. Animation, very small/low-contrast text, ambiguous
characters, long wrapped dialogue, mixed scripts and background interference can
produce unknown text or missed/merged intervals. Rectangular calibration does not
automatically establish detector accuracy. A 2 fps sampler can miss brief text;
OCR sample times and browser previews are not exact caption word timings.

The existing 64 MiB raw-frame cap allows about 6.8 minutes per asset with this
sampler; the decode timeout remains 600 seconds. OCR has a per-call 10-second
limit and retains at most eight exact crop readings within a unit. There is no
streaming long-asset analysis, OCR download/model manager, full-screen reading,
translation, story interpretation or native OCR preview UI in M17. Lawful local
capture evaluation and packaging/platform qualification remain separate work.
