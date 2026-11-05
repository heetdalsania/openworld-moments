# M17 — Banner and subtitle detectors

## Objective

Detect configured mission/failure/arrest banners and subtitle text through localized, region-constrained OCR with conservative temporal rules.

## Dependencies

M15 merged.

## Required context

Read specification sections 8.4.4, 8.8.2, and the footage policy.

## In scope

- OCR adapter abstraction and one local implementation.
- Profile-defined banner and subtitle regions.
- Locale vocabulary packs and fuzzy matching.
- Temporal appearance/disappearance events.
- OCR line boxes, confidence, and source timestamps.
- Initial generic event types for failure, arrest, mission state, and subtitle changes.
- Synthetic stylized-text fixtures only in repository.

## Out of scope

- Full-screen OCR, story interpretation, translation, and copyrighted font redistribution.

## Implementation steps

1. Select OCR engine and record model/license/packaging implications.
2. Implement preprocessing variants per region type.
3. Implement constrained vocabulary matcher and unknown-text path.
4. Add temporal deduplication for persistent banners/subtitles.
5. Emit spoiler-risk metadata for mission text without classifying story meaning.
6. Add locale pack format and English synthetic pack.
7. Benchmark accuracy and processing cost.

## Acceptance criteria

- Persistent subtitle emits one interval rather than frame spam.
- Known synthetic banner variants map to the right generic event.
- Unknown text remains raw low-confidence OCR, not a fabricated mission event.
- Region-only OCR avoids reading unrelated UI.
- Locale and OCR model versions are recorded.
- No official font, screenshot, or text corpus is committed.

## Required validation

- Scale, compression, contrast, outline, multiline, and false-region tests.
- Temporal deduplication test.
- OCR-unavailable graceful-degradation test.

## Handoff

Document OCR dependency, preprocessing, vocabulary format, confidence thresholds, and known locale limitations. Update M17.

