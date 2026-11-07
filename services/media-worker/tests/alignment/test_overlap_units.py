# SPDX-License-Identifier: AGPL-3.0-or-later
"""owm-overlap on synthetic fingerprints (M12): exact, noisy, partial, ambiguous,
isolated, flat, implausible, audio refinement, and speed/memory."""

from __future__ import annotations

import random
import time
import tracemalloc

import pytest

from openworld_moments.alignment.overlap import (
    APPLY_CONFIDENCE,
    Frame,
    Side,
    align,
    candidates,
    verify,
)
from openworld_moments.sessions.grouping import AssetFacts, layout


class Footage:
    """A deterministic 'master recording': one random 256-bit hash every 500 ms."""

    def __init__(self, seed: int, length_ms: int = 120_000) -> None:
        rng = random.Random(seed)  # noqa: S311 - deterministic test data
        self.rng = rng
        self.frames = {t: rng.getrandbits(256) for t in range(0, length_ms, 500)}

    def noisy(self, value: int, bits: int) -> int:
        for _ in range(bits):
            value ^= 1 << self.rng.randrange(256)
        return value

    def tail(self, start_ms: int, duration_ms: int, *, noise: int = 0) -> Side:
        """Tail window (last 30 s) of a clip cut from the master at ``start_ms``."""
        window = max(0, duration_ms - 30_000)
        frames = tuple(
            Frame(t, self.noisy(self.frames[start_ms + t], noise))
            for t in range(window, duration_ms, 500)
        )
        return Side(duration_ms, frames, window)

    def head(self, start_ms: int, duration_ms: int, *, noise: int = 0) -> Side:
        frames = tuple(
            Frame(t, self.noisy(self.frames[start_ms + t], noise))
            for t in range(0, min(30_000, duration_ms), 500)
        )
        return Side(duration_ms, frames, 0)


def test_exact_overlap() -> None:
    master = Footage(1)
    a = master.tail(0, 40_000)
    b = master.head(30_000, 40_000)  # B starts 30 s into A: 10 s repeated
    result = align(a, b)
    assert result.status == "matched" and result.applied
    assert result.offset_ms == 30_000 and result.overlap_ms == 10_000
    assert result.confidence is not None and result.confidence >= 0.9
    assert result.evidence["longest_run"] == 20


@pytest.mark.parametrize("bits", [5, 15, 20])
def test_recompression_noise_within_match_distance(bits: int) -> None:
    master = Footage(2)
    result = align(master.tail(0, 40_000), master.head(30_000, 40_000, noise=bits))
    assert result.status == "matched" and result.offset_ms == 30_000


@pytest.mark.parametrize("overlap_s", [3, 8, 15, 29])
def test_overlap_lengths_within_the_window(overlap_s: int) -> None:
    master = Footage(3)
    start = 40_000 - overlap_s * 1000
    result = align(master.tail(0, 40_000), master.head(start, 40_000))
    assert result.status == "matched"
    assert result.overlap_ms == overlap_s * 1000


def test_unrelated_clips_do_not_match() -> None:
    result = align(Footage(4).tail(0, 40_000), Footage(5).head(0, 40_000))
    assert result.status == "no_match" and not result.applied


def test_isolated_similar_frames_are_rejected() -> None:
    master, other = Footage(6), Footage(7)
    a = master.tail(0, 40_000)
    frames = list(other.head(0, 40_000).frames)
    # Two scattered frames of B happen to look like frames near the end of A.
    frames[0] = Frame(0, master.frames[33_000])
    frames[5] = Frame(2500, master.frames[36_500])
    b = Side(40_000, tuple(frames), 0)
    result = align(a, b)
    assert result.status == "no_match"
    assert result.evidence["reason"] == "no_continuous_match"


def test_repeating_menu_is_ambiguous_not_confident() -> None:
    master, other = Footage(8), Footage(9)
    menu = master.rng.getrandbits(256)
    a_frames = tuple(
        Frame(t, menu if t >= 32_000 else master.frames[t]) for t in range(10_000, 40_000, 500)
    )
    b_frames = tuple(Frame(t, menu if t < 8000 else other.frames[t]) for t in range(0, 30_000, 500))
    result = align(Side(40_000, a_frames, 10_000), Side(40_000, b_frames, 0))
    assert result.status == "ambiguous" and not result.applied
    assert result.evidence["reason"] == "repeating_footage"


