# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic audio features (M18) on synthetic signals: tone, impact, silence,
speech-like activity, no audio, boundaries and cancellation. Timing tolerances are
the documented ones: impacts ±20 ms, interval boundaries ±150 ms."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from openworld_moments_contracts import load

from openworld_moments.detectors.audio import (
    AudioFeatures,
    envelope,
    features,
    hop_energies,
    level_db,
)
from openworld_moments.detectors.audio_fixtures import (
    add_impact,
    noise_floor,
    samples,
    silence,
    speech_band,
    speech_like,
    tone,
)
from openworld_moments.detectors.audio_input import SAMPLE_RATE, split_channels, track_policy
from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisContext, AudioSamples

IMPACT_TOLERANCE_MS = 20
BOUNDARY_TOLERANCE_MS = 150


def kinds(found: list) -> list[str]:  # type: ignore[type-arg]
    return [f.kind for f in found]


def context(audio: AudioSamples | None, duration_ms: int, cancel=None) -> AnalysisContext:  # type: ignore[no-untyped-def]
    return AnalysisContext(
        "ast_01JCBQ00000000000000000001",
        duration_ms,
        (),
        MappingProxyType({}),
        MappingProxyType({"id": "audio-features", "enabled": True}),
        MappingProxyType({}),
        cancel or (lambda: None),
        lambda *_: None,
        audio,
    )


def test_levels_are_dbfs_with_a_floor() -> None:
    assert level_db(0) == -160.0
    assert level_db(32768.0**2) == pytest.approx(0.0)
    full_scale_sine = samples(tone(1, amplitude=1.0))
    blocks = envelope(hop_energies(full_scale_sine.full, SAMPLE_RATE, lambda: None))
    assert all(b == pytest.approx(-3.01, abs=0.05) for b in blocks)


def test_steady_tone_is_neither_silence_nor_speech_nor_an_onset() -> None:
    assert features(samples(tone(5, 440, 0.5)), 5000) == []
    assert features(samples(tone(5, 1000, 0.1)), 5000) == []


def test_digital_silence_is_one_confident_silence_interval() -> None:
    found = features(samples(silence(4)), 4000)
    assert [(f.kind, f.start_ms, f.end_ms, f.confidence) for f in found] == [
        ("silence", 0, 4000, 1.0)
    ]
    assert found[0].level_dbfs == -160.0


def test_short_quiet_gap_is_not_silence() -> None:
    signal = tone(2) + silence(0.8) + tone(2)
    assert "silence" not in kinds(features(samples(signal), 4800))


def test_impact_is_time_aligned_and_classified() -> None:
    signal = noise_floor(4)
    add_impact(signal, 1.234)
    found = [f for f in features(samples(signal), 4000) if f.kind in ("impact", "onset")]
    assert len(found) == 1
    impact = found[0]
    assert impact.kind == "impact"
    assert abs(impact.start_ms - 1234) <= IMPACT_TOLERANCE_MS
    assert impact.end_ms - impact.start_ms <= 300
    assert impact.level_dbfs > -20
    assert dict(impact.details)["rise_db"] >= 15


@pytest.mark.parametrize("at_s", [0.3, 0.995, 2.5, 3.7])
def test_impacts_anywhere_in_the_clip_stay_within_tolerance(at_s: float) -> None:
    signal = noise_floor(4)
    add_impact(signal, at_s)
    impacts = [f for f in features(samples(signal), 4000) if f.kind == "impact"]
    assert len(impacts) == 1 and abs(impacts[0].start_ms - at_s * 1000) <= IMPACT_TOLERANCE_MS


def test_two_impacts_close_together_are_separate_after_the_refractory_period() -> None:
    signal = noise_floor(3)
    add_impact(signal, 1.0)
    add_impact(signal, 1.4)
    impacts = [f for f in features(samples(signal), 3000) if f.kind == "impact"]
    assert [round(f.start_ms, -1) for f in impacts] == [1000, 1400]


def test_a_sound_that_starts_and_stays_is_an_onset_not_an_impact() -> None:
    signal = noise_floor(1.5) + tone(2.5, 300, 0.4)
    onsets = [f for f in features(samples(signal), 4000) if f.kind in ("impact", "onset")]
    assert [f.kind for f in onsets] == ["onset"]
    assert abs(onsets[0].start_ms - 1500) <= IMPACT_TOLERANCE_MS


