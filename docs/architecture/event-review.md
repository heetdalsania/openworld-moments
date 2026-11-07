# Event review (M19)

The session screen shows event markers in the same virtual timeline as M13,
with an evidence inspector and explicit approve, reject, label/interval correction,
reset and manual-event controls. **Game compatibility is unvalidated.** Audio
observations are supporting evidence, never highlights. Confidence remains a
heuristic associated with the original observation.

## Immutable observations and separate decisions

Migration **0012** adds two session-owned tables:

- `event_observations`: original contract JSON, original event ID, session ID,
  creation time and the producing session-layout hash. The event ID is independent
  of the replaceable producer table: a rerun cannot cascade-delete the snapshot.
- `event_decisions`: append-only revisions keyed by event ID and integer revision.
  Each decision stores the effective type, unique-session interval, review state
  and creation time. Reads return the latest 20 decisions and a truncation flag;
  earlier revisions stay in SQLite.

The existing `events` table and `detector_runs` continue to supply raw producer
results/cache identity. M19 does **not** update an observation's type, confidence,
attributes, evidence, provenance or original review state. Reset appends an
`unreviewed` decision using the original label/interval. Approve/reject retain
previous explicit label/interval corrections. Manual creation stores a new
`source.kind: user`, confidence-1, confirmed observation with no fabricated
machine evidence; this is the user's assertion, not detector certainty.

Every successful new producer commit records its original snapshots in the same
transaction. Existing pre-M19 observations are archived before replacement or on
first inspection, with an unknown layout hash. A raw record already reviewed by
older internal APIs remains untouched.

## Re-analysis and reconciliation

Reconciliation is explicit, conservative, and based on identity rather than an
inferred similarity match:

| Status | Meaning and behavior |
|---|---|
| `current` | Original ID still exists in producer results (or is manual), and its recorded layout hash matches the current session. May seek/review. |
| `superseded` | Producer replaced this ID. Original and decisions survive as read-only history. Review the new candidate separately; no correction is silently transferred. |
| `stale` | ID exists but session order, membership, duration or applied overlap changed. Inspection/history remain available; seeking/review are disabled until a fresh observation is produced. |
| `legacy` | The original has no proven producing layout. Inspection is available; rerun the chosen detector before reviewing a replacement. |

The page contains current candidates plus any superseded observation with user
decisions. Superseded unreviewed snapshots remain archived without filling the
UI. Manual records survive detector reruns. A session-layout edit also marks
manual records stale; explicitly create a new interval in the new layout rather
than silently reinterpreting the old range. Session regrouping/merge guards count
archived observations as attached data, even if no current event remains.

The desktop independently hashes the displayed layout and disables markers and
edits until that hash matches the returned review page. If Web Crypto is
unavailable, it fails closed.

Mutation requests include the layout hash the user saw and the review revision
captured when the form opened. An immediate SQLite transaction rechecks both,
the current event identity, and the interval. A layout/review/rerun race returns
409; the UI refreshes and keeps the conflict visible. A correction requires a
namespaced type and `0 <= start < end <= unique session duration`; malformed,
noninteger, unknown or immutable fields return 422. No user field becomes SQL or
a shell expression. Foreign-session IDs return 404.

## API and contracts

Contracts **1.14** add `event-review`, `evaluation`, `evaluation-observations` and
`evaluation-report`; previous 1.x documents remain readable. TS/Python verify
nested evidence, unchanged immutable fields, page/event identity, history order,
clip ranges, unique media hashes and unique detector identities.

| Route | Purpose |
|---|---|
| `GET /v1/sessions/{id}/review?offset=0&limit=50` | Versioned page: layout key/duration, originals, effective views, statuses and recent audit history; limit clamped to 1–100. |
| `POST /v1/sessions/{id}/review` | Manual interval, explicit layout key and type. |
| `POST /v1/sessions/{id}/review/{eventId}` | `approve`, `reject`, `correct` or `reset`, with layout key and expected revision. |
| `POST /v1/sessions/{id}/analyze` | Existing analyze job, now available to the desktop through the host allowlist. |

Review POST responses return the affected `EventReviewItem`. The legacy
`GET /v1/events` continues to return raw producer observations; consumers needing
human decisions must use the review projection. No new cloud service or job kind
is introduced. M20 must consume only current effective review views and apply its
own policy for rejected/unreviewed observations.

## Desktop behavior and privacy

- Profile choice starts empty; analysis runs only after the user selects a profile
  and presses **Analyze events**. Existing Background jobs provides cancellation.
- Markers and the ordered accessible event list seek the current playback view.
  Unique review times map through source coordinates when repeated footage is
  revealed. Manual insertion maps the playhead back into unique time.
- Inspector shows original confidence, evidence, profile/detector/tool versions,
  source times/crops, original text, mission spoiler flag and decision history.
  React renders recognized text as text, never HTML.
- Original JSON and OCR text remain local. Evaluation reports never serialize the
  inspector, attributes, evidence or transcripts. There is no telemetry.
- UI covers loading/empty/error states, conflicts, historical/stale status,
  cancelled/failed analysis, keyboard controls and paginated observations.

## Limits

Snapshots and decisions intentionally remain until their session/library is
removed; this is not a retention-manager UI. Old corrections never imply approval
of a new model/detector output. No OCR crop-image renderer, confidence calibration,
caption editing, story generation or training is added here. M18 transcripts still
follow their documented snapshot/rebuild policy; event review does not make stale
transcripts current automatically.
