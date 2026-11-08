# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search benchmark on a synthetic library (M26).

Builds a deterministic library in a fresh database (no media files: search reads
only SQLite) and times common queries. Rows go in through the canonical tables, so
the triggers build the index exactly as the app does.

    uv run python -m openworld_moments.search.benchmark --clips 10000 --json

Default shape for 10,000 clips: 1,000 sessions, 30,000 events (half confirmed or
corrected through review decisions), 50,000 transcript spans and 100 projects.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openworld_moments.search.filters import SearchFilters, SearchRequest
from openworld_moments.search.service import SearchService
from openworld_moments.storage import Database, transaction

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
EVENT_TYPES = (
    "openworld.wanted_level_changed",
    "openworld.mission_completed",
    "openworld.mission_failed",
    "openworld.vehicle_crash",
    "openworld.busted",
    "openworld.wasted",
)
OCR_TEXT = (
    "WANTED",
    "MISSION PASSED",
    "MISSION FAILED",
    "BUSTED",
    "WASTED",
    "Lose the cops",
    "Go to the safehouse",
    "Heist complete",
)
SPEECH = (
    "no way that just happened",
    "police chase down the highway",
    "watch out for the bike",
    "the heist went perfectly",
    "lose them in the tunnel",
    "we need a faster car",
    "that crash was brutal",
    "mission complete let's go",
    "over here quick",
    "get to the airport",
)
SOURCES = ("xbox", "playstation", "obs", "capture_card", "phone_upload", "other")

#: Common queries timed by the benchmark (query text, filters).
QUERIES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("wanted", {}),
    ("heist", {}),
    ("police chase", {}),
    ('"no way"', {}),
    ("mission comp*", {}),
    ("crash -bike", {}),
    ("busted", {"kinds": ["event"], "min_confidence": 0.8}),
    ("", {"kinds": ["event"], "review_states": ["confirmed"]}),
    ("", {"event_types": ["openworld.vehicle_crash"], "source_kinds": ["xbox"]}),
    (
        "airport",
        {"occurred_from": "2026-03-01T00:00:00Z", "occurred_to": "2026-06-30T23:59:59Z"},
    ),
)


