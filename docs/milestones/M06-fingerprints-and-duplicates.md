# M06 — Fingerprints and duplicate detection

## Objective

Give every asset exact, fast, visual, and optional audio identity so imports can detect duplicates and later milestones can align sessions.

## Dependencies

M05 merged.

## Required context

Read specification sections 8.1.4, 8.2.3, and Epic C.

## In scope

- SHA-256 exact hash.
- Fast partial fingerprint for screening.
- Sampled-frame perceptual hashes with timestamps.
- Optional compact audio fingerprint suitable for overlap candidates.
- Duplicate-candidate records and review-safe behavior.
- Hash backfill job for existing assets.

## Out of scope

- Automatic deletion, full overlap alignment, and semantic embeddings.

## Implementation steps

1. Define fingerprint version metadata and invalidation rules.
2. Stream exact/partial hashes without loading whole files into memory.
3. Decode bounded analysis frames and compute perceptual hashes.
4. Compute an audio fingerprint only when an audio stream exists.
5. Integrate exact duplicate prevention into M05.
6. Surface perceptual candidates without collapsing assets automatically.
7. Add performance and collision fixtures.

## Acceptance criteria

- Byte-identical files resolve to one canonical asset.
- Same-content remuxes become perceptual candidates, not automatic duplicates.
- Similar but distinct synthetic clips remain separate.
- Fingerprint algorithm version is persisted.
- Hashing is cancellable and reports progress for large files.
- No duplicate workflow deletes media.

## Required validation

- Exact duplicate, renamed duplicate, remux, recompressed, and near-match tests.
- Memory-usage smoke test on a large sparse fixture.
- Backfill restart test.

## Handoff

Document algorithms, sampling frequency, thresholds, versioning, and candidate semantics. Update M06.

