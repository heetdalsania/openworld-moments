# M09 — Desktop library and jobs UI

## Objective

Deliver the first usable desktop workflow: import media, observe background work, browse assets, play proxies, and understand failures.

## Dependencies

M03, M05, and M08 merged.

## Required context

Read specification sections 10.1–10.3 and 12.4.

## In scope

- Primary navigation shell.
- Import button and drag/drop.
- Asset/library grid and detail view.
- Proxy/original playback choice.
- Background-job center with progress, cancel, retry, and errors.
- Empty/loading/error/cancelled states.
- Missing-source and derived-media status.
- Keyboard navigation and basic accessible labels.

## Out of scope

- Sessions, event timeline, editing, search, and phone transfer.

## Implementation steps

1. Add typed API client and query cache.
2. Build import entry points and batch result view.
3. Build library grid/list with stable pagination.
4. Build asset detail and player using derived proxy when available.
5. Connect job-event stream and recovery after UI reload.
6. Add actionable error presentation without raw stack traces.
7. Add component and end-to-end tests.

## Acceptance criteria

- A user can import and play a supported clip without a terminal.
- Long jobs remain visible after navigation and UI reload.
- Cancel/retry actions reflect durable job state.
- Missing source and failed proxy are distinguishable.
- All primary controls are keyboard reachable.
- UI never implies source deletion or modification.

## Required validation

- Component tests for all states.
- End-to-end import-to-playback path.
- Keyboard-only walkthrough.
- Worker restart while UI is open.

## Handoff

Provide screenshots, route/component map, API hooks, known player limitations, and E2E command. Update M09.

