# Virtual session timeline

M13 plays a session as one continuous timeline. The clips play back to back. When a
later clip starts with footage the previous clip already shows, that repeated part is
skipped. Every moment on the timeline stays traceable to a clip and a time in that
clip.

Code:

- `apps/desktop/src/timeline.ts`: the pure mapping library;
- `apps/desktop/src/player.ts`: the playback controller (`SessionPlayer`);
- `apps/desktop/src/SessionView.tsx` and `SessionsView.tsx`: the screens.

Inputs come from the session document (M11, M12):

- the member order;
- `duration_ms`;
- `overlap_with_previous_ms`, the overlap the worker applied;
- `alignment_confidence`;
- each asset's average frame rate (`video.average_frame_rate`, else `frame_rate`).

## Terms

| Term | Meaning |
|---|---|
| **Source time** | Milliseconds into one clip, as the file plays it. |
| **Virtual time** | Milliseconds into the session timeline. It starts at 0 and has no gaps. |
| **Segment** | The part of one clip that plays: `[sourceInMs, sourceOutMs)` of the clip, placed at `[virtualStartMs, virtualEndMs)`. |
| **Hidden overlap** | The start of a clip, `[0, hiddenMs)`, that repeats the previous clip and is skipped. |

### What virtual time leaves out

Virtual time ignores real pauses between recordings. `session_start_ms`, which can
contain gaps, describes capture time and is not used for playback. Two clips recorded
ten minutes apart play one after the other.

## Mapping API (`timeline.ts`)

| Function | Does |
|---|---|
| `buildTimeline(members, { reveal })` | Builds segments in member order. Overlaps are clamped to `[0, duration]`, and a first clip's overlap is ignored. With `reveal`, nothing is hidden and `revealedDuplicateMs` marks the repeated range instead. |
| `toSource(t, virtualMs)` | Returns `{ segment, sourceMs }`. Virtual time is clamped to `[0, duration]`. A boundary belongs to the next clip, so `virtualStartMs` maps to that clip's first unique frame. The timeline end maps to the last clip's end. Clips with no unique footage are skipped. Lookup is a binary search. |
| `toVirtual(t, index, sourceMs)` | Returns `{ virtualMs, exact }`, or `null` when `sourceMs` is outside the clip. A visible moment maps exactly. A hidden moment maps to the same moment in the previous clip and returns `exact: false`; that moment is at `duration(prev) − overlap + sourceMs` in the previous clip, resolved recursively. |
| `indexOf`, `boundaries`, `nearestBoundary` | Find clips and move between clip starts. |
| `frameMs(member)` | One frame at the clip's average rate. Defaults to 30 fps when the rate is unknown. |
| `stepFrame(t, virtualMs, ±1)` | Steps one frame of the clip on screen. A step that crosses a boundary lands on the neighbouring clip's first unique frame (forward) or its last frame (back). |
| `repeatedMs(t)` | Total repeated footage, hidden or revealed. |

Times are integer milliseconds.

## Precision guarantees

These are enforced by `timeline.test.ts`:

- **Round trips:**
  - `toVirtual(toSource(v)) === v` for every virtual millisecond.
  - Mapping every source frame to virtual time and back stays in the same clip and
    lands within one frame.
  - Tested at 23.976, 24, 25, 29.97, 30, 50, 59.94, 60, and 120 fps, and at a
    VFR average of 47.3 fps.
- **Overlap cases:**
  - zero overlap: clips are laid end to end;
  - partial overlap: the hidden start is skipped;
  - full overlap: the clip adds no time and is skipped;
  - clamping;
  - an empty session.
- **Frame steps:** each step is exactly one frame of the clip on screen. A boundary
  is never stepped over twice.
- **Variable frame rate:** steps use the average rate. A VFR clip's real frame
  times can differ from that rate, so a step can land between two decoded frames.
  The browser then shows the nearest one.

## Playback controller (`player.ts`)

`SessionPlayer` drives two media elements through a `MediaLike` interface, which
keeps it testable without a browser:

- The **active element** plays the current segment.
- The **standby element** is already loaded with the next segment, at its first
  unique frame.

Its rules:

- **Boundary switch:** when the active element reaches `sourceOutMs` minus half a
  frame, playback switches to the standby element. Switching is triggered by:
  - `tick()` on every animation frame;
  - `timeupdate` events, for background windows where animation frames are paused;
  - the `ended` event, for a playback copy that is a frame shorter than its
    metadata.

  The roles then swap, and the following segment is preloaded.
- **No replay:** the repeated footage is never played, because the incoming element
  is already at `sourceInMs`.
- **Clock:** the virtual clock is derived from the active element's position. It
  continues across a switch without a jump.
