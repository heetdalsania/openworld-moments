# Generic banner and subtitle OCR

Synthetic-only reference profile, version 1.0.0, Apache-2.0. Game compatibility,
including GTA VI, is **unvalidated**. The English vocabulary consists of original
generic test phrases; no official font, screenshot or text corpus is bundled.

Install Tesseract 5+ and English `eng.traineddata` explicitly. Check availability
with `uv run --directory services/media-worker owm text doctor`. The application
never downloads OCR components automatically. Missing OCR skips its units while
other detectors stay usable.

The 16:9 profile supports upright sources from 640×360. Use Settings → Calibrate
detector profile regions to align `mission_banner` and `subtitle` to the text.
Analysis uses the saved local overrides. The M15 single-frame preview still
supports only the bright-region example; this profile runs through the existing
analyze job/API/CLI. It does not add an OCR UI.

English pack `en` version 1.0.0 maps to Tesseract language `eng`. Vocabulary keys
are `failure`, `arrest`, `mission-started`, `mission-objective`, `mission-completed`
and `mission-failed`. Local profiles can define another licensed/versioned pack
and installed OCR language without editing Python. Matching uses the whole
normalized text, a default 0.9 similarity and category ambiguity rejection.

Default confirmation is two 500 ms samples, with one tolerated miss. Banner
preprocessing preserves grayscale contrast; subtitles use thresholding. Text below
0.6 OCR confidence is discarded. Known categories require ≥0.75 OCR confidence;
unknown recognized banner text gets a generic OCR interval capped at 0.49. The
common event threshold is 0.3 so these unknown observations remain inspectable.
Raising it can hide them. Confidence is heuristic, not a calibrated probability.

See [algorithm, evidence, validation and limits](../../docs/detectors/text.md).
