# Fingerprints and duplicate candidates

M06 gives every asset an exact, a fast, a visual, and (when it has audio) an
audio identity.

- **Imports use them** to avoid storing the same bytes twice.
- **Duplicate candidates** report the same content in a different file.
- **Session alignment (M12)** builds on the sampled windows.

Code lives in `services/media-worker/openworld_moments/fingerprints/`:

- `algorithms.py` holds the algorithms and thresholds.
- `service.py` stores fingerprints, compares them, and runs the backfill.

The contract is `fingerprint.schema.json` (`AssetFingerprints`, with `$defs`
`DuplicateCandidate`, `DuplicateEvidence`, `FingerprintRequest`, and
`FingerprintResult`; contracts 1.4).

## Algorithms

Each fingerprint stores its algorithm name and an integer version.

| Kind | Algorithm v1 | What it reads | Size |
|---|---|---|---|
| Exact | SHA-256 of all bytes (M05) | The whole file, streamed in 1 MiB chunks | 64 hex digits |
| Fast | `owm-fast`: SHA-256 over the size (8 bytes, little-endian) plus the first and last MiB | At most 2 MiB | 64 hex digits |
| Frames | `dhash256`: FFmpeg samples **2 frames per second** over the **first and last 30 seconds**; each frame is scaled to 17×16 grayscale (area filter, after automatic rotation) and each row yields 16 bits (is the left pixel brighter than its right neighbour?) | Two bounded decodes | 256 bits per frame, about 120 frames |
| Audio | `energy-envelope`: the first audio stream, mono at 8 kHz, as **10 loudness values per second** in 0.5 dB steps (0 = silence or below -127.5 dBFS, 255 = full scale), over the same windows | Two bounded decodes | About 600 bytes |

Notes:

- **Short assets:** when an asset is shorter than 30 seconds, the head and tail
  windows are the same window.
- **Flat frames:** a frame whose brightest and darkest pixels differ by at most
  8 levels (black, white, fades) is marked `flat` and ignored when comparing.
- **Why 17×16:** a 9×8 (64-bit) hash was tried first and was too coarse. Two
  segments of a mostly static pattern, 10 seconds apart, matched at a mean
  distance of 2.8 bits. At 17×16 the same pair is 34–47 bits apart, while a
  half-bitrate re-encode at double resolution stays within 14.
- **Where fingerprints live:** in `asset_fingerprints`, one row per (asset,
  kind), as small canonical JSON. This is metadata, not media. SHA-256 and the
  fast hash also stay on `media_assets` for indexed lookups.

## Versioning and invalidation

- `fingerprints.service.CURRENT` maps each kind to its current
  `(algorithm, version)`.
- A stored row with a different pair is **stale**. Stale rows stay readable,
  but the backfill recomputes them, and duplicate matching uses only current
  frame fingerprints on both sides.
- Any change to how a fingerprint is computed must bump its version in
  `algorithms.py`.
- Candidates record the matching algorithm (`perceptual-match`) and its version.

## Exact duplicates during import

- **Byte-identical files always resolve to one asset.** `media_assets.sha256`
  is unique, so a renamed copy, or the same file in another folder, is
  reported `existing` (see [import](./import.md)).
- **Fast hash first.** Every import computes the fast hash first (2 MiB).
- **No needless copies.** In managed mode, if an asset with the same fast hash
  and size exists, the source is hashed in place and the copy is skipped when
  the SHA-256 matches. A known file is never copied into staging again. The
  one exception is restoring a lost managed copy, which needs the copy.
- **Collisions are harmless.** Equal fast hashes only suggest identity; the
  full SHA-256 decides. A constructed collision (same size, same first and
  last MiB, different middle) imports as two distinct assets.

## Duplicate candidates

New assets are fingerprinted at the end of the import job (state
`fingerprinting`), and each new asset is compared with every asset of similar
duration.

**A pair becomes a candidate (`perceptual-match` v1) when all of these hold:**

- Durations differ by at most max(1 s, 2%).
- At least **4** informative frame pairs can be compared: head with head and
  tail with tail, in sampling order, skipping flat frames.
