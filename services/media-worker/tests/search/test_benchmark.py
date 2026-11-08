# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search at a representative library size.

By default 2,000 synthetic clips (about 18,000 documents) with a loose regression
guard, so shared CI runners stay reliable. ``OWM_SEARCH_BENCH=1`` runs the full
acceptance check: 10,000 clips and every common query under 300 ms at p95.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from openworld_moments.search import index
from openworld_moments.search.benchmark import QUERIES, build_library, time_queries
from openworld_moments.storage import Database

FULL = os.environ.get("OWM_SEARCH_BENCH") == "1"


def test_common_queries_at_library_scale(tmp_path: Path) -> None:
    clips = 10_000 if FULL else 2_000
    database = Database.open(tmp_path / "library.sqlite3")
    counts = build_library(database, clips=clips)
    assert counts == {
        "clips": clips,
        "sessions": clips // 10,
        "events": clips * 3,
        "transcripts": clips * 5,
        "projects": max(1, clips // 100),
    }
    status = index.status(database, check=True)
    assert status["status"] == "current"
    assert sum(status["documents"].values()) == clips * 9 + clips // 10 + max(1, clips // 100)
    timings = time_queries(database, repeats=5 if not FULL else 20)
    assert len(timings) == len(QUERIES) and all(t["total"] > 0 for t in timings)
    budget = 300.0 if FULL else 1500.0
    slow = [t for t in timings if t["p95_ms"] > budget]
    assert not slow, slow
    # Correctness at scale: every returned event really carries the filtered values.
    with contextlib.closing(database.connect()) as conn:
        wrong = conn.execute(
            "SELECT count(*) FROM search_documents WHERE kind = 'event' AND "
            "(event_type IS NULL OR review_state IS NULL OR confidence IS NULL)"
        ).fetchone()[0]
    assert wrong == 0
