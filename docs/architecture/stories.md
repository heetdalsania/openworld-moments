# Story engine (M20)

`owm-story` **1.0.0** proposes explainable, non-destructive edit windows in M13
unique session time. It reads current M19 effective decisions and M18 source-word
coordinates. It never runs a detector, transcriber, model, network request or media
process. A candidate is a draft; only explicit acceptance creates a Project/Story.
Final editing, manual editor workflows, autosave and undo are M21/M22.

## Input and seed policy

A consistent SQLite snapshot binds ordered members, applied overlaps, current
immutable observations plus decision revisions, source transcript timings/text
hashes, effective options and generator version into `input_key`. Layout identity
uses the same M19 hash. The snapshot has no transcript text beyond the temporary
punctuation parse; candidates/reports contain no text, filenames or private paths.

Only current observations with a proven layout are eligible. Stale, superseded
and legacy observations cannot seed or support generation. Rejected events cannot
seed; an overlapping rejection contributes a visible penalty. A seed is:

- a confirmed/corrected event, including a user-created event; or
- an unreviewed **detector** event with confidence at least **0.90**, unless
  `allow_unreviewed` is false. An unreviewed model suggestion never seeds.

Audio-features observations, original audio/silence/speech types, and evidence
marked supporting stay supporting-only even after relabeling. Subtitle, dialogue,
silence and explicit scene-boundary/cut events also cannot seed. Empty, rejected,
legacy or audio-only sessions produce zero automatic candidates. The generator
never blocks independent manual Project/Story creation downstream.

## Stages and presets

1. Sort seeds by start/end/ID. Add configured pre/post roll. Merge overlapping
   windows, or nearby wanted-to-wanted / mission-to-mission events within the
   causal-gap setting. This is a declared temporal/type heuristic, not inferred
   knowledge of gameplay causality.
2. Clamp to available session footage and prefer the preset's minimum length.
   Under maximum-duration pressure, anchor on the last explicit payoff, otherwise
   the strongest event (earliest on ties). Preserve the anchor where it fits;
   expose omitted/truncated seed context through references, warnings and score.
3. Expand cut boundaries to complete speech spans when the maximum duration
   permits. Try a shift preserving retained seeds if expansion alone does not fit.
   An impossible cut is marked `speech_truncated`; no extra footage is fabricated.
4. Prefer a silence midpoint or explicit scene boundary within **2 s outward** of
   a cut, only if it preserves context, speech and the maximum duration. No new
   scene detector is introduced; absent scene observations are simply unavailable.
5. Generate short/long context alternatives with **0.5× / 1.5×** roll, applying
   the same constraints. Suppress duplicate alternatives or an alternative that
   goes against its duration preference. Minimum lengths can give equal-duration
   alternatives with different boundaries; constrained footage can give none.
6. Coalesce neighboring candidate groups whose final windows overlap, regenerating
   their union under the same duration constraints. Output windows never replay
   the same unique session time twice.
7. Map every half-open window to ordered source ranges, skipping each later
   clip's applied hidden prefix. EDL timeline positions are contiguous. The sum
   of source lengths equals the candidate length, with no repeated source range.

| Preset | Min–max | Default pre | Default post | Causal gap |
|---|---:|---:|---:|---:|
| `moment` | 10–25 s | 4 s | 4 s | 3 s |
| `short` | 25–60 s | 10 s | 8 s | 10 s |
| `extended_short` | 60–180 s | 15 s | 12 s | 20 s |
| `highlight` | 30–120 s | 12 s | 10 s | 15 s |

Pre/post roll accept 0–60 s and causal gap 0–30 s. The maximum is hard. The
minimum is a preference when the session or complete speech leaves less footage;
`below_minimum` is explicit. Compilation remains a user-defined downstream editing
workflow, not an automatic cross-session generator in M20.

## Transcript and supporting boundaries

M18's stored session offsets can become stale after session changes. M20 maps
`source_start_ms`/`source_end_ms` through current membership and hidden overlap.
It discards hidden duplicates, missing members and invalid/out-of-source spans.
Words are sorted in current unique time, joined until punctuation (`.?!。？！`) or
an inter-word gap above **1.5 s**, and can span adjacent clips. A segment without
words is preserved as one utterance. Overlapping speaker spans are unioned, so a
cut cannot preserve one voice while truncating another. No transcript is rebuilt
or altered, and no recognition engine is required.

M18 recognition quality is still unqualified by a real whisper.cpp run. Punctuation
and pauses are timing heuristics, not a general linguistic sentence parser.
Scene hints require an explicit current reviewed/high-confidence scene event;
silence can also come from current supporting audio evidence. There is no visual
scene inference from nonexistent metadata.

## Beats and score

- `setup`: actual available pre-first-seed context, explicitly labelled context.
- `incident`: a retained generic event or initial wanted change.
- `escalation`: a positive wanted level increasing from another positive level.
- `payoff`: explicit death, arrest, mission completion/failure, crash, escape, or
  wanted dropping from positive to zero. Other labels are not invented.
