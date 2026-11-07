# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from types import MappingProxyType

import pytest

from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisContext, AnalysisError
from openworld_moments.detectors.wanted import Observation, TemporalState, WantedState, estimate
from openworld_moments.detectors.wanted_fixtures import DEFAULT_REGION, fixture_frame


def context(levels: Sequence[int | None], **settings: object) -> AnalysisContext:
    frames = tuple(
        fixture_frame(level or 0, i * 500, pattern="absent" if level is None else "normal")
        for i, level in enumerate(levels)
    )
    return AnalysisContext(
        "ast-fixture",
        len(frames) * 500,
        frames,
        MappingProxyType({"wanted_indicator": DEFAULT_REGION}),
        MappingProxyType(settings),
        MappingProxyType({}),
        lambda: None,
        lambda *_: None,
    )


@pytest.mark.parametrize("shape", ["star", "disc"])
@pytest.mark.parametrize("maximum,level", [(m, n) for m in (1, 3, 5, 10) for n in range(m + 1)])
@pytest.mark.parametrize("brightness", [0.55, 0.8, 1])
def test_known_state_brightness_and_shapes(
    maximum: int, level: int, shape: str, brightness: float
) -> None:
    o = estimate(
        fixture_frame(level, maximum=maximum, shape=shape, brightness=brightness),
        maximum=maximum,
        shape=shape,
    )
    assert o.level == level and 0.8 <= o.confidence <= 1


@pytest.mark.parametrize("maximum", [1, 3, 5, 10])
def test_zero_and_maximum(maximum: int) -> None:
    for level in (0, maximum):
        assert estimate(fixture_frame(level, maximum=maximum), maximum=maximum).level == level


@pytest.mark.parametrize("pattern", ["absent", "rectangles", "nonprefix", "ambiguous"])
def test_false_patterns_are_unknown(pattern: str) -> None:
    assert estimate(fixture_frame(2, pattern=pattern)).level is None
    assert estimate(fixture_frame(2, shape="disc"), shape="star").level is None


def test_transitions_confirm_once_and_clear_zero() -> None:
    events = list(WantedState().detect(context([0] * 3 + [2] * 4 + [5] * 4 + [0] * 4)))
    assert [(e.attributes["from"], e.attributes["to"]) for e in events] == [(0, 2), (2, 5), (5, 0)]
    assert [(e.start_ms, e.attributes["confirmed_at_ms"]) for e in events] == [
        (1500, 2500),
        (3500, 4500),
        (5500, 6500),
    ]
    assert all(
        0.8 <= e.confidence <= 1 and e.evidence[0]["frame_ms"] == e.attributes["confirmed_at_ms"]
        for e in events
    )
    assert all("pixels" not in str(e.evidence) and "path" not in str(e.evidence) for e in events)


def test_flicker_occlusion_and_ambiguous_frames_do_not_invent_changes() -> None:
    assert list(WantedState().detect(context([0] * 3 + [2, 0, 2, 0, None, 0, 2, 0]))) == []
    events = list(WantedState().detect(context([0] * 3 + [2, None, 2, 2] + [None] + [2] * 3)))
    assert len(events) == 1 and events[0].attributes["to"] == 2
    assert events[0].evidence[1]["frames"] == 3
    assert events[0].evidence[1]["score"] < 1


def test_sustained_missing_loses_baseline_and_reacquires_without_false_transition() -> None:
    assert list(WantedState().detect(context([2] * 3 + [None] * 3 + [0] * 3))) == []
    events = list(WantedState().detect(context([2] * 3 + [0] * 3)))
    assert len(events) == 1 and events[0].attributes["to"] == 0


def test_debounce_requires_current_confirmed_state_and_never_emits_a_stale_candidate() -> None:
    s = TemporalState(confirmation=2, debounce=2500)
    levels = [0, 0, 2, 2, 0, 0, 2, 2, 0, 0]
    changes = [
        s.observe(i * 500, Observation(level, 0.95, "test")) for i, level in enumerate(levels)
    ]
    assert [(e.previous, e.level, e.confirmed_ms) for e in changes if e] == [
        (0, 2, 1500),
        (2, 0, 4500),
    ]


def test_time_gap_low_confidence_and_bad_sample_fail_closed() -> None:
    s = TemporalState(confirmation=2)
    for t in (0, 500):
        s.observe(t, Observation(2, 0.95, "test"))
    assert s.observe(2000, Observation(0, 0.95, "test")) is None and s.stable is None
    assert s.observe(2500, Observation(0, 0.2, "weak")) is None
    with pytest.raises(AnalysisError):
        s.observe(2500, Observation(0, 0.95, "test"))
    with pytest.raises(AnalysisError):
        estimate(replace(fixture_frame(1), pixels=b""))
    c = context([0] * 3 + [2] * 3)
    with pytest.raises(AnalysisError):
        list(WantedState().detect(replace(c, frames=(replace(c.frames[0], region=None),))))


def test_cancellation_and_trace_have_no_media() -> None:
    c = context([0] * 3 + [2] * 3)

    def stop() -> None:
        raise AnalysisCancelled

    with pytest.raises(AnalysisCancelled):
        list(WantedState().detect(replace(c, check_cancelled=stop)))
    rows = list(WantedState().replay(c))
    assert len(rows) == 6 and rows[-1][0]["transition"]["to"] == 2
    assert rows[-1][0]["stable"] == 2
    assert "pixels" not in str(rows[0][0])


def test_candidate_recovers_after_early_misses_while_debounced() -> None:
    state = TemporalState(confirmation=2, missing=1, debounce=10000)
    values = [0, 0, 2, 2, 0, None, 0, None, 0, None] + [0] * 20
    changes = [
        state.observe(
            i * 500,
            Observation(v, 0.95, "test") if v is not None else Observation(None, 0, "missing"),
        )
        for i, v in enumerate(values)
    ]
    assert [(c.previous, c.level) for c in changes if c] == [(0, 2), (2, 0)]
    assert changes[-1] is None and state.stable == 0


def test_detail_guard_uses_proxy_resolution_not_4k_source() -> None:
    from openworld_moments.detectors.inputs import require_roi_detail

    with pytest.raises(AnalysisError, match="crop is too small"):
        require_roi_detail(3840, 2160, (0, 0, 0.025, 0.05), 5)
    require_roi_detail(3840, 2160, DEFAULT_REGION, 5)
