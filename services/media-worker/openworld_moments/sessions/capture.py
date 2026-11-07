# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capture-time estimation (spec 8.2.4, M11).

Three signals, each with a known weakness:

* **filename**: console and recorder names carry the local wall-clock time of the
  recording (no time zone). Converted with the computer's time zone *for that
  date*, which is right when the capture device and the computer share a zone.
* **container_metadata**: the container's creation time, nominally UTC. Some
  devices write local time as if it were UTC, and some apps rewrite it on
  download.
* **filesystem_mtime**: when the file was last written, usually the end of the
  recording. Copies and downloads reset it.

The estimate takes the best available signal (filename, then container, then
mtime) and scores how much the others agree. Agreement raises confidence;
disagreement lowers it, and a disagreement of a whole number of hours is called
out as a likely time-zone mismatch. The result never claims more precision than
its sources: an estimate based on one weak signal stays weak.

Bump :data:`ESTIMATOR_VERSION` whenever a rule changes.
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from itertools import pairwise
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ESTIMATOR_VERSION = 1

#: Confidence of an estimate based on one signal alone.
BASE_CONFIDENCE = {"filename": 0.6, "container_metadata": 0.55, "filesystem_mtime": 0.25}
#: Two signals within this distance agree (mtime is compared with start + duration).
AGREE_WITHIN = timedelta(minutes=2)
AGREEMENT_BONUS = 0.2
DISAGREEMENT_FACTOR = 0.5
MAX_CONFIDENCE = 0.95
#: mtimes this close across one import are a copy artefact, not capture times.
COPY_ARTEFACT_WINDOW = timedelta(seconds=3)


@dataclass(frozen=True)
class FilenameTime:
    local: datetime  # naive wall-clock time
    pattern: str


# Each pattern names its groups; all must form a valid date and time.
_SEP = r"[-_. ]"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # OBS, Xbox (OneDrive), generic: 2026-11-20 03-14-22, 2026_11_20-03_14_22, 2026-11-20T03:14:22
    (
        "ymd_hms",
        re.compile(
            rf"(?<!\d)(?P<y>20\d\d){_SEP}(?P<mo>\d\d){_SEP}(?P<d>\d\d)"
            rf"(?:[T ]|{_SEP})+(?P<h>\d\d)[-_.:](?P<mi>\d\d)[-_.:](?P<s>\d\d)(?!\d)"
        ),
    ),
    # Android and phones: VID_20261120_031422, PXL_20261120_031422123, 20261120-031422
    (
        "ymd8_hms6",
        re.compile(
            r"(?<!\d)(?P<y>20\d\d)(?P<mo>\d\d)(?P<d>\d\d)[_-](?P<h>\d\d)(?P<mi>\d\d)(?P<s>\d\d)(?:\d{1,3})?(?!\d)"
        ),
    ),
    # PlayStation: Game_20261120031422
    (
        "ymdhms14",
        re.compile(
            r"(?<!\d)(?P<y>20\d\d)(?P<mo>\d\d)(?P<d>\d\d)(?P<h>\d\d)(?P<mi>\d\d)(?P<s>\d\d)(?!\d)"
        ),
    ),
    # Xbox Game Bar (Windows): Game 11_20_2026 3_14_22 AM
    (
        "mdy_hms_ampm",
        re.compile(
            r"(?<!\d)(?P<mo>\d{1,2})_(?P<d>\d{1,2})_(?P<y>20\d\d) "
            r"(?P<h>\d{1,2})_(?P<mi>\d\d)_(?P<s>\d\d) ?(?P<ampm>[AaPp][Mm])"
        ),
    ),
)


def parse_filename(name: str) -> FilenameTime | None:
    """The recording's local time from a file name, or None.

    A name that yields two different times is ambiguous and gives None.
    """
    found: dict[datetime, str] = {}
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(name):
            parts = match.groupdict()
            hour = int(parts["h"])
            ampm = parts.get("ampm")
            if ampm:
                if not 1 <= hour <= 12:
                    continue
                hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
            try:
                when = datetime(
                    int(parts["y"]),
                    int(parts["mo"]),
                    int(parts["d"]),
                    hour,
                    int(parts["mi"]),
                    int(parts["s"]),
                )
            except ValueError:
                continue
            found.setdefault(when, label)
    if len(found) != 1:
        return None
    ((when, label),) = found.items()
    return FilenameTime(when, label)