- At least **80%** of those pairs match, meaning they differ in at most
  **24 of 256** bits (about 9%).

**Score:** matching ratio × (1 − mean distance / 48). Identical frames score
1.0, and frames at the match limit score 0.5.

**Audio:** when both assets have audio, the evidence also includes
`audio_correlation`, the Pearson correlation of the head envelopes. It
informs review but does not decide.

**What becomes a candidate, and what doesn't:**

| Case | Result |
|---|---|
| Byte-identical, renamed, or moved copy | One asset (`existing`) |
| Remux (same streams, other container) | Candidate, score 1.0 |
| Recompressed (other resolution or bitrate) | Candidate (about 0.88 for a half-bitrate re-encode at double resolution) |
| Similar but different content (same texture, other seed; the same static pattern 10 s later; another test pattern) | Separate, no candidate |
| Replay overlap (A's end repeated at the start of B) | Not a candidate: head is compared with head and tail with tail. Overlap alignment is M12 |

**Candidates are review-safe:**

- **Nothing is merged or deleted, ever.** Both assets and their files stay.
- **The import reports candidates** per item as `candidate_asset_ids` (up to 20).
- **People decide.** `review_state` is `unreviewed` until someone sets
  `duplicate` or `distinct` (`PATCH /v1/duplicates/{id}`).
- **Re-running never overrides a decision.** Recomputing (a new import, the
  backfill, or `force`) refreshes score and evidence but never changes
  `review_state`, and never re-creates a pair as new.
- **Pairs that stop matching** under a newer algorithm version are kept, not
  deleted.

## Backfill job

`POST /v1/fingerprints/backfill`, with body
`{asset_ids?: [...], force?: bool, idempotency_key?}`, starts a job of kind
`fingerprint`, which runs in the `fingerprinting` state.

- **What it computes:** without `force`, only missing or stale fingerprints.
  With `force`, everything for the selected assets.
- **Restartable:** each asset is committed on its own, so a cancelled or
  interrupted job (it is requeued up to 3 attempts) continues with the assets
  still lacking a current fingerprint.
- **Result** (`FingerprintResult`): `considered`, `updated`, `up_to_date`,
  `unavailable` (the source is missing or replaced), `failed` (for example,
  undecodable samples), and `new_candidates`.
- **Requires FFmpeg:** without it the job fails with `tool.ffmpeg_missing`
  (retryable). An import still succeeds without FFmpeg; it stores the fast
  hash only and leaves frames and audio to the backfill.

## API

| Method | Path | Result |
|---|---|---|
| GET | `/v1/assets/{id}/fingerprints` | `AssetFingerprints` |
| GET | `/v1/duplicates?review_state=&asset_id=&limit=&offset=` | `DuplicateCandidate[]`, oldest first |
| GET | `/v1/duplicates/{id}` | `DuplicateCandidate` |
| PATCH | `/v1/duplicates/{id}` | `{review_state}`. Records a decision; never deletes |
| POST | `/v1/fingerprints/backfill` | `Job` (kind `fingerprint`) |

Errors: `asset.not_found` and `duplicate.not_found` (404), and
`job.invalid_params` (422).

## Large files and cost

- **Bounded memory:** hashing reads 1 MiB chunks. A test hashes a 256 MiB
  sparse file with peak Python allocations under 8 MiB.
- **Progress and cancellation:** hashing and copying report bytes, shown as
  "File 3 of 5: 42%" about every 0.5 s, and check for cancellation between
  chunks.
- **Bounded decoding:** at most 60 seconds of the asset is decoded, at reduced
  frame rate and size, with a 180 s timeout per window. Cancellation kills
  FFmpeg.

## Error codes

| Code | When |
|---|---|
| `fingerprint.decode_failed` | FFmpeg could not decode a sampled window (counted as `failed`, never fails an import) |
| `fingerprint.decode_timeout` | A window took longer than 180 s (**retryable**) |
| `tool.ffmpeg_missing`, `tool.ffmpeg_too_old`, `tool.ffmpeg_unusable` | The backfill needs FFmpeg 6.0 or newer (**retryable**) |
| `duplicate.not_found` | Unknown candidate ID |
