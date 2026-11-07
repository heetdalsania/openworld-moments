# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic metadata grouping of assets into candidate sessions (spec 8.2.2, M11).

Assets are split by source, ordered by estimated capture time (then import order),
and walked in order. A clip joins the previous one's session when:

1. it comes from the same source (kind and folder; see :func:`source_key`),
2. its format is compatible (codec, upright resolution, frame rate within 1%),
3. it starts at most ``max_gap_ms`` after the previous clip ends (15 minutes by
   default; overlapping clips, as replay buffers produce, also join).

When neither clip has a usable time (both are bulk-copy mtimes), time cannot decide:
neighbours from the same import join on import order alone, at very low confidence.

Every join records its evidence (gap, confidence, reasons). A session's confidence is
its weakest link (or, for one clip, how sure its start time is). Visual and audio
overlap (M12) will raise confidence later; nothing here reads media.

Bump :data:`GROUPING_VERSION` whenever a rule changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any

from openworld_moments.sessions.capture import parse_utc

GROUPING_ALGORITHM = "owm-metadata-gap"
GROUPING_VERSION = 1
DEFAULT_MAX_GAP_MS = 15 * 60 * 1000
FPS_TOLERANCE = Fraction(1, 100)
#: Below this capture-time confidence a clip's time is treated as unknown.
UNKNOWN_TIME_CONFIDENCE = 0.15
IMPORT_ORDER_CONFIDENCE = 0.15
#: Join confidence falls linearly from 1.0 (gap up to a minute) to this at max gap.
FAR_GAP_FACTOR = 0.7
CLOSE_GAP_MS = 60_000


@dataclass(frozen=True)
class AssetFacts:
    """What grouping knows about one asset. Built from the database; no media access."""

    id: str
    source_key: str
    captured_at: str
    capture_confidence: float
    duration_ms: int
    created_at: str  # import order
    import_job: str | None = None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: Fraction | None = None

    @property
    def start(self) -> datetime:
        when = parse_utc(self.captured_at)
        if when is None:  # pragma: no cover - stored values are validated
            raise ValueError(f"bad capture time for {self.id}")
        return when

    @property
    def time_known(self) -> bool:
        return self.capture_confidence > UNKNOWN_TIME_CONFIDENCE