def _ulid(prefix: str, n: int) -> str:
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def build_library(
    database: Database,
    *,
    clips: int = 10_000,
    clips_per_session: int = 10,
    events_per_clip: int = 3,
    spans_per_clip: int = 5,
    seed: int = 26,
) -> dict[str, int]:
    """Fill ``database`` with a deterministic synthetic library. Returns row counts."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not security
    sessions = max(1, clips // clips_per_session)
    counts = {"clips": clips, "sessions": sessions, "events": 0, "transcripts": 0, "projects": 0}
    with contextlib.closing(database.connect()) as conn, transaction(conn):
        for s in range(sessions):
            month, day = 1 + s * 12 // sessions, 1 + s % 28
            started = f"2026-{month:02d}-{day:02d}T{s % 24:02d}:00:00Z"
            conn.execute(
                "INSERT INTO sessions (id, title, started_at, review_state, created_at) "
                "VALUES (?, ?, ?, 'unreviewed', ?)",
                (_ulid("ses", s + 1), f"Session {s + 1} {rng.choice(SPEECH)}", started, started),
            )
        for c in range(clips):
            sid = _ulid("ses", c // clips_per_session + 1)
            aid = _ulid("ast", c + 1)
            duration = rng.randint(20_000, 120_000)
            source = SOURCES[c % len(SOURCES)]
            conn.execute(
                "INSERT INTO media_assets (id, sha256, original_name, source_kind, import_mode, "
                "duration_ms, container, created_at, captured_at, captured_at_confidence, "
                "captured_at_basis_json) VALUES (?, ?, ?, ?, 'reference', ?, 'mp4', ?, ?, 0.9, "
                "'[\"filename\"]')",
                (
                    aid,
                    hashlib.sha256(aid.encode()).hexdigest(),
                    f"Capture {c + 1:05d} {rng.choice(OCR_TEXT).lower()}.mp4",
                    source,
                    duration,
                    "2026-01-01T00:00:00Z",
                    f"2026-{1 + c * 12 // clips:02d}-{1 + c % 28:02d}T12:00:00Z",
                ),
            )
            order = c % clips_per_session
            conn.execute(
                "INSERT INTO session_assets (session_id, asset_id, order_index, session_start_ms) "
                "VALUES (?, ?, ?, ?)",
                (sid, aid, order, order * 120_000),
            )
            base = order * 120_000
            for e in range(events_per_clip):
                n = c * events_per_clip + e + 1
                eid = _ulid("evt", n)
                start = base + rng.randint(0, duration - 2000)
                conn.execute(
                    "INSERT INTO events (id, session_id, asset_id, type, start_ms, end_ms, "
                    "confidence, attributes_json, evidence_json, source_kind, detector_id, "
                    "detector_version, review_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', "
                    "'detector', 'synthetic', '1.0.0', 'unreviewed')",
                    (
                        eid,
                        sid,
                        aid,
                        rng.choice(EVENT_TYPES),
                        start,
                        start + rng.randint(300, 2000),
                        round(rng.uniform(0.4, 1.0), 3),
                        json.dumps({"text": rng.choice(OCR_TEXT)}),
                    ),
                )
                conn.execute(
                    "INSERT INTO event_observations VALUES (?, ?, '{}', NULL, ?)",
                    (eid, sid, "2026-01-01T00:00:00Z"),
                )
                if n % 2 == 0:
                    conn.execute(
                        "INSERT INTO event_decisions VALUES (?, 1, ?)",
                        (
                            eid,
                            json.dumps(
                                {
                                    "revision": 1,
                                    "state": "confirmed" if n % 4 == 0 else "corrected",
                                    "type": rng.choice(EVENT_TYPES),
                                    "start_ms": start,
                                    "end_ms": start + 1500,
                                    "created_at": "2026-01-02T00:00:00Z",
                                }
                            ),
                        ),
                    )
                counts["events"] += 1
            for t in range(spans_per_clip):
                start = rng.randint(0, duration - 3000)
                conn.execute(
                    "INSERT INTO transcript_segments (session_id, start_ms, end_ms, speaker, text, "
                    "language, confidence, asset_id, source_start_ms, source_end_ms, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'en', ?, ?, ?, ?, ?)",
                    (
                        sid,
                        base + start,
                        base + start + 2500,
                        "player" if t % 3 == 0 else None,
                        rng.choice(SPEECH),
                        round(rng.uniform(0.6, 1.0), 3),
                        aid,
                        start,
                        start + 2500,
                        "2026-01-01T00:00:00Z",
                    ),
                )
                counts["transcripts"] += 1
        for p in range(max(1, sessions // 10)):
            pid = _ulid("prj", p + 1)
            conn.execute(
                "INSERT INTO stories (id, session_id, title, timeline_json, review_state, "
                "created_at, updated_at) VALUES (?, ?, ?, '{}', 'accepted', ?, ?)",
                (
                    pid,
                    _ulid("ses", p * 10 + 1),
                    f"Project {p + 1}: {rng.choice(SPEECH)}",
                    "2026-02-01T00:00:00Z",
                    "2026-02-01T00:00:00Z",
                ),
            )
            counts["projects"] += 1
    return counts


def time_queries(
    database: Database,
    *,
    repeats: int = 20,
    queries: tuple[tuple[str, dict[str, Any]], ...] = QUERIES,
) -> list[dict[str, Any]]:
    """Wall time of each query through SearchService (connection, query, facets, snippets)."""
    service = SearchService(database)
    rows = []
    for text, filters in queries:
        request = SearchRequest(query=text, filters=SearchFilters.model_validate(filters))
        service.search(request)  # warm the page cache
        samples = []
        total = 0
        for _ in range(repeats):
            started = time.perf_counter()
            total = service.search(request)["total"]
            samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
        rows.append(
            {
                "query": text,
                "filters": filters,
                "total": total,
                "median_ms": round(statistics.median(samples), 1),
                "p95_ms": round(samples[max(0, round(0.95 * len(samples)) - 1)], 1),
                "max_ms": round(samples[-1], 1),
            }
        )
    return rows


@contextlib.contextmanager
def _scratch() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="owm-search-bench-") as folder:
        yield Path(folder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time common searches on a synthetic library.")
    parser.add_argument("--clips", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    args = parser.parse_args(argv)
    with _scratch() as folder:
        database = Database.open(folder / "library.sqlite3")
        started = time.perf_counter()
        counts = build_library(database, clips=args.clips)
        build_s = time.perf_counter() - started
        timings = time_queries(database, repeats=args.repeats)
    report = {
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "library": counts,
        "build_seconds": round(build_s, 1),
        "queries": timings,
        "worst_p95_ms": max(t["p95_ms"] for t in timings),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{counts} built in {build_s:.1f} s on {report['machine']['platform']}")
        for t in timings:
            print(
                f"{t['p95_ms']:7.1f} ms p95  {t['median_ms']:7.1f} ms median  "
                f"{t['total']:6d} hits  {t['query']!r} {t['filters']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
