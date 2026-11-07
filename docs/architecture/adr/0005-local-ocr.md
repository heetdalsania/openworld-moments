# ADR-0005: Local region OCR with Tesseract

- Status: Accepted for the M17 implementation; subject to maintainer review
- Date: 2026-11-07
- Milestone: M17

## Context

M17 needs a local OCR adapter, line boxes, localized vocabulary and temporal
intervals. M14/M16 already provide trusted built-ins, derived-only frame inputs,
calibration, producer isolation and versioned caches. The 200×40 indicator crop
is insufficient for multiline text. Full-screen OCR and model downloading are
outside this milestone.

## Decision

Use a protocol-backed **Tesseract 5+ executable** with LSTM (`--oem 1`), block
segmentation (`--psm 6`) and TSV output. Crop the checked M08 SDR proxy to the
calibrated region at 2 fps, resampling to 640×128. Only these immutable grayscale
pixels reach the adapter. Existing whole-frame and wanted samplers remain usable.

The adapter contrast-normalizes/inverts or thresholds a crop and adds a white
border. It writes an owned temporary PGM, invokes the executable using an argument
array through the existing cancellable runner, validates bounded TSV and removes
the scratch directory. It cannot receive an original source path from the SDK.

Discover the explicitly configured `OWM_TESSERACT` executable, PATH, or the standard
Windows installation. Never download an engine/model at runtime. Missing engines
or selected language data skip OCR units explicitly. Record engine version,
selected language, language-data SHA-256, preprocessing and locale-pack versions
in event/cache provenance. Recheck model metadata during recognition and its
hash before committing a computed unit.

Tesseract and official tessdata/tessdata_fast data use Apache-2.0; installed
custom data still needs its own provenance/license review. No engine or model is
committed. M29/M34 own bundling, architecture, catalog, notices and packaged data
verification. This implementation adds no production Python dependency.

OpenCV/NumPy are **development dependencies only** for synthetic lettering.
Use explicit Hershey Simplex/Duplex styles, with scale-aware stroke width; no font
file is copied into the repository. OpenCV's Hershey implementation retains BSD
terms within the Apache-licensed project. Its package notices remain relevant
when distributing a development environment. Generated test media stays local.

## Consequences

- Recognized lines have confidence, global normalized boxes and source sample time.
- A confirmed presence/disappearance becomes one interval; unknown text stays raw
  low-confidence OCR rather than a mission claim.
- Real-engine tests need Tesseract plus English data. CI installs them explicitly
  and sets `OWM_REQUIRE_OCR=1`; missing-OCR behavior also has independent tests.
- Fixed 640×128 samples and the existing 64 MiB cap limit a text-analyzed asset
  to roughly 6.8 minutes. Streaming/long-asset chunking is future work.
- Two fps and independent asset units cannot establish exact source-frame timing
  or infer text continuity across clip boundaries. Game compatibility is unvalidated.

## Alternatives considered

- A neural OCR framework: larger native/model and packaging surface for this slice.
- A Python Tesseract wrapper: unnecessary when the process runner already provides
  cancellation, output caps, timeouts and private-path redaction.
- Whole-frame OCR: violates M17's region boundary and reads unrelated UI.

## References

- [Tesseract CLI and TSV](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
- [Tesseract manual](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)
- [Tesseract data license](https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE)
- [OpenCV Hershey implementation and retained license](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/src/hershey_fonts.cpp)