@dataclass(frozen=True)
class Link:
    from_asset_id: str
    to_asset_id: str
    gap_ms: int
    confidence: float
    reasons: tuple[str, ...]

    def doc(self) -> dict[str, Any]:
        return {
            "from_asset_id": self.from_asset_id,
            "to_asset_id": self.to_asset_id,
            "gap_ms": self.gap_ms,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


@dataclass
class Group:
    assets: list[AssetFacts]
    links: list[Link] = field(default_factory=list)
    #: Why this group did not continue the previous one from the same source.
    split_before: tuple[str, ...] = ()

    @property
    def confidence(self) -> float:
        if self.links:
            return min(link.confidence for link in self.links)
        return round(self.assets[0].capture_confidence, 3)


@dataclass(frozen=True)
class Settings:
    max_gap_ms: int = DEFAULT_MAX_GAP_MS

    def doc(self) -> dict[str, Any]:
        return {"max_gap_ms": self.max_gap_ms}


def compatible(a: AssetFacts, b: AssetFacts) -> tuple[bool, str]:
    if a.video_codec != b.video_codec:
        return False, "codec_changed"
    if (a.width, a.height) != (b.width, b.height):
        return False, "resolution_changed"
    if a.fps is not None and b.fps is not None:
        if abs(a.fps - b.fps) > FPS_TOLERANCE * max(a.fps, b.fps):
            return False, "frame_rate_changed"
    elif a.fps != b.fps:
        return False, "frame_rate_changed"
    return True, "compatible_format"


def gap_ms(a: AssetFacts, b: AssetFacts) -> int:
    end_a = a.start.timestamp() * 1000 + a.duration_ms
    return round(b.start.timestamp() * 1000 - end_a)


def evaluate(a: AssetFacts, b: AssetFacts, settings: Settings) -> Link | tuple[str, ...]:
    """A :class:`Link` when ``b`` continues ``a``'s session, else the split reasons."""
    ok, format_reason = compatible(a, b)
    if not ok:
        return (format_reason,)
    if not (a.time_known and b.time_known):
        if a.import_job is not None and a.import_job == b.import_job:
            return Link(
                a.id,
                b.id,
                0,
                IMPORT_ORDER_CONFIDENCE,
                ("same_source", "compatible_format", "time_unknown", "import_order"),
            )
        return ("time_unknown",)
    gap = gap_ms(a, b)
    if gap > settings.max_gap_ms:
        return ("gap_exceeded",)
    reasons = ["same_source", "compatible_format", "gap_within_limit"]
    if gap < 0:
        reasons.append("overlapping")
    if gap <= CLOSE_GAP_MS:
        factor = 1.0
    else:
        span = max(1, settings.max_gap_ms - CLOSE_GAP_MS)
        factor = 1.0 - (1.0 - FAR_GAP_FACTOR) * (gap - CLOSE_GAP_MS) / span
    confidence = round(min(a.capture_confidence, b.capture_confidence) * factor, 3)
    return Link(a.id, b.id, gap, confidence, tuple(reasons))


def ordering_key(asset: AssetFacts) -> tuple[str, str, str]:
    return (asset.captured_at, asset.created_at, asset.id)


def group(assets: list[AssetFacts], settings: Settings | None = None) -> list[Group]:
    """Group assets. Deterministic: the same facts always give the same groups in the
    same order (by source key, then start time)."""
    settings = settings or Settings()
    by_source: dict[str, list[AssetFacts]] = defaultdict(list)
    for asset in assets:
        by_source[asset.source_key].append(asset)
    groups: list[Group] = []
    for key in sorted(by_source):
        ordered = sorted(by_source[key], key=ordering_key)
        current = Group([ordered[0]])
        for asset in ordered[1:]:
            verdict = evaluate(current.assets[-1], asset, settings)
            if isinstance(verdict, Link):
                current.assets.append(asset)
                current.links.append(verdict)
            else:
                groups.append(current)
                current = Group([asset], split_before=verdict)
        groups.append(current)
    groups.sort(key=lambda g: (g.assets[0].captured_at, g.assets[0].source_key, g.assets[0].id))
    return groups


def source_key(source_kind: str, source_folder: str | None) -> str:
    """Where a clip came from: its source kind, plus the folder it was imported from.

    Phone uploads arrive through a fresh staging folder each time, so only their
    kind counts. The folder is local data: it is compared, never logged or returned.
    """
    if source_kind == "phone_upload" or not source_folder:
        return source_kind
    return f"{source_kind}|{source_folder}"


def offsets(assets: list[AssetFacts], *, chronological: bool = True) -> list[int]:
    """Each asset's start within the session (ms, non-decreasing). Chronological
    sessions use capture times; a hand-ordered session places clips end to end."""
    out: list[int] = []
    if not assets:
        return out
    if chronological:
        origin = assets[0].start.timestamp() * 1000
        previous = 0
        for asset in assets:
            value = max(previous, round(asset.start.timestamp() * 1000 - origin))
            out.append(value)
            previous = value
        return out
    position = 0
    for asset in assets:
        out.append(position)
        position += max(0, asset.duration_ms)
    return out


def evidence(group_: Group, settings: Settings, notes: list[str] | None = None) -> dict[str, Any]:
    """The grouping record stored with a session (contract ``SessionGrouping``)."""
    doc: dict[str, Any] = {
        "algorithm": GROUPING_ALGORITHM,
        "version": GROUPING_VERSION,
        "settings": settings.doc(),
        "links": [link.doc() for link in group_.links],
    }
    if group_.split_before:
        doc["split_before"] = list(group_.split_before)
    if notes:
        doc["notes"] = sorted(set(notes))
    return doc
