# Overlap alignment (repeated footage between clips)

Console replay captures often repeat footage: clip B begins with what the end of
clip A already showed. M12 finds that repeat between adjacent clips of a session.
It records where B starts inside A and how long the repeat is, so the virtual
session timeline (M13) can hide duplicated time.

Originals are never touched. Nothing is cut, re-encoded, deleted, or rewritten.
Only database rows describe the overlap, and a low-confidence result changes
nothing.

Code: `services/media-worker/openworld_moments/alignment/`

- `overlap.py`: the algorithm, pure functions.
- `service.py`: the job, caching, overrides, and documents.

Shared layout: `sessions/grouping.py::layout`.

Also:

- **Contract:** `overlap.schema.json`, plus member fields in
  `session.schema.json` (contracts 1.8).
- **Migration:** 0009 (`asset_overlaps`).
- **Job:** `align`.

## Inputs: windows and sampling

Alignment uses the M06 fingerprints, computed on demand if missing or stale:

| Signal | Window | Rate | Use |
|---|---|---|---|
| `dhash256` frame hashes (256 bits, flat frames flagged) | First and last 30 s of each clip | 2 per second (500 ms) | Candidate search and verification |
| `energy-envelope` loudness | Same windows | 10 per second (100 ms) | Refining the offset |

For a pair (A, B), A's **tail** window is compared with B's **head** window.
Overlaps are therefore found when they are at least about 2 s long (the minimum
run below) and at most 30 s long (the window). Longer repeats are a known
limitation; see the end.

## Algorithm `owm-overlap`, version 1

