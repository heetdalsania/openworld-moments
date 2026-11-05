# M26 — Search and collections

## Objective

Make clips, sessions, transcripts, and detected events discoverable through fast local search and reusable collections.

## Dependencies

M02, M09, and M19 merged.

## Required context

Read specification sections 7.4, 8.8, 9.7, and 12.2.

## In scope

- SQLite FTS index for user text, transcripts, OCR text, and event labels.
- Filters for date, duration, source, session, event type, confidence, and review state.
- Timestamp-level results that seek to supporting evidence.
- Manual and rule-based collections.
- Index rebuild, progress, cancellation, and integrity checks.
- Privacy-safe deletion of derived index data.

## Out of scope

- Cloud search, semantic embeddings, web discovery, and shared team libraries.

## Implementation steps

1. Define normalized searchable documents and index-version metadata.
2. Add migration-backed FTS tables and transactional update triggers/jobs.
3. Index clips, sessions, events, transcript spans, and user annotations.
4. Implement query parsing, facets, ranking, snippets, and timestamp navigation.
5. Add collection CRUD plus explicit, inspectable collection rules.
6. Add cancellable full rebuild and stale-index detection.
7. Build performance and correctness fixtures at representative library sizes.

## Acceptance criteria

- Search results identify the matching source and exact supporting time range.
- A 10,000-clip fixture returns common queries in under 300 ms on the reference machine.
- Index rebuild never changes source media or canonical analysis records.
- Deleting a transcript or event removes it from results after the transaction commits.
- Rule-based collections explain why each item matched.
- Empty, malformed, and special-character queries fail safely.

## Required validation

- Ranking, filtering, Unicode, phrase, prefix, deletion, and rebuild tests.
- Corrupt/stale index recovery and cancellation tests.
- Keyboard-complete search-to-playback end-to-end test.

## Handoff

Document the searchable-document contract, ranking rules, benchmark hardware/results, collection rule grammar, rebuild procedure, and privacy behavior. Update M26.
