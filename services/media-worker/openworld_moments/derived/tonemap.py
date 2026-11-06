# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic HDR → SDR tone mapping for proxies (spec 8.3.3, M08).

The mapping is computed here, in plain Python, as a 3D LUT (``.cube``) and
applied by FFmpeg's built-in ``lut3d`` filter. That needs no optional FFmpeg
library (``zscale``/zimg is missing from many builds), and the exact curve is
part of the recipe: same settings → byte-identical LUT → same proxy.

Per LUT entry (BT.2020 RGB, PQ- or HLG-encoded, full range [0, 1]):

1. decode to display light in nits (PQ: SMPTE ST 2084 EOTF; HLG: BT.2100
   inverse OETF + OOTF for a ``source_peak_nits`` display),
2. tone-map with the Hable curve on the largest channel (hue preserving),
   relative to ``reference_white_nits``, so ``source_peak_nits`` maps to white,
3. convert BT.2020 → BT.709 primaries in linear light and clip to [0, 1],
4. encode with the BT.709 OETF.

The original file keeps its HDR signal; only the proxy is SDR.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

HdrTransfer = Literal["smpte2084", "arib-std-b67"]

TONEMAP_VERSION = 1
LUT_FILE = "tonemap.cube"

# SMPTE ST 2084 (PQ) constants.
_M1 = 2610 / 16384
_M2 = 2523 / 4096 * 128
_C1 = 3424 / 4096
_C2 = 2413 / 4096 * 32
_C3 = 2392 / 4096 * 32
_PQ_MAX_NITS = 10000.0

# ARIB STD-B67 (HLG) constants.
_HLG_A = 0.17883277
_HLG_B = 1 - 4 * _HLG_A
_HLG_C = 0.5 - _HLG_A * math.log(4 * _HLG_A)

# BT.2020 → BT.709 in linear light (ITU-R BT.2087).
_BT2020_TO_BT709 = (
    (1.660491, -0.587641, -0.072850),
    (-0.124550, 1.132900, -0.008349),
    (-0.018151, -0.100579, 1.118730),
)
_BT2020_LUMA = (0.2627, 0.6780, 0.0593)

# Hable (Uncharted 2) filmic curve, as in FFmpeg's tonemap filter.
_HA, _HB, _HC, _HD, _HE, _HF = 0.15, 0.50, 0.10, 0.20, 0.02, 0.30


@dataclass(frozen=True)
class ToneMapSettings:
    """Everything that determines the LUT. Recorded with every tone-mapped proxy."""

    transfer: HdrTransfer
    method: str = "lut3d"
    curve: str = "hable"
    source_peak_nits: float = 1000.0
    reference_white_nits: float = 100.0
    output_primaries: str = "bt709"
    output_transfer: str = "bt709"
    lut_size: int = 33
    interpolation: str = "tetrahedral"
    version: int = TONEMAP_VERSION

    def describe(self) -> dict[str, Any]:
        return {**asdict(self), "lut_sha256": lut_sha256(self)}


def pq_to_nits(code: float) -> float:
    e = max(0.0, min(1.0, code)) ** (1 / _M2)
    return float((max(e - _C1, 0.0) / (_C2 - _C3 * e)) ** (1 / _M1) * _PQ_MAX_NITS)


def _hlg_inverse_oetf(code: float) -> float:
    code = max(0.0, min(1.0, code))
    if code <= 0.5:
        return code * code / 3
    return (math.exp((code - _HLG_C) / _HLG_A) + _HLG_B) / 12


def hlg_to_nits(rgb: tuple[float, float, float], peak: float) -> tuple[float, float, float]:
    """BT.2100 HLG: inverse OETF then the OOTF for a display of ``peak`` nits."""
    scene = tuple(_hlg_inverse_oetf(c) for c in rgb)
    gamma = 1.2 + 0.42 * math.log10(peak / 1000)
    ys = sum(k * c for k, c in zip(_BT2020_LUMA, scene, strict=True))
    gain = peak * (ys ** (gamma - 1)) if ys > 0 else 0.0
    r, g, b = (gain * c for c in scene)
    return r, g, b


def _hable(x: float) -> float:
    return ((x * (_HA * x + _HC * _HB) + _HD * _HE) / (x * (_HA * x + _HB) + _HD * _HF)) - _HE / _HF


def bt709_oetf(linear: float) -> float:
    linear = max(0.0, min(1.0, linear))
    if linear < 0.018:
        return 4.5 * linear
    return float(1.099 * linear**0.45 - 0.099)


def map_pixel(
    rgb: tuple[float, float, float], settings: ToneMapSettings
) -> tuple[float, float, float]:
    """One HDR code value (BT.2020, [0, 1]) → SDR BT.709 code value ([0, 1])."""
    if settings.transfer == "smpte2084":
        nits = tuple(pq_to_nits(c) for c in rgb)
    else:
        nits = hlg_to_nits(rgb, settings.source_peak_nits)
    white = settings.reference_white_nits
    signal = [n / white for n in nits]
    peak = settings.source_peak_nits / white
    biggest = max(signal)
    if biggest > 0:
        mapped = min(_hable(min(biggest, peak)) / _hable(peak), 1.0)
        signal = [c * mapped / biggest for c in signal]
    out = []
    for row in _BT2020_TO_BT709:
        linear = sum(k * c for k, c in zip(row, signal, strict=True))
        out.append(bt709_oetf(linear))
    return out[0], out[1], out[2]


def cube_text(settings: ToneMapSettings) -> str:
    """The LUT as an Adobe/Resolve ``.cube`` file (red varies fastest)."""
    n = settings.lut_size
    if not 2 <= n <= 65:
        raise ValueError("lut_size must be between 2 and 65")
    lines = [
        "# OpenWorld Moments proxy tone map",
        f"# {settings.transfer} BT.2020 -> BT.709 SDR, {settings.curve}, "
        f"peak {settings.source_peak_nits:g} nits, v{settings.version}",
        f"LUT_3D_SIZE {n}",
    ]
    step = 1 / (n - 1)
    for b in range(n):
        for g in range(n):
            for r in range(n):
                out = map_pixel((r * step, g * step, b * step), settings)
                lines.append(" ".join(f"{v:.6f}" for v in out))
    return "\n".join(lines) + "\n"


_LUT_CACHE: dict[ToneMapSettings, tuple[str, str]] = {}


def lut(settings: ToneMapSettings) -> tuple[str, str]:
    """``(cube text, sha256)``, computed once per settings."""
    cached = _LUT_CACHE.get(settings)
    if cached is None:
        text = cube_text(settings)
        cached = (text, hashlib.sha256(text.encode("ascii")).hexdigest())
        _LUT_CACHE[settings] = cached
    return cached


def lut_sha256(settings: ToneMapSettings) -> str:
    return lut(settings)[1]


def is_hdr_transfer(transfer: str | None) -> bool:
    return transfer in ("smpte2084", "arib-std-b67")
