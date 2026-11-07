# Local detector evaluation (M19)

Use local annotations and frozen observations to report quality, not a supported
badge. The harness never uploads media. Its public manifest references each clip
by SHA-256; a separate **private** map supplies explicitly selected local files.

## Reproduce the committed sample

```bash
uv run --locked --directory services/media-worker owm eval run \
  ../../fixtures/manifests/evaluation-holdout-v1.json \
  --observations ../../docs/evaluation/sample/observations.json \
  --output /absolute/new-report-directory
```

[Sample Markdown](./sample/report.md), [JSON](./sample/report.json), frozen
[observations](./sample/observations.json) and the [manifest](../../fixtures/manifests/evaluation-holdout-v1.json)
reproduce identical Markdown and the same JSON document (the committed JSON is
indented by the repository formatter). Two generated reports from the same frozen
inputs are byte-identical. JSON keys, input ordering for matching and compatibility
rows are deterministic. Reports contain no wall clock or generated timestamp.

## Capture new local observations

```bash
uv run --locked --directory services/media-worker owm eval holdout --output /absolute/new-holdout
uv run --locked --directory services/media-worker owm eval capture /absolute/new-holdout/manifest.json \
  --media-map /absolute/new-holdout/media-map.private.json --output /absolute/new-observations.json
uv run --locked --directory services/media-worker owm eval run /absolute/new-holdout/manifest.json \
  --observations /absolute/new-observations.json --output /absolute/new-report
```

`holdout` generates three independent temporal recipes for the **unchanged M14
synthetic bright-region example**: 19 seconds total, three sustained annotated
intervals, one short flash and one sub-confirmation flash in a negative clip.
Background 64 avoids the proxy's black-frame cutoff. H.264 CRF18/24/30 tests light
and heavier compression. These recipes were not used to tune the detector and are
separate from its original three-second tuning fixture. No game, text, font,
model or official asset is used or committed. Generated media stays outside Git.

A public annotation manifest (`evaluation`, schema 1.14) declares:

- dataset ID, `split: holdout` and provenance (`synthetic`, `user-owned` or
  `licensed`, declared by the annotator);
- profile ID/version, inclusive boundary tolerance in milliseconds;
- clips with SHA-256, exact duration/upright dimensions, locale, HUD scale,
  compression group and `{type,start_ms,end_ms}` annotations;
- at most 100 clips and 500 annotations per clip. Negative clips use `[]`.

Create annotations independently before inspecting predictions. Every prediction
clip also has a 500-event limit. Public schemas reject paths, arbitrary extra
fields and text transcripts. This is declaration and reproducibility, not a
license checker or protection against fabricated input metrics.

The private map is a JSON object of `{ "<sha256>": "/absolute/local/clip.mp4" }`.
Do not share it. Capture verifies source SHA-256 before/after, size/mtime, exact
duration and upright resolution. It uses a scratch library, reference imports,
checked M08 proxies and existing trusted detector jobs. Original media is never
changed. Missing files, wrong hashes/metadata, unavailable/skipped/failed
producers or excess events fail the capture instead of evaluating partial output.
`--profiles` explicitly chooses another local catalog. No user library is scanned.

## Metrics and matching

`owm-eval-1` matches within each clip, requiring identical event type **and both**
absolute start and end errors `<= tolerance_ms`. Each annotation/prediction
participates at most once. A deterministic augmenting-path bipartite matcher
maximizes true-positive count, unlike a greedy nearest-neighbor pass. Predictions
are ordered by type/start/end/original index; edges prefer smaller summed boundary
error, then annotation index. This is deterministic maximum cardinality, **not a
global minimum timing-error assignment**.

- TP = matched pairs, FP = unmatched predictions, FN = unmatched annotations.
- Precision = TP/(TP+FP); recall = TP/(TP+FN).
- F1 = 2TP/(2TP+FP+FN).
- Undefined ratios are JSON `null` / “Not defined”; empty negatives do not invent
  a perfect precision/recall score.
- False positives/hour = FP / (all evaluated clip duration / 3,600,000 ms),
  including negative clips. This is evaluated footage time, not runtime.
- Timestamp error = median over matches of `(abs(start error)+abs(end error))/2`.
  No matches means undefined.
- Processing ms is **recorded during capture**, including analysis proxy
  preparation/decode, excluding import and initial/final source hashing. The
  real-time factor is total clip duration / total recorded processing time;
  zero processing time is undefined.

The report is deterministic for the same manifest **and frozen observations**.
Capture itself measures a real execution, so its new timings/observations hash can
differ between runs/machines. Freeze both input files for reproducible comparisons;
the observation file is sealed to the canonical manifest hash. Re-capture for a
new engine/profile and compare fresh reports rather than rewriting an old result.

## Compatibility and privacy

Reports group by upright resolution, locale, HUD scale and compression; each row
has metrics, footage hours and status. Synthetic rows remain `synthetic-only`;
other local rows remain `unvalidated`. A measurement never automatically declares
GTA compatibility. GTA VI default has **not measured** precision/recall and zero
evaluated gameplay hours; it remains **Unvalidated**.

The JSON/Markdown writer explicitly selects only metrics, public profile/detector
identifiers, bounded annotation metadata and hashes. It includes no media bytes,
filenames, paths, source event IDs, attributes, OCR strings or transcripts. Hashes
can still identify media; inspect a report before sharing. Outputs must be new
files/directories. Cancelling capture/evaluation leaves source media unchanged and
cleans its scratch library; no network call or model download is introduced.

This small synthetic holdout establishes harness behavior, not gameplay
precision/recall, a minimum Windows CPU benchmark, or quality for the wanted/OCR/
audio detectors. Add independent, legitimately obtained annotated holdouts for
those producers; M19 does not train or retune them.