def test_flat_frames_are_ignored() -> None:
    master = Footage(10)
    a = master.tail(0, 40_000)
    # B opens with black (flat frames are dropped when parsed) then real overlap.
    b = Side.head(
        40_000,
        {
            "head": [
                {"t_ms": t, "hash": "0" * 64, "flat": True}
                if t < 2000
                else {"t_ms": t, "hash": f"{master.frames[30_000 + t]:064x}"}
                for t in range(0, 30_000, 500)
            ]
        },
        None,
    )
    assert all(f.t_ms >= 2000 for f in b.frames)
    result = align(a, b)
    assert result.status == "matched" and result.offset_ms == 30_000


def test_offsets_outside_the_tail_are_not_candidates() -> None:
    master = Footage(11)
    a = master.tail(0, 40_000)
    # B equals A's tail shifted so that its start would fall before A's window.
    b = master.head(5_000, 40_000)
    assert all(bin_ * 500 >= 10_000 - 500 for bin_ in candidates(a, b))


def test_too_few_frames_is_insufficient() -> None:
    master = Footage(12)
    a = master.tail(0, 40_000)
    b = Side(1000, a.frames[:2], 0)
    assert align(a, b).status == "insufficient"


def test_verify_counts_runs() -> None:
    master = Footage(13)
    check = verify(master.tail(0, 40_000), master.head(30_000, 40_000), 30_000)
    assert (check.compared, check.matched, check.longest_run) == (20, 20, 20)
    assert check.verified


def _envelope(seed: int, length: int) -> list[int]:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    return [rng.randrange(60, 200) for _ in range(length)]


def test_audio_refines_the_visual_offset() -> None:
    master = Footage(14)
    a = master.tail(0, 40_000)
    b = master.head(30_000, 40_000)
    env = _envelope(15, 700)  # 70 s of 10 Hz loudness on the master timeline
    true_offset = 30_200  # B really starts 200 ms later than the frame grid says
    a_env = tuple(env[100:400])  # A's tail window: 10 s .. 40 s
    b_env = tuple(env[true_offset // 100 : true_offset // 100 + 300])
    a_audio = Side(a.duration_ms, a.frames, a.window_start_ms, a_env, 10_000)
    b_audio = Side(b.duration_ms, b.frames, 0, b_env, 0)
    result = align(a_audio, b_audio)
    assert result.status == "matched"
    assert result.offset_ms == true_offset
    assert result.evidence["visual_offset_ms"] == 30_000
    assert result.evidence["audio_correlation"] > 0.99


def test_audio_that_disagrees_is_ignored() -> None:
    master = Footage(16)
    a = master.tail(0, 40_000)
    b = master.head(30_000, 40_000)
    a_audio = Side(a.duration_ms, a.frames, 10_000, tuple(_envelope(1, 300)), 10_000)
    b_audio = Side(b.duration_ms, b.frames, 0, tuple(_envelope(2, 300)), 0)
    result = align(a_audio, b_audio)
    assert result.status == "matched" and result.offset_ms == 30_000
    assert "audio_correlation" not in result.evidence


def test_weak_matches_are_found_but_not_applied() -> None:
    master = Footage(17)
    # A 2 s overlap: exactly the minimum run, so the match is real but weak.
    result = align(master.tail(0, 40_000), master.head(38_000, 40_000))
    assert result.status == "weak" and not result.applied
    assert result.offset_ms == 38_000
    assert result.confidence is not None and result.confidence < APPLY_CONFIDENCE


def test_layout_applies_overlaps() -> None:
    def facts(asset_id: str, minute: int) -> AssetFacts:
        return AssetFacts(
            id=asset_id,
            source_key="xbox",
            captured_at=f"2026-11-20T03:{minute:02d}:00.000Z",
            capture_confidence=0.9,
            duration_ms=60_000,
            created_at="2026-11-21T09:00:00Z",
        )

    class Known:
        overlap_ms = 15_000
        confidence = 0.9

    assets = [facts("a", 0), facts("b", 1), facts("c", 5)]
    placed = layout(assets, overlaps={("a", "b"): Known()})
    assert [p.start_ms for p in placed] == [0, 45_000, 300_000]
    assert [p.overlap_with_previous_ms for p in placed] == [0, 15_000, 0]
    assert placed[1].alignment_confidence == 0.9


def test_speed_and_memory() -> None:
    """Budget: 200 pairs of full 30 s windows in well under a second each, bounded memory."""
    pairs = []
    for seed in range(200):
        master = Footage(1000 + seed, length_ms=80_000)
        pairs.append((master.tail(0, 40_000), master.head(30_000, 40_000)))
    tracemalloc.start()
    started = time.perf_counter()
    results = [align(a, b) for a, b in pairs]
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert all(r.status == "matched" for r in results)
    assert elapsed / len(pairs) < 0.05, f"{elapsed / len(pairs) * 1000:.1f} ms per pair"
    assert peak < 20 * 1024 * 1024, f"peak {peak / 1e6:.1f} MB"
