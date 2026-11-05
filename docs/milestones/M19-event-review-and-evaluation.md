# M19 — Event review and evaluation

## Objective

Make detector output inspectable and correctable, and provide a reproducible evaluation harness that reports quality instead of relying on anecdotal demos.

## Dependencies

M13, M16, M17, and M18 merged.

## Required context

Read specification sections 10.4, 13.2, 13.3, and 19.3.

## In scope

- Event markers on virtual session timeline.
- Evidence inspector with detector/profile/tool versions.
- Approve, reject, relabel, adjust interval, and manually add event.
- Immutable detector output plus separate user correction layer.
- Local evaluation manifest and CLI.
- Precision, recall, F1, false positives/hour, timestamp error, and performance report.
- Compatibility matrix generation.

## Out of scope

- Story generation, model training, and central telemetry collection.

## Implementation steps

1. Add review/correction contracts and persistence.
2. Render event lanes and evidence details.
3. Implement manual event creation and correction audit trail.
4. Define evaluation annotation format referencing local media by hash.
5. Implement matcher and metrics with tolerance windows.
6. Generate Markdown/JSON report and compatibility row.
7. Add synthetic holdout fixtures separate from tuning fixtures.

## Acceptance criteria

- User correction never mutates original detector record.
- Re-analysis preserves or explicitly reconciles reviewed corrections.
- Evaluation report is deterministic from the same manifest.
- False positives/hour and timestamp tolerance are calculated correctly.
- Shareable report contains no footage, private paths, or transcripts by default.
- UI exposes unvalidated profile status prominently.

## Required validation

- Correction/re-analysis tests.
- Metric unit tests including boundary cases.
- E2E event review path.
- Report privacy inspection.

## Handoff

Attach a sample synthetic evaluation report, document annotation format and reconciliation rules, and update M19.

