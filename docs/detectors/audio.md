# Audio features (M18)

The built-in `audio-features` detector (version 1.0.0) produces timestamped audio
evidence. It runs through the M14 runtime with profile `generic-audio`.

**Every output is supporting evidence, not a highlight.** Each event carries
`attributes.evidence_role: "supporting"`, and its `audio` evidence carries
`role: "supporting"`; contract 1.13 allows no other value. A loud moment is not
proof that something important happened. Downstream consumers (M19 review, M20
stories) must corroborate audio with other evidence before relying on it.

Code: `services/media-worker/openworld_moments/detectors/audio.py`,
`audio_input.py`; synthetic signals in `audio_fixtures.py`.

## Input

- **Source:** like every detector, audio is read only from the checked M08 proxy.
  The proxy's bytes must match its row; the original is never opened.
- **Extraction:** a fixed FFmpeg graph produces mono 8 kHz signed 16-bit audio as
  two channels: the full band, and the same signal band-passed to 300–3400 Hz
  (second-order high-pass and low-pass). No profile value reaches FFmpeg.
- **Sampler version:** `pcm8k-mono-speechband-v1`.
- **Track policy:** the first audio stream (`0:a:0`) is analyzed, the same stream as
  the proxy, waveform, and fingerprints. Provenance records `audio_track`:
  - `first-of-N`, where N is the number of audio streams the source has;
  - `none` for a clip without audio.

  Other tracks, such as a separate microphone track, are not analyzed in M18.
- **No audio:** the unit completes with status `computed` and no events. It is not a
  failure and is not skipped.
- **Limit:** decoding is capped at 64 MiB per clip, about 35 minutes of audio. A
  longer clip fails that unit with `analysis.audio_too_long`; other clips and
  detectors are unaffected. Streaming analysis of long clips is future work.

## Feature definitions

All features start from **10 ms hop energies**: the mean square of each 80-sample
hop of both channels.

**Level** is RMS in dBFS: `10·log10(energy / 32768²)`.
- A full-scale sine measures about −3 dBFS.
- Digital silence is floored at −160 dBFS.

### Loudness envelope

The level of each 100 ms block (10 hops). It is the basis for silence and the
`level_dbfs` values. It is not emitted as events: a continuous loudness series
would invite "loud = important" readings.

### Onset and impact

An onset is triggered at hop *i* when both hold:
- the level jumps at least **15 dB** above the loudest hop of the previous 50 ms;
- the level reaches at least **−40 dBFS**.

How it is reported:
- **Peak:** the loudest hop within the next 50 ms.
- **Impact** (`openworld.audio_impact`): the level falls at least **12 dB** below the
  peak within 300 ms, i.e. a short transient. The event ends where it has decayed.
- **Onset** (`openworld.audio_onset`): any other onset, i.e. a sound that starts and
  stays. The event covers 300 ms.
- **Refractory period:** no new onset is triggered within 150 ms after a peak.
- **Confidence:** `0.5 + (rise − 15 dB) / 50`, clamped to [0.5, 0.9].
- **Attributes:** `level_dbfs` (the peak) and `rise_db`.

### Silence (`openworld.silence`)

A run of 100 ms blocks, all below **−50 dBFS**, lasting at least **1 s**.
- **Confidence:** `0.5 + (−50 − loudest block) / 40`, clamped to [0.5, 1].
  Digital silence scores 1.
- **Level:** `level_dbfs` is the loudest block in the run.

### Speech-like activity (`openworld.speech_activity`)

1. **Voiced blocks:** a 100 ms block is voiced when its level is at least
   −45 dBFS and at least **45%** of its energy is in the speech band.
2. **Runs:** gaps of up to 300 ms are bridged, and a run must last at least 600 ms.
3. **Syllable-like modulation:** a run is kept only if both hold:
   - the standard deviation of the speech-band hop levels is at least **3 dB**, which
     rejects steady tones, hum and noise;
   - there are 1.5–10 syllable-like peaks per second. A peak is a local maximum of
     the 30 ms smoothed band level that rises at least 6 dB above the preceding
     minimum, at least 100 ms after the previous peak.

Reporting:
- **Confidence:** `0.5 + 0.2·clamp((ratio − 0.45) / 0.35) + 0.2·clamp((modulation − 3) / 6)`,
  capped at **0.9**. This is speech-*like* activity, not identified speech.
- **Attributes:** `band_ratio`, `modulation_db`, `syllable_rate_hz` (speech rate).

All thresholds are fixed constants in the versioned detector. Changing one requires
a detector version bump, which invalidates cached results. These scores are
explainable heuristics, not calibrated probabilities.

## Timing tolerance

| Feature | Resolution | Asserted tolerance |
|---|---|---|
| Impact / onset start | 10 ms hop | ±20 ms on synthetic PCM; ±30 ms after the AAC proxy and FFmpeg decode (measured within 10 ms) |
| Silence and speech-activity boundaries | 100 ms block | ±150 ms |

**Session time:** event times are source milliseconds, mapped by the runtime into
M13 unique session time like any other event. Features entirely inside hidden
repeated footage are dropped, and crossing ones are clipped.
`attributes.source_start_ms` and `source_end_ms` keep the source interval.

## Validation

- **Unit tests** (`tests/detectors/test_audio.py`, synthetic PCM):
  - dBFS calibration;
  - steady tones and hum produce no events;
  - digital silence, and short gaps that are not silence;
  - impact alignment at four positions;
  - two impacts 400 ms apart;
  - sustained onset versus impact;
  - speech-like boundaries and rate;
  - tone, hum and steady noise rejected as speech;
  - no audio, empty and sub-hop audio;
  - contract-valid supporting evidence;
  - determinism, cancellation, the channel split, and the track policy.
- **Real path** (`tests/media/test_audio.py`), generated clips → import → proxy → analysis:
  - speech, impact and silence intervals within tolerance after AAC;
  - a silent clip, a clip without audio, and a two-track clip (first stream analyzed);
  - FFmpeg cancellation;
  - cache reuse;
  - unchanged source bytes and mtime.
- **Benchmark:** `uv run --directory services/media-worker owm audio benchmark --minutes 10 --repeats 3`
  measures feature extraction only. On Apple M4 / macOS arm64 / Python 3.12.14, 10
  synthetic minutes took a median **0.156 s** (about 3,850× real time). This excludes
  proxy creation, FFmpeg decode and I/O, which dominate in practice.

## Limits

- **Not validated on gameplay:** all quality evidence is synthetic.
  - Music, engine noise, explosions layered over speech, and game mixes are not
    validated.
  - Music with a syllable-like rhythm can be classed as speech-like activity.
- **Not built:** laughter detection, speaker diarization, and emotion analysis are
  not implemented. Diarization and emotion are out of scope.
- **One stream:** only the first audio stream is analyzed.