- `reaction`: post-payoff timed speech or supporting audio. Its basis says
  `transcript`/`audio`; it means reaction-supporting timing, not an inferred emotion,
  person or laugh. Silence itself never receives a reaction bonus.

`source_events` stores exact IDs, revisions, effective labels, full intervals,
review states and confidence. It includes pressure-omitted seeds so lost setup
and truncation are auditable. Beats identify their relevant event IDs and times.
Source ranges provide exact asset in/out and unique session positions for both
the main and alternative boundaries.

The score is the sum below, rounded to six decimals. Every component is returned;
no opaque or engagement score is introduced.

| Component | Rule / weight |
|---|---|
| `event_confidence` | 0.25 × mean original confidence of retained seed events |
| `setup_coverage` | 0.15 × min(1, available pre-first-seed context / max(1, requested pre-roll)) |
| `payoff_coverage` | +0.20 if an explicit payoff is wholly retained |
| `reaction_evidence` | +0.10 if post-payoff speech/audio support exists |
| `continuity_score` | +0.30 for the contiguous unique-time window |
| `duplicate_penalty` | 0: duplicate ranges are structurally prohibited |
| `dead_air_penalty` | −0.15 × union of retained non-rejected silence / window duration |
| `truncation_penalty` | −0.25 if a speech span or cluster seed is cut/omitted |
| `spoiler_risk_penalty` | −0.10 if enabled and a retained seed has a spoiler flag |
| `rejection_penalty` | −0.20 if a rejected event intersects the window |
| `missing_payoff_penalty` | −0.10 if no explicit payoff is wholly retained |

Coverage metrics expose the unweighted setup fraction, explicit payoff presence,
speech truncation count and duplicate milliseconds. Scores reward edit completeness
and evidence under these rules; they do not establish gameplay quality or predict
publishing performance. No-payoff candidates remain inspectable with a warning.

## Persistence, regeneration and acceptance

Migration **0013** adds `story_candidates` (immutable documents),
`story_decisions` (append-only revisions), `story_generations` (current cache keys,
including empty results), and the cancellable `story` job kind. Original events,
transcripts and source files are not changed. Archived candidates count as attached
session data during regrouping/merge guards.

Candidate and segment IDs are deterministic 128-bit hashes encoded in the existing
`prj_`/`seg_` Crockford shape; their suffix is an opaque identity, **not a creation
timestamp**. No wall clock enters candidate bytes. Reads are contract validated.

Generation snapshots, computes outside the write transaction, then rechecks the
entire input key inside the atomic commit. A concurrent event/review/transcript/
layout change fails with `story.inputs_changed`; nothing partial is committed.
Cancellation is checked through snapshot, generation and insert loops and just
before commit. Completed prior generations survive failures/cancellation. Crash
retries reuse the completed marker or deterministic candidate IDs.

A force run never overwrites a candidate or decision. The same inputs yield the
same IDs and documents. A generator/version, review, observation identity,
transcript, layout, preset or option change yields a new input identity; old
candidates remain inspectable with `current: false`. Rejected candidates stay
hidden by default and stay rejected on an identical rerun. Changed evidence or a
new generator produces fresh suggestions requiring independent review; no approval
or rejection is silently transferred to new IDs.

Decision requests carry `input_key` and expected revision. Acceptance rechecks
freshness and creates the existing Story/Project EDL once, with `fit` crops, no
captions/overlays, unchanged gain, exact source ranges and generic editable title.
It accepts the main window; alternative ranges remain explicit metadata for the
downstream editor. It never starts rendering or publishing. Rejection or restore-to-suggested appends
a revision and soft-updates a previously accepted Story's review state, retaining
its EDL. If the project is marked `edited`, candidate review refuses to change it;
manage that project through the downstream editor. Regeneration never modifies
an accepted or edited project.

## Interfaces and bounds

- `POST /v1/sessions/{id}/stories`: story options plus optional idempotency key;
  returns a cancellable durable job, using the existing job center.
- `GET /v1/sessions/{id}/stories`: same effective options as query parameters,
  plus `include_history`, `offset`, `limit` (default 50, max 100). Custom-roll
  generations are listed using those same settings; omitting them lists defaults.
- `POST /v1/sessions/{id}/stories/{candidateId}/decision`: state `accepted`,
  `rejected` or `suggested`, candidate input key and expected revision.

All routes retain worker token/loopback guards and the host's closed allowlist.
No new media protocol or UI editing surface is added.

Inputs are bounded to **1,000 members**, **5,000 current events**, **10,000 transcript
rows**, **50,000 words**, **1,000 candidates** and **50,000 total candidate event
references**. Oversized work fails with an actionable split-session message rather
than silently truncating results. API/CLI reject unknown or invalid options. CLI
requires an existing explicitly chosen library and prints safe errors.

See the [CLI and synthetic coverage guide](../stories/README.md). Future M21/M22
must keep manual creation independent, preserve source references and edited
projects, and visibly distinguish stale candidate history from current evidence.
