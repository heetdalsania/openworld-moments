# M12 — Visual and audio overlap alignment

## Objective

Detect and refine repeated footage between adjacent session assets so the application can construct a unique virtual timeline without deleting originals.

## Dependencies

M08 and M11 merged.

## Required context

Read specification section 8.2.3 and M06 fingerprint behavior.

## In scope

- Candidate search over bounded head/tail windows.
- Perceptual-hash sequence alignment.
- Verification through sequential consistency.
- Optional audio cross-correlation refinement.
- Overlap duration, offset, confidence, and evidence persistence.
- Conservative no-match behavior and manual override API.

## Out of scope

- General video synchronization, arbitrary multi-camera alignment, and destructive deduplication.

## Implementation steps

1. Define alignment result contract and algorithm version.
2. Implement candidate matches from sampled fingerprints.
3. Verify monotonic sequences and reject isolated similar frames.
4. Refine time offset with audio when available.
5. Add compression, black-frame, menu, and repeated-scene adversarial fixtures.
6. Persist result and expose recompute/override operations.
7. Benchmark speed and memory.

## Acceptance criteria

- Known overlaps align within 500 ms in the fixture suite.
- Similar menus without continuous matching do not become high-confidence overlaps.
- Audio-less clips still align visually where evidence is sufficient.
- Low confidence leaves both timelines intact.
- Manual override wins over automatic recomputation.
- Source assets remain untouched.

## Required validation

- Exact, recompressed, audio-shifted, silent, repeated-scene, and no-overlap tests.
- Cancellation and performance test.
- Algorithm-version invalidation test.

## Handoff

Document windows, sampling rate, thresholds, confidence, performance, and known adversarial cases. Update M12.

