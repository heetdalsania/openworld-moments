# Sessions: capture time and grouping

M11 groups imported clips into **candidate play sessions** from metadata alone:
capture times, source, format, and import order. Every decision is explainable
and every user correction is permanent. Visual and audio overlap (M12) will
refine sessions later. Nothing here opens, moves, or changes a media file.

Code: `services/media-worker/openworld_moments/sessions/`

| File | What it holds |
|---|---|
| `capture.py` | Capture-time estimation |
| `grouping.py` | Grouping rules |
| `service.py` | Recompute and corrections |
| `fixtures.py` | Synthetic scenarios |

Also:

- **Contract:** `session.schema.json` (contracts 1.7).
- **Migration:** 0008.
- **Job:** `group` (state `grouping`).

## Capture time

Each asset carries `capture_time = {captured_at, confidence, basis}` (spec
8.2.4). It is estimated when the asset is imported and again by every `group`
run, from three signals:

| Signal | Where it comes from | Known weakness |
|---|---|---|
| `filename` | The local wall-clock time in the file name (patterns below) | No time zone: read in the computer's zone for that date (daylight-saving rules of the recording date, where the system exposes an IANA zone; on Windows, the current offset) |
| `container_metadata` | The container's creation time, probed at import and stored as `media_assets.container_created_at` | Some devices write local time as UTC; some apps rewrite it on download |
| `filesystem_mtime` | The file's modification time at import, minus the clip's duration (consoles write the file at the end of recording) | Copies and downloads reset it |

### Filename patterns

| Name | Example | Typical source |
|---|---|---|
| `ymd_hms` | `Heist 2026-11-20 03-14-22.mp4`, `GTA V-2026_11_20-03_14_22.mp4`, `2026-11-20T03:14:22.mkv` | OBS, Xbox (OneDrive), generic |
| `ymd8_hms6` | `VID_20261120_031422.mp4`, `PXL_20261120_031422123.mp4` | Android phones |
| `ymdhms14` | `Heist_20261120031422.mp4` | PlayStation |
| `mdy_hms_ampm` | `Heist 11_20_2026 3_14_22 PM.mp4` | Xbox Game Bar (Windows) |

A name is refused, so no time is taken from it, when:

- the date or time is impossible;
- the year is not 20xx;
- a 12-hour time is out of range;
- it contains two *different* times.

### Confidence calculation

The estimate takes the first available signal in the order filename, then
container, then mtime. It then compares the others with it. **Estimator
version 1:**

1. **Base confidence** of the chosen signal: filename 0.60, container 0.55,
   mtime 0.25.
2. **Agreement:** each other signal within 2 minutes adds 0.20 (mtime adds
   0.10) and joins the `basis`.
3. **Disagreement:**
   - A container time that disagrees halves the confidence. If the difference is
     a whole number of hours (1–14 h, ±2 min), a note says "possible time-zone
     mismatch".
   - A disagreeing mtime is expected (copies, downloads) and only gets a note.
4. **Limits:** the result is kept between 0.05 and 0.95.
5. **Copy artefacts:** mtimes within 3 seconds of another file's in the same
   import job are copy times, not capture times. An estimate based on such an
   mtime alone drops to at most 0.10, with a note.

**An estimate never becomes more precise than its sources.** A single mtime
stays weak, and conflicting sources lower confidence instead of picking a
"best" time silently. Times with `basis: ["user"]` are never re-estimated.

## Grouping rules

**Algorithm `owm-metadata-gap`, version 1.** Assets are split by **source key**:

- the source kind plus the folder of the asset's first import;
- for phone uploads, the kind alone, because each upload has its own staging
  folder.

Within a source, clips are ordered by estimated start, then by import order,
then by ID. Each clip joins the previous clip's session when all three hold:

| Rule | Default | Split reason otherwise |
|---|---|---|
| Same codec | — | `codec_changed` |
| Same upright resolution | — | `resolution_changed` |
| Frame rate within 1% | — | `frame_rate_changed` |
| Starts at most `max_gap_ms` after the previous clip ends | **15 minutes** (job param `max_gap_ms`, or the `sessions.max_gap_ms` setting; 1 min – 24 h) | `gap_exceeded` |

- **Overlapping clips** (a negative gap, typical of replay buffers) join, and
  the link is marked `overlapping`.
- **The boundary is inclusive:** exactly 15 minutes still joins.
- **Unknown times:** when either clip's time is unknown (confidence ≤ 0.15,
  typically copy artefacts), time cannot decide. Neighbours from the same import
  job join on `import_order` alone, at confidence 0.15. Otherwise the clips are
  split as `time_unknown`.