def iso(when: datetime) -> str:
    """Contract UtcTimestamp (millisecond precision, 'Z')."""
    return when.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def local_zone() -> tzinfo:
    """The computer's time zone, with its daylight-saving rules for any date where the
    system exposes an IANA zone (``TZ``, or ``/etc/localtime`` on macOS and Linux).
    Otherwise (typically Windows) the current UTC offset, which can be an hour off
    for dates on the other side of a daylight-saving change."""
    name = os.environ.get("TZ", "").lstrip(":")
    if name:
        with contextlib.suppress(ZoneInfoNotFoundError, ValueError, OSError):
            return ZoneInfo(name)
    with contextlib.suppress(OSError, ValueError), open("/etc/localtime", "rb") as handle:
        return ZoneInfo.from_file(handle, key="localtime")
    zone = datetime.now().astimezone().tzinfo
    return zone if zone is not None else UTC


def to_utc(local: datetime, zone: tzinfo) -> datetime:
    """A naive local time in ``zone`` as UTC. ZoneInfo applies the DST rules of that
    date; a fixed-offset zone applies its offset."""
    return local.replace(tzinfo=zone).astimezone(UTC)


@dataclass(frozen=True)
class Signals:
    original_name: str
    container_created_at: str | None
    mtime_ns: int | None
    duration_ms: int


@dataclass(frozen=True)
class Estimate:
    captured_at: str
    confidence: float
    basis: tuple[str, ...]
    #: Plain-language notes on agreement, disagreement, and assumptions.
    notes: tuple[str, ...] = field(default=())

    def doc(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "confidence": self.confidence,
            "basis": list(self.basis),
        }


def _whole_hours(delta: timedelta) -> bool:
    minutes = abs(delta.total_seconds()) / 60
    hours = round(minutes / 60)
    return 1 <= hours <= 14 and abs(minutes - 60 * hours) <= 2


def estimate(signals: Signals, zone: tzinfo | None = None) -> Estimate:
    """Best capture-time estimate for one asset (start of the recording, UTC)."""
    zone = zone or local_zone()
    duration = timedelta(milliseconds=max(0, signals.duration_ms))
    candidates: list[tuple[str, datetime]] = []
    named = parse_filename(signals.original_name)
    if named is not None:
        candidates.append(("filename", to_utc(named.local, zone)))
    container = parse_utc(signals.container_created_at)
    if container is not None:
        candidates.append(("container_metadata", container.astimezone(UTC)))
    if signals.mtime_ns is not None:
        end = datetime.fromtimestamp(signals.mtime_ns / 1e9, tz=UTC)
        candidates.append(("filesystem_mtime", end - duration))
    if not candidates:  # pragma: no cover - imports always record an mtime
        raise ValueError("no capture-time signal")

    primary, chosen = candidates[0]
    confidence = BASE_CONFIDENCE[primary]
    basis = [primary]
    notes: list[str] = []
    if named is not None:
        notes.append(f"Filename time read as local time ({named.pattern}).")
    for source, value in candidates[1:]:
        delta = value - chosen
        if abs(delta) <= AGREE_WITHIN:
            confidence += AGREEMENT_BONUS * (0.5 if source == "filesystem_mtime" else 1.0)
            basis.append(source)
            notes.append(f"{source} agrees.")
        elif source == "filesystem_mtime":
            notes.append("File modification time differs (likely copied or downloaded later).")
        elif _whole_hours(delta):
            confidence *= DISAGREEMENT_FACTOR
            notes.append(
                f"{source} differs by a whole number of hours: possible time-zone mismatch."
            )
        else:
            confidence *= DISAGREEMENT_FACTOR
            notes.append(f"{source} disagrees.")
    confidence = round(min(MAX_CONFIDENCE, max(0.05, confidence)), 3)
    return Estimate(iso(chosen), confidence, tuple(basis), tuple(notes))


def copy_artefacts(mtimes_ns: Sequence[int | None]) -> set[int]:
    """Indexes of mtimes that sit within a few seconds of another one: files copied
    together, whose mtimes say nothing about when they were recorded."""
    window = COPY_ARTEFACT_WINDOW.total_seconds() * 1e9
    ordered = sorted((m, i) for i, m in enumerate(mtimes_ns) if m is not None)
    flagged: set[int] = set()
    for (a, i), (b, j) in pairwise(ordered):
        if b - a <= window:
            flagged.update((i, j))
    return flagged


def with_copy_artefact(estimate_: Estimate) -> Estimate:
    """An mtime-only estimate from a bulk copy: keep the value, drop confidence."""
    if estimate_.basis != ("filesystem_mtime",):
        return estimate_
    return Estimate(
        estimate_.captured_at,
        min(estimate_.confidence, 0.1),
        estimate_.basis,
        (*estimate_.notes, "Copied together with other files: the time is the copy time."),
    )
