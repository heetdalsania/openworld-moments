# M20 — Story engine

## Objective

Convert reviewed events, transcript boundaries, audio evidence, and unique session time into explainable candidate clips with setup and payoff coverage.

## Dependencies

M12 and M19 merged.

## Required context

Read specification section 8.5 in full.

## In scope

- Seed windows from reviewed/high-confidence events.
- Pre/post roll, causal/temporal merge, overlap removal, and duration presets.
- Transcript sentence and silence/scene boundary adjustment.
- Beat representation: setup, incident, escalation, payoff, reaction.
- Inspectable score components and alternative boundaries.
- Candidate accept/reject and regeneration semantics.

## Out of scope

- “Viral” prediction, automatic publishing, general LLM storytelling, and final editing UI.

## Implementation steps

1. Define story candidate and beat contracts.
2. Implement deterministic seed/merge/expand pipeline.
3. Add duration presets and hard constraints.
4. Add score components and rejection penalties.
5. Add alternative short/long boundary candidates.
6. Persist generator version and source-event references.
7. Add golden timeline fixtures and metric hooks.

## Acceptance criteria

- Related event windows merge without duplicated overlap.
- Speech is not truncated when timing evidence exists and duration permits.
- Every score is decomposable into documented components.
- Candidate links to exact source events and time ranges.
- No events produces no automatic candidate, not fabricated content.
- Manual story creation remains possible through downstream editor model.

## Required validation

- Golden cases for isolated event, chase sequence, overlapping events, no payoff, long silence, and duration pressure.
- Determinism and version invalidation tests.
- Setup/payoff coverage report.

## Handoff

Document algorithm stages, presets, score weights, known failure cases, and golden fixture results. Update M20.

