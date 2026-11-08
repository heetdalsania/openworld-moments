# M28 — Privacy and spoiler review

## Objective

Give creators a deliberate pre-export review that surfaces likely personal information, mixed voice chat, subtitles, and spoiler-sensitive content.

## Dependencies

M17, M18, and M22 merged.

## Required context

Read specification sections 8.8, 14, 15.6, 17, and 21.

## In scope

- Explainable risk flags from OCR, subtitles, transcripts, and audio metadata.
- User-defined spoiler labels and time ranges.
- Manual rectangular blur regions with keyframes.
- Mute suggestions for selected transcript/audio ranges.
- Pre-export checklist with explicit acknowledge, fix, or ignore decisions.
- Local-only processing and deletion controls for review artifacts.

## Out of scope

- Identity recognition, guaranteed PII detection, legal clearance, and automated censorship.

## Implementation steps

1. Define risk-flag, review-decision, blur-region, and spoiler-range contracts.
2. Add conservative pattern detectors with evidence and category labels.
3. Build a timeline review panel linked to exact source ranges.
4. Add blur keyframes, preview, and render-plan compilation.
5. Connect mute decisions to M23 audio controls.
6. Add an export gate that records unresolved and acknowledged findings.
7. Document false positives, false negatives, and local retention behavior.

## Acceptance criteria

- No export is described as privacy-safe or legally cleared by the application.
- Every flag shows its evidence category and supporting time range.
- Users can dismiss false positives and later reverse the decision.
- Blur preview matches rendered output on golden fixtures.
- Mixed voice-chat risk is shown when separation is impossible.
- Review data and derived text can be deleted without deleting source clips.

## Required validation

- Synthetic phone-number, username, subtitle, voice-chat, and spoiler fixtures.
- Blur interpolation, dismissal persistence, export-gate, and deletion tests.
- False-positive cases containing scores, coordinates, and HUD numbers.

## Handoff

Document detectors, limitations, retention rules, export-gate states, blur behavior, fixtures, and all wording that avoids overpromising protection. Update M28.