1. **Candidates.** Every pair of non-flat frames (one from A's tail, one from
   B's head) within **24 bits** Hamming distance votes for an offset `d`, the
   time in A where B's time 0 falls, in 500 ms bins. Offsets that would not put
   B's start inside A's tail, or that make the overlap longer than either clip,
   are dropped.
2. **Verification.** For each of the **5** best-voted offsets, B's head frames
   are walked in order and compared with A's frame at the same moment (`t_B +
   d`, nearest sample within 250 ms). A candidate is *verified* when it has:
   - at least **4** compared frames,
   - at least **80%** of them matching,
   - an unbroken run of at least **4** matching samples (2 s).

   This rejects isolated look-alike frames.
3. **Ambiguity.** If another verified offset more than one bin away has at least
   **80%** as many matches, the footage repeats itself (menus, static scenes,
   loading screens). The result is `ambiguous` and is never applied.
4. **Refinement.**
   - **Visual:** `d` becomes the median of `t_A − t_B` over the matched samples,
     accurate to about 250 ms.
   - **Audio:** with envelopes on both sides, the envelopes are cross-correlated
     at lags `d ± 1 s` in 100 ms steps, over at least 2 s of overlap. A Pearson
     correlation of **0.7 or more** moves `d` to that lag (about 100 ms
     accuracy) and adds confidence. Weaker audio is ignored, and the visual
     offset stands.

### Confidence and status

```text
confidence = matching ratio × min(1, longest run / 8)   (+0.10 when audio agrees)
             capped at 0.95
```

| Status | Meaning | Applied to the timeline? |
|---|---|---|
| `matched` | Verified, unambiguous, confidence ≥ **0.6** | Yes |
| `weak` | Verified but below 0.6 (for example a 2 s repeat: run 4/8 = 0.5) | No |
| `ambiguous` | Several offsets fit: repeating footage | No |
| `no_match` | No candidates, or none continuous | No |
| `insufficient` | Fewer than 4 usable frames on a side, or no fingerprints (source missing) | No |
| `pending` | Not computed yet (a row created by an override) | No |

**Conservative by design:** anything other than `matched` leaves both clips
whole, and their capture-time placement (M11) stands.

## Persistence and the timeline

- **One stored result per ordered pair:** `asset_overlaps` holds `(A, B)` with
  status, offset, overlap, confidence, evidence (vote counts, compared and
  matching frames, longest run, visual and audio offsets, reason), and the
  algorithm and version.
- **Stale results are never applied:** a result from another version is stale.
  The next `align` run recomputes it, and until then it applies nothing.
- **What applies:** the user override, else a current `matched` result, else
  nothing (`OverlapRepository.effective`).
- **One shared layout:** `grouping.layout` is the single function that positions
  clips. M11 grouping and corrections, and M12 alignment and overrides, all use
  it.
  - When an overlap applies, B's `session_start_ms` is A's start plus
    `duration(A) − overlap`. The member records `overlap_with_previous_ms` and
    `alignment_confidence` (1.0 for an override).
  - Otherwise the M11 placement is kept.
- **Regrouping is stable:** an unchanged session stays unchanged after
  alignment (tested).

## The `align` job

`POST /v1/sessions/align` (`AlignRequest`: `session_ids?`, `force?`,
`idempotency_key?`) does the following:

1. **Collect** the adjacent pairs of the chosen sessions (default: all).
2. **Reuse or compute:** current results are cache hits. Otherwise the pair gets
   current fingerprints and is aligned.
3. **Commit pair by pair:** each result is committed on its own, so a
   cancelled or interrupted job resumes where it stopped.
4. **Lay sessions out** again.

The result (`AlignResult`) counts:

- pairs considered, computed, and cached;
- fingerprints computed and sessions updated;
- each status.

Cancellation is checked between pairs and during fingerprinting.

## Manual override

`PUT /v1/sessions/{id}/overlaps/{asset_id}` with `{"overlap_ms": N}` sets the
overlap between that clip and the clip before it:

- `0` means "these do not overlap";
- `null` clears the override.

Overrides:

- **must be between 0 and the shorter clip's duration;**
- are **always applied** and **survive every recomputation**, forced or not;
- are logged in the session's correction log (`overlap`).

`GET /v1/sessions/{id}/overlaps` lists every adjacent pair as an `AssetOverlap`:

- the automatic result and whether it is current;
- the override, if any;
- what is applied.

## Performance

**Alignment itself is cheap:** two 60-frame windows give at most 3,600 hash
comparisons plus up to 5 verifications. The test budget is 200 pairs at under
50 ms each with a peak of under 20 MB (`test_speed_and_memory`). It runs at
about 1–2 ms per pair on a laptop.

**End to end, the cost is dominated by fingerprinting.** That is a bounded
FFmpeg decode of two 30 s windows per clip (M06), about 0.5–1.3 s per new pair
for 40 s synthetic clips. Each clip is fingerprinted once and each pair aligned
once per algorithm version.

## Fixture results

The suite is in `tests/media/test_alignment.py`. Clips are synthetic: Game of
Life video and a quasi-periodic tone, cut so that B repeats A's last 10 s
(true offset 30 000 ms).

| Case | Result |
|---|---|
| Exact | `matched`, offset 30 000 ms, confidence 0.95, 20/20 frames, audio correlation 0.98 |
| Recompressed (CRF 38, downscaled and upscaled) | `matched`, 30 000 ms, 19/20 frames |
| Audio 300 ms late | `matched`, 30 000 ms. The shifted audio is not trusted, and the visual offset stands |
| Silent | `matched`, 30 000 ms, visual only |
| Repeated menu (A ends and D starts on the same static bars) | `ambiguous`, not applied |
| No overlap | `no_match`, not applied |

## Known adversarial cases

- **Static menus, loading screens, pause screens:** these match at many offsets
  and come out `ambiguous`. A real overlap that *also* contains a long static
  section can be rejected for the same reason. Use the override.
- **Repeated content** (looping cutscenes, identical laps): the same as above.
- **Fades and black frames:** flat frames are ignored. An overlap that is mostly
  black lacks evidence (`insufficient` or `no_match`).
- **Heavy recompression or scaling:** tolerated within 24 of 256 bits per frame.
  Different crops or HUD overlays (for example a streamer overlay on one copy
  only) can break matching.
- **Overlaps longer than 30 s:** only the last 30 s of A and the first 30 s of B
  are compared, so a longer repeat is detected as at most 30 s (the window).
  Detecting longer repeats needs wider fingerprint windows.
- **Audio-only evidence:** never enough on its own. Audio only refines a
  verified visual match.
