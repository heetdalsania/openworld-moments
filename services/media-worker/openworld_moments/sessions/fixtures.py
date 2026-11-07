# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic session fixtures (M11): metadata-only assets for grouping tests.

Each scenario is a list of :class:`Clip` descriptions: name, source, folder,
recording time, duration, format, and which import job brought it in. ``install``
writes them as asset rows plus import provenance, exactly as an import would, but
without any media file. Nothing here is footage; nothing is written to disk except
the library database.

    uv run --directory services/media-worker python -m openworld_moments.sessions.fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from openworld_moments_contracts import load

from openworld_moments.sessions.capture import Signals, estimate, iso
from openworld_moments.storage import AssetImportRepository, AssetRepository, transaction
from openworld_moments.storage.repositories import SCHEMA_VERSION

_EPOCH = datetime(2026, 11, 20, 3, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Clip:
    """One synthetic capture. Times are UTC unless ``name`` carries a local time."""

    name: str
    start: datetime
    duration_s: int = 60
    source_kind: str = "xbox"
    folder: str = "/captures/Xbox"
    #: Container creation time; None means the container has none.
    container: datetime | None = None
    #: File mtime; default: the recording's end (as consoles write it).
    mtime: datetime | None = None
    job: str = "job_01JCBQ0000000000000000JOB1"
    codec: str = "h264"
    width: int = 1920
    height: int = 1080
    fps: tuple[int, int] = (60, 1)
    #: Seconds after the batch's first import, to keep import order deterministic.
    imported_offset_s: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def at(minutes: float) -> datetime:
    """A UTC time ``minutes`` after the fixture epoch (2026-11-20 03:00 UTC)."""
    return _EPOCH + timedelta(minutes=minutes)


def _asset_id(index: int, name: str) -> str:
    digest = hashlib.sha256(name.encode()).hexdigest()[:6].upper()
    tail = "".join(c if c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" else "0" for c in digest)
    return f"ast_01JCBQ{index:014d}{tail}"


def install(conn: sqlite3.Connection, clips: Sequence[Clip], zone: Any = None) -> list[str]:
    """Insert clips as assets with import provenance; returns their IDs in order."""
    ids: list[str] = []
    with transaction(conn):
        assets = AssetRepository(conn)
        imports = AssetImportRepository(conn)
        for index, clip in enumerate(clips, start=1):
            asset_id = _asset_id(index, clip.name)
            end = clip.start + timedelta(seconds=clip.duration_s)
            mtime = clip.mtime or end
            mtime_ns = int(mtime.timestamp() * 1e9)
            container = iso(clip.container) if clip.container else None
            signals = Signals(clip.name, container, mtime_ns, clip.duration_s * 1000)
            imported = iso(_EPOCH + timedelta(days=1, seconds=clip.imported_offset_s + index))
            doc = {
                "schema_version": SCHEMA_VERSION,
                "id": asset_id,
                "sha256": hashlib.sha256(f"{index}:{clip.name}".encode()).hexdigest(),
                "original_name": clip.name,
                "source_kind": clip.source_kind,
                "import_mode": "reference",
                "size_bytes": 1000 + index,
                "capture_time": estimate(signals, zone).doc(),
                "duration_ms": clip.duration_s * 1000,
                "container": "mov,mp4,m4a,3gp,3g2,mj2",
                "video": {
                    "codec": clip.codec,
                    "width": clip.width,
                    "height": clip.height,
                    "frame_rate": {"num": clip.fps[0], "den": clip.fps[1]},
                    "pixel_format": "yuv420p",
                    "color": {"hdr": False},
                },
                "audio": [{"codec": "aac", "channels": 2, "sample_rate_hz": 48000}],
                "created_at": imported,
            }
            path = f"{clip.folder.rstrip('/')}/{clip.name}"
            assets.add(
                load("media-asset", doc),  # type: ignore[arg-type]
                original_path=path,
                container_created_at=container,
            )
            imports.record(
                asset_id=asset_id,
                import_mode="reference",
                source_kind=clip.source_kind,
                source_path=path,
                size_bytes=1000 + index,
                mtime_ns=mtime_ns,
                job_id=clip.job,
                when=imported,
            )
            ids.append(asset_id)
    return ids


def _xbox_name(game: str, local: datetime) -> str:
    return f"{game} {local:%Y-%m-%d %H-%M-%S}.mp4"


def scenarios() -> dict[str, list[Clip]]:
    """Named scenarios for the fixture matrix (local times assume UTC)."""
    return {
        "adjacent_same_source": [
            Clip(_xbox_name("Heist", at(m)), at(m), container=at(m)) for m in (0, 3, 6)
        ],
        "large_gap": [
            Clip(_xbox_name("Heist", at(0)), at(0), container=at(0)),
            Clip(_xbox_name("Heist", at(120)), at(120), container=at(120)),
        ],
        "format_change": [
            Clip(_xbox_name("Heist", at(0)), at(0), container=at(0)),
            Clip(_xbox_name("Heist", at(2)), at(2), container=at(2), width=3840, height=2160),
        ],
        "mixed_folders": [
            Clip(_xbox_name("Heist", at(0)), at(0), folder="/captures/Xbox/Heist"),
            Clip(_xbox_name("Race", at(1)), at(1), folder="/captures/Xbox/Race"),
        ],
        "mixed_sources": [
            Clip(_xbox_name("Heist", at(0)), at(0)),
            Clip("Heist_20261120030100.mp4", at(1), source_kind="playstation", folder="/ps"),
        ],
        "overlapping_replays": [
            Clip(_xbox_name("Heist", at(0)), at(0), duration_s=60, container=at(0)),
            Clip(
                _xbox_name("Heist", at(0.75)),
                at(0.75),
                duration_s=60,
                container=at(0.75),
            ),
        ],
        "phone_copies_without_times": [
            Clip(
                f"IMG_{n:04d}.MOV",
                at(500),
                source_kind="phone_upload",
                folder="/staging",
                mtime=at(500) + timedelta(milliseconds=200 * n),
                job="job_01JCBQ0000000000000000JOB2",
                imported_offset_s=n,
            )
            for n in (1, 2, 3)
        ],
        "timezone_mismatch": [
            # Container claims UTC but holds local time 7 hours off: confidence drops.
            Clip(_xbox_name("Heist", at(0)), at(0), container=at(0) + timedelta(hours=7)),
        ],
        "boundary_gap": [
            Clip(_xbox_name("Heist", at(0)), at(0), duration_s=60, container=at(0)),
            # Starts exactly 15 minutes after the first ends: still the same session.
            Clip(_xbox_name("Heist", at(16)), at(16), container=at(16)),
            # 15 minutes and 1 second after the second ends: a new session.
            Clip(
                _xbox_name("Heist", at(32) + timedelta(seconds=1)),
                at(32) + timedelta(seconds=1),
                container=at(32) + timedelta(seconds=1),
            ),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m openworld_moments.sessions.fixtures",
        description="Print the synthetic session scenarios (metadata only, no media).",
    )
    parser.add_argument("--scenario", help="only this scenario")
    args = parser.parse_args(argv)
    chosen = scenarios()
    if args.scenario:
        if args.scenario not in chosen:
            print(f"unknown scenario; choose from {', '.join(chosen)}", file=sys.stderr)
            return 2
        chosen = {args.scenario: chosen[args.scenario]}
    out = {
        name: [{"name": c.name, "start": iso(c.start), "source": c.source_kind} for c in clips]
        for name, clips in chosen.items()
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