def test_speech_like_activity_is_found_with_its_boundaries() -> None:
    signal = silence(1) + speech_like(3) + silence(2)
    speech = [f for f in features(samples(signal), 6000) if f.kind == "speech_activity"]
    assert len(speech) == 1
    s = speech[0]
    assert abs(s.start_ms - 1000) <= BOUNDARY_TOLERANCE_MS
    assert abs(s.end_ms - 4000) <= BOUNDARY_TOLERANCE_MS
    details = dict(s.details)
    assert 3 <= details["syllable_rate_hz"] <= 5
    assert details["band_ratio"] >= 0.45
    assert 0.5 <= s.confidence <= 0.9  # speech-LIKE, never certain


def test_tones_hum_and_steady_noise_are_not_speech() -> None:
    hum = tone(4, 120, 0.4)
    loud_noise = noise_floor(4, level=6000)
    for signal in (tone(4, 1000, 0.4), hum, loud_noise):
        assert "speech_activity" not in kinds(features(samples(signal), 4000))


def test_no_audio_completes_without_events() -> None:
    detector = AudioFeatures()
    ctx = context(None, 5000)
    detector.setup(ctx)
    assert list(detector.detect(ctx)) == []
    detector.close()


def test_empty_and_sub_hop_audio_complete() -> None:
    assert features(AudioSamples(SAMPLE_RATE, b"", b""), 1000) == []
    tiny = samples(tone(0.004))
    assert features(tiny, 4) == []


def test_detections_are_valid_supporting_evidence_events() -> None:
    signal = silence(1) + speech_like(2) + noise_floor(1)
    add_impact(signal, 3.3)
    detector = AudioFeatures()
    found = list(detector.detect(context(samples(signal), 4000)))
    assert {d.type for d in found} >= {
        "openworld.silence",
        "openworld.speech_activity",
        "openworld.audio_impact",
    }
    for d in found:
        assert d.attributes["evidence_role"] == "supporting"
        evidence = dict(d.evidence[0])
        assert evidence["role"] == "supporting" and evidence["kind"] == "audio"
        load(
            "event",
            {
                "schema_version": "1.13",
                "id": "evt_01JCBQ00000000000000000001",
                "session_id": "ses_01JCBQ00000000000000000001",
                "asset_id": "ast_01JCBQ00000000000000000001",
                "type": d.type,
                "start_ms": d.start_ms,
                "end_ms": d.end_ms,
                "confidence": d.confidence,
                "attributes": dict(d.attributes),
                "evidence": [evidence],
                "source": {
                    "kind": "detector",
                    "detector_id": "audio-features",
                    "detector_version": "1.0.0",
                    "profile_id": "generic-audio",
                    "profile_version": "1.0.0",
                },
                "review_state": "unreviewed",
            },
        )


def test_features_are_deterministic() -> None:
    signal = silence(1) + speech_like(2)
    add_impact(signal, 0.5)
    assert features(samples(signal), 3000) == features(samples(signal), 3000)


def test_cancellation_is_checked_during_feature_extraction() -> None:
    def cancelled() -> None:
        raise AnalysisCancelled

    detector = AudioFeatures()
    with pytest.raises(AnalysisCancelled):
        list(detector.detect(context(samples(tone(2)), 2000, cancelled)))


def test_band_filter_and_channel_split_match_the_ffmpeg_layout() -> None:
    # The fixture filter keeps speech harmonics and rejects low hum.
    hum_energy = sum(v * v for v in speech_band(tone(1, 60, 0.5)))
    voice_energy = sum(v * v for v in speech_band(tone(1, 1000, 0.5)))
    assert hum_energy < voice_energy / 50
    interleaved = bytes([1, 0, 2, 0, 3, 0, 4, 0])
    split = split_channels(interleaved, SAMPLE_RATE)
    assert (split.full, split.speech_band) == (bytes([1, 0, 3, 0]), bytes([2, 0, 4, 0]))


def test_track_policy_names_the_analyzed_stream() -> None:
    assert track_policy(0) == "none"
    assert track_policy(1) == "first-of-1"
    assert track_policy(3) == "first-of-3"