- **Audio follows the picture.** Only the active element is audible; the standby
  element is always muted. One element carries both picture and sound, so they stay
  in sync across a switch. The player test "keeps sound with the picture" is the
  A/V boundary smoke test.
- **Layout changes:** `setTimeline` is called after a reveal toggle, reorder,
  override, or split. It stays on the same clip and source moment, even at a clip's
  very end. If that moment becomes hidden, it goes to the same moment in the
  previous clip. If the clip left the session, it goes to the start.
- **Errors:** a failed `play()` or a media `error` on the active element stops
  playback and reports a message. The position is kept. Errors on the standby
  element are ignored until that element becomes active.

## Session screens

- **`#/sessions`:** candidate sessions, each with:
  - clip count;
  - played duration (repeated footage excluded);
  - hidden repeated footage;
  - review state;
  - grouping confidence.

  Buttons start the `group` (M11) and `align` (M12) jobs. **Merge selected**
  merges into the earliest selected session and opens it.
- **`#/session/<id>`** has:
  - **Player:** play/pause, frame steps, previous/next clip, mute, a time readout,
    and a frame-step position slider. A source readout says which clip and time is
    on screen ("Clip 2 of 3: … at 0:12.34"), and whether it is the playback copy.
  - **Track:** clips laid end to end, with thumbnails and waveforms of the part
    that plays. Boundaries and a hidden-overlap marker are drawn on it. A legend
    lists each clip's start, its hidden repeated footage, and the alignment
    confidence. **Show repeated footage** reveals the repeated ranges, hatched on
    the track.
  - **Clip list** of corrections (M11/M12 APIs). Each correction refreshes the
    session, and the player keeps its moment:
    - move earlier or later;
    - split after this clip;
    - not part of this session;
    - not repeated footage (override 0);
    - use automatic match (clear the override);
    - confirm session.
  - **Keyboard** (on the player group):

    | Key | Action |
    |---|---|
    | Space or K | Play/pause |
    | ← / → | 5 seconds back / forward |
    | `,` / `.` | One frame back / forward |
    | `[` / `]` | Previous / next clip start |
    | Home / End | Session start / end |
    | R | Show repeated footage |
    | M | Mute |

    Buttons and checkboxes keep Space and Enter.

## Source-boundary behavior

- A seek to an exact boundary shows the next clip's first unique frame.
- At the end of a clip during playback, the next clip starts at its first unique
  frame. Repeated footage plays only when revealed.
- A clip that is entirely repeated footage is skipped and labelled.
- Seeking to an event time in source terms (`toVirtual`, used by event markers in
  M19) always selects a clip. A hidden moment resolves to the earlier clip that
  shows the same footage, flagged `exact: false`.
- **Reorder:**
  - Out of capture order, the worker places clips end to end with no overlap.
  - Restoring capture order brings the cached alignment back without recomputing.
  - The corrections never change membership or source files.

## Player limitations

- **Formats:**
  - Each clip plays its playback copy when ready, otherwise the original, which
    only plays in a format the web view decodes.
  - A clip with an offline original and no playback copy is reported and cannot
    play.
- **Switch timing:**
  - The switch happens on the next animation frame or `timeupdate` after the
    boundary. In a foreground window that is within about one frame. A background
    window can lag up to about 250 ms.
  - A brief black frame or stall is possible on slow disks if the standby element
    has not buffered yet. A loading indicator shows while waiting.
- **Overlap precision:** overlaps are as precise as M12 measures them (samples every
  500 ms, refined by audio). Up to a few frames of repeated or missing footage at a
  boundary is possible.
- **Out of scope for M13:**
  - playback speed and A/V offset controls, which the editor milestones (M21, M22)
    own;
  - rendering (M24).

## Tests

| Test | Covers |
|---|---|
| `timeline.test.ts` | Mapping, overlap cases, frame rates, steps, boundaries |
| `player.test.ts` | Preload, boundary crossing without replay, clock continuity, end and restart, seek, frame steps across boundaries, audio muting, relayout at clip ends, reveal and reorder keeping the moment, `ended` and error handling |
| `SessionView.test.tsx` | The screen through the fake host: playback across a boundary, the keyboard over the full timeline, reveal, reorder, overrides, split/remove/confirm, error states, and an app-level seek/play/reorder flow |
| `SessionsView.test.tsx` | The list, empty state, jobs, merge, and errors |
| `src-tauri/tests/session_e2e.rs` | The real worker and FFmpeg, using only routes the UI may call. Three clips are imported (two cut from one master, repeating 5 s), grouped, and aligned; the overlap is found at about 5000 ms. Reorder and the overrides are checked against the layout contract, and source files are confirmed unchanged. |

M19 adds [event review markers and evidence](./event-review.md), including unique-time mapping while repeated footage is revealed.
