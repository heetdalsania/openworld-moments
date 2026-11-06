# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compact waveform data (``waveform-<key>.bin``, M08).

FFmpeg decodes the first audio stream to mono 16-bit PCM at
:data:`SAMPLE_RATE_HZ`; samples are streamed (never held in memory) into
buckets of ``SAMPLE_RATE_HZ / BUCKETS_PER_SECOND`` samples. Each bucket stores
its peak and RMS amplitude as one byte each (0 = silence, 255 = full scale).

File layout, little-endian::

    offset  size  field
    0       4     magic b"OWMW"
    4       2     format version (1)
    6       2     buckets per second
    8       4     decode sample rate (Hz)
    12      4     bucket count N
    16      2N    N * (peak u8, rms u8)

An hour of audio is about 360 KB.
"""

from __future__ import annotations

import math
import operator
import struct
from array import array
from dataclasses import dataclass

MAGIC = b"OWMW"
FORMAT_VERSION = 1
SAMPLE_RATE_HZ = 8000
BUCKETS_PER_SECOND = 50
BUCKET_SAMPLES = SAMPLE_RATE_HZ // BUCKETS_PER_SECOND
HEADER = struct.Struct("<4sHHII")
_FULL_SCALE = 32768.0


class WaveformError(Exception):
    pass


class WaveformBuilder:
    """Feed raw s16le bytes in any chunk sizes; call :meth:`finish` once."""

    def __init__(self) -> None:
        self._carry = b""
        self._pending = array("h")
        self._buckets = bytearray()
        self.samples = 0

    def feed(self, data: bytes) -> None:
        data = self._carry + data
        usable = len(data) - len(data) % 2
        self._carry = data[usable:]
        if not usable:
            return
        block = array("h")
        block.frombytes(data[:usable])
        if struct.pack("=h", 1) != struct.pack("<h", 1):  # pragma: no cover - big-endian host
            block.byteswap()
        self.samples += len(block)
        self._pending.extend(block)
        whole = len(self._pending) - len(self._pending) % BUCKET_SAMPLES
        for start in range(0, whole, BUCKET_SAMPLES):
            self._add(self._pending[start : start + BUCKET_SAMPLES])
        del self._pending[:whole]

    def _add(self, bucket: array[int]) -> None:
        peak = max(max(bucket), -min(bucket))
        rms = math.sqrt(sum(map(operator.mul, bucket, bucket)) / len(bucket))
        self._buckets.append(_byte(peak))
        self._buckets.append(_byte(rms))

    def finish(self) -> bytes:
        if self._pending:
            self._add(self._pending)
            self._pending = array("h")
        count = len(self._buckets) // 2
        header = HEADER.pack(MAGIC, FORMAT_VERSION, BUCKETS_PER_SECOND, SAMPLE_RATE_HZ, count)
        return header + bytes(self._buckets)


def _byte(amplitude: float) -> int:
    return min(255, round(amplitude / _FULL_SCALE * 255))


@dataclass(frozen=True)
class Waveform:
    buckets_per_second: int
    sample_rate_hz: int
    peaks: bytes
    rms: bytes


def parse(data: bytes) -> Waveform:
    """Read a waveform file, checking the header and length."""
    if len(data) < HEADER.size:
        raise WaveformError("waveform file is truncated")
    magic, version, rate, sample_rate, count = HEADER.unpack_from(data)
    if magic != MAGIC or version != FORMAT_VERSION:
        raise WaveformError("not a version 1 waveform file")
    body = data[HEADER.size :]
    if len(body) != 2 * count or rate < 1:
        raise WaveformError("waveform length does not match its header")
    return Waveform(rate, sample_rate, bytes(body[0::2]), bytes(body[1::2]))


def expected_buckets(samples: int) -> int:
    return -(-samples // BUCKET_SAMPLES)
