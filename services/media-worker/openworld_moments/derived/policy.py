# SPDX-License-Identifier: AGPL-3.0-or-later
"""When an asset needs a playback proxy, and what the proxy looks like (spec 8.3.2).

The embedded player is the system web view (WebView2, WKWebView, WebKitGTK).
The only video they all decode smoothly is 8-bit 4:2:0 H.264 in MP4/MOV, with
AAC or MP3 audio, at up to 1080p and 60 fps. Anything else gets a proxy, and
every reason is recorded so the decision is explainable. HDR always gets a
proxy: web views show PQ/HLG inconsistently, and the proxy is tone-mapped SDR.

Bump :data:`POLICY_VERSION` whenever a rule changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from openworld_moments_contracts.generated.media_asset_schema import MediaAsset, VideoStream

from openworld_moments.derived.tonemap import is_hdr_transfer

POLICY_VERSION = 1
ProxyPolicy = Literal["auto", "always"]

PLAYABLE_CODECS = frozenset({"h264"})
PLAYABLE_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p"})
PLAYABLE_AUDIO = frozenset({"aac", "mp3"})
#: FFprobe format names of MP4-family containers ("mov,mp4,m4a,3gp,3g2,mj2").
PLAYABLE_CONTAINER_TOKENS = frozenset({"mp4", "mov"})
MAX_PLAYABLE_PIXELS = 1920 * 1080
MAX_PLAYABLE_FPS = Fraction(60)

#: Proxy geometry: the longer edge is at most this many pixels (1280 for landscape,
#: so a vertical proxy is never larger than a horizontal one).
PROXY_MAX_EDGE = 1280
#: Proxies keep the source timing (VFR stays VFR) unless it is faster than this.
PROXY_MAX_FPS = 60
#: Filmstrip thumbnails: longer edge in pixels.
THUMB_MAX_EDGE = 160


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str

    def doc(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ProxyDecision:
    needed: bool
    policy: ProxyPolicy
    reasons: tuple[Reason, ...]

    def doc(self) -> dict[str, object]:
        return {
            "needed": self.needed,
            "policy": self.policy,
            "policy_version": POLICY_VERSION,
            "reasons": [r.doc() for r in self.reasons],
        }


def frame_rate(video: VideoStream) -> Fraction:
    rate = video.average_frame_rate or video.frame_rate
    return Fraction(rate.num, rate.den)


def display_size(video: VideoStream) -> tuple[int, int]:
    """Upright (post-rotation) width and height."""
    if video.rotation in (90, 270):
        return video.height, video.width
    return video.width, video.height


def fit(width: int, height: int, max_edge: int) -> tuple[int, int]:
    """Scale to fit ``max_edge`` on the longer side (never up), with even sizes."""
    scale = min(1.0, max_edge / max(width, height))
    return _even(width * scale), _even(height * scale)


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def is_hdr(video: VideoStream) -> bool:
    return bool(video.color.hdr) or is_hdr_transfer(video.color.transfer)


def decide(asset: MediaAsset, policy: ProxyPolicy = "auto") -> ProxyDecision:
    video = asset.video
    if video is None:  # imports require video; defensive
        return ProxyDecision(False, policy, (Reason("no_video", "The asset has no video."),))
    reasons: list[Reason] = []
    if policy == "always":
        reasons.append(Reason("requested", "A proxy was requested, or the asset already has one."))
    tokens = set((asset.container or "").split(","))
    if not tokens & PLAYABLE_CONTAINER_TOKENS:
        reasons.append(Reason("container", f"Container '{asset.container}' is not MP4 or MOV."))
    if video.codec not in PLAYABLE_CODECS:
        reasons.append(Reason("codec", f"Video codec '{video.codec}' is not H.264."))
    if video.pixel_format and video.pixel_format not in PLAYABLE_PIXEL_FORMATS:
        reasons.append(
            Reason("pixel_format", f"Pixel format '{video.pixel_format}' is not 8-bit 4:2:0.")
        )
    if is_hdr(video):
        reasons.append(
            Reason("hdr", f"HDR ({video.color.transfer or 'flagged'}): the proxy is tone-mapped.")
        )
    width, height = display_size(video)
    if width * height > MAX_PLAYABLE_PIXELS:
        reasons.append(Reason("resolution", f"{width}x{height} is larger than 1920x1080."))
    fps = frame_rate(video)
    if fps > MAX_PLAYABLE_FPS:
        reasons.append(Reason("frame_rate", f"{float(fps):.3f} fps is above 60 fps."))
    audio = asset.audio or []
    if audio and audio[0].codec not in PLAYABLE_AUDIO:
        reasons.append(Reason("audio_codec", f"Audio codec '{audio[0].codec}' is not AAC or MP3."))
    return ProxyDecision(bool(reasons), policy, tuple(reasons))


@dataclass(frozen=True)
class ProxyGeometry:
    width: int
    height: int
    #: None keeps source timing; otherwise constant frames per second.
    fps_cap: int | None
    hdr_transfer: str | None


def proxy_geometry(video: VideoStream) -> ProxyGeometry:
    width, height = fit(*display_size(video), PROXY_MAX_EDGE)
    cap = PROXY_MAX_FPS if frame_rate(video) > PROXY_MAX_FPS else None
    transfer: str | None = None
    if is_hdr(video):
        transfer = video.color.transfer
        if not is_hdr_transfer(transfer):
            transfer = "smpte2084"  # flagged HDR without a known transfer: assume HDR10
    return ProxyGeometry(width, height, cap, transfer)


def thumbnail_size(width: int, height: int) -> tuple[int, int]:
    return fit(width, height, THUMB_MAX_EDGE)