**Evidence:** each join is stored as a link `{from_asset_id, to_asset_id,
gap_ms, confidence, reasons}`. A session that does not continue the previous one
from its source records `split_before`. Members' capture-time caveats are kept
as `notes`.

**Session confidence:**

- **For a join:** min(the two clips' capture confidences) × a gap factor (1.0 up
  to a one-minute gap, falling linearly to 0.7 at the maximum gap).
- **For a session:** its weakest link; for a single clip, that clip's capture
  confidence.

## Recompute (the `group` job)

`POST /v1/sessions/recompute` (params `GroupRequest`) runs in **one database
transaction**:

1. **Re-estimate** every asset's capture time and store changes.
2. **Lock** the members of `corrected` and `confirmed` sessions, and of any
   session with **attached data**: a story, events, transcript segments, or a
   collection entry. Deleting such a session would drop those rows (they cascade)
   or be blocked by them, so recompute never changes or removes it.
3. **Group** all other assets.
4. **Reconcile with existing `unreviewed` sessions:**
   - each group keeps the ID of the unreviewed session it shares the most clips
     with (an exact match wins);
   - unchanged sessions are not written at all;
   - unreviewed sessions that no group continues are removed. Only sessions
     without attached data can be in this set, so removing one deletes just its
     membership rows, never media or anything else.

**Idempotent:** a second run over the same data creates, updates, and removes
nothing, and returns the same session documents. It is safe to requeue.
`GroupResult` reports the counts.

## Manual corrections

Each correction is one transaction. It marks the touched sessions
**`corrected`** and is written to the `session_corrections` log (`GET
/v1/sessions/{id}/corrections`). Because recompute skips corrected and confirmed
sessions, **corrections survive every future run**.

| Action | API | Effect |
|---|---|---|
| Merge | `POST /v1/sessions/merge {session_ids}` | Members combined into the first session, in capture-time order; the others are removed. Refused (`session.in_use`) if a session being removed has attached data (stories, events, transcripts, collection entries); list that session first to merge into it instead |
| Split | `POST /v1/sessions/{id}/split {after_asset_id}` | Clips up to that one stay; the rest form a new corrected session |
| Reorder | `POST /v1/sessions/{id}/order {asset_ids}` | Every member once, in the user's order. Out-of-time-order clips are then placed end to end (`session_start_ms` = cumulative durations) |
| Mark unrelated | `POST /v1/sessions/{id}/remove {asset_id}` | The clip moves to a corrected session of its own and is never regrouped |
| Confirm | `POST /v1/sessions/{id}/confirm` | `unreviewed` → `confirmed`; membership and evidence are kept and locked |

- **A corrected session has no automatic evidence:** `grouping` and
  `grouping_confidence` are null, because its membership is the user's decision.
  The log says what changed.
- **Errors:** `session.not_found` (404), `session.invalid_request` (422), and
  `session.in_use` (409).

## Session order and offsets

- **`order_index`** is 0, 1, 2, … in session order.
- **`session_start_ms` in chronological sessions** comes from capture times
  relative to the first clip. It never decreases: overlapping clips start no
  earlier than the clip before them.
- **In hand-ordered sessions** clips are placed end to end. M12 will replace
  these offsets with measured overlaps (`overlap_with_previous_ms`).

## Fixtures and tests

`openworld_moments.sessions.fixtures` builds synthetic, metadata-only assets
(rows and import provenance; no media). Run
`python -m openworld_moments.sessions.fixtures` to print the scenarios:

- adjacent clips from one source, a large gap, a format change;
- mixed folders, mixed sources, overlapping replays;
- phone copies without times, a time-zone mismatch, and the exact gap boundary.

`tests/sessions/test_sessions.py` covers:

- the filename patterns and refusals;
- agreement, disagreement, and time-zone handling, including a daylight-saving
  date and a +5:30 zone;
- copy artefacts;
- the scenario matrix;
- the custom gap;
- idempotent recompute and stable IDs as clips arrive;
- each correction surviving recompute;
- the correction log and refused corrections;
- locks from confirmations and stories;
- no file access during grouping;
- the job and API end to end.

## Limitations

- **Metadata only:** clips with the same source and format recorded within
  15 minutes of each other join even if they are different games; game
  detection (M14+) and overlap (M12) refine this.
- **Filename times assume the capture device used the computer's time zone.**
  A mismatch shows up only when another signal disagrees.
- **No UI yet:** the Inbox and session review screens arrive in later
  milestones; corrections are API-only in M11.
- **Recompute is not automatic** after imports yet; the UI milestone that shows
  sessions will trigger it.
