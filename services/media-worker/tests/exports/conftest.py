# SPDX-License-Identifier: AGPL-3.0-or-later
"""A saved project with events, captions and every unsupported operation (M27)."""

from __future__ import annotations

import contextlib
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.exports.service import Exporter
from openworld_moments.storage import Database, transaction
from tests.privacy.helpers import acknowledge

SES = "ses_01JCBQ00000000000000000002"
AST = "ast_01JCBQ00000000000000000001"
AST2 = "ast_01JCBQ00000000000000000014"
PRJ = "prj_01JCBQ00000000000000000005"
SHA = "a" * 64
SHA2 = "b" * 64
GOLDENS = Path(__file__).parent / "goldens"
REGION = [0.78, 0.02, 0.2, 0.12]
WANTED = "openworld.wanted_level_changed"

DOCUMENT: dict[str, Any] = {
    "schema_version": "1.19",
    "model_version": 1,
    "project": {
        "schema_version": "1.19",
        "id": PRJ,
        "title": 'Six-star escape: "Café" run',
        "session_id": SES,
        "created_at": "2026-11-20T05:40:10Z",
        "updated_at": "2026-11-20T05:45:00Z",
        "tracks": [
            {
                "kind": "video",
                "segments": [
                    {
                        "id": "seg_01JCBQ00000000000000000006",
                        "asset_id": AST,
                        "source_in_ms": 12500,
                        "source_out_ms": 44800,
                        "timeline_start_ms": 0,
                        "crop": {
                            "mode": "safe",
                            "keyframes": [{"at_ms": 0, "region": [0.21875, 0, 0.5625, 1]}],
                        },
                        "vertical_crop": {
                            "layout_version": 1,
                            "strategy": "keyed",
                            "background": "solid",
                            "keyframes": [
                                {"at_ms": 0, "region": [0.1, 0, 0.3, 1]},
                                {"at_ms": 1000, "region": [0.5, 0, 0.3, 1]},
                            ],
                        },
                    },
                    {
                        "id": "seg_01JCBQ00000000000000000007",
                        "asset_id": AST,
                        "source_in_ms": 50000,
                        "source_out_ms": 61000,
                        "timeline_start_ms": 32300,
                        "crop": {"mode": "fit", "keyframes": []},
                    },
                ],
            }
        ],
        "captions": [
            {"start_ms": 1000, "end_ms": 2500, "text": "Here we go & <go> → 🚗"},
            {"start_ms": 3000, "end_ms": 4250, "text": "=SUM(A1) 你好\nsecond line"},
        ],
        "overlays": [
            {"kind": "blur", "start_ms": 0, "end_ms": 5000, "region": [0.0, 0.0, 0.25, 0.08]},
            {
                "kind": "text",
                "start_ms": 0,
                "end_ms": 1000,
                "region": [0, 0, 1, 0.1],
                "text": "Title",
            },
        ],
        "audio": {
            "gain_db": -3.5,
            "mute_ranges": [{"start_ms": 20000, "end_ms": 21000}],
            "gain_ranges": [{"start_ms": 0, "end_ms": 1000, "gain_db": -5}],
        },
    },
    "layout": {"aspect_ratio": "16:9"},
    "sources": [
        {
            "asset_id": AST,
            "sha256": SHA,
            "original_name": "Capture 01 — Café.mp4",
            "duration_ms": 120000,
        }
    ],
}


class Fixture:
    def __init__(self, database: Database, media: Path) -> None:
        self.database = database
        self.media = media
        self.exporter = Exporter(database)

    def sql(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            conn.execute(statement, params)

    def save(self, document: dict[str, Any], revision: int = 3) -> None:
        self.sql(
            "INSERT OR REPLACE INTO editor_projects (project_id, revision, document_json, "
            "recovery_json, saved_at) VALUES (?, ?, ?, NULL, '2026-11-21T11:00:00.000Z')",
            (PRJ, revision, json.dumps(document)),
        )

        self.sql(
            "UPDATE stories SET timeline_json=? WHERE id=?", (json.dumps(document["project"]), PRJ)
        )

    def export(self, fmt: str, **options: Any) -> dict[str, Any]:
        acknowledge(self.database, PRJ)
        return self.exporter.project(PRJ, fmt, **options)


def build(database: Database, media: Path) -> Fixture:
    fixture = Fixture(database, media)
    source = media / "Capture 01 — Café.mp4"
    source.write_bytes(b"synthetic source bytes")
    fixture.sql(
        "INSERT INTO sessions (id, title, started_at, review_state, created_at) VALUES "
        "(?, 'Evening session', '2026-11-20T10:14:22Z', 'unreviewed', '2026-11-20T05:40:10Z')",
        (SES,),
    )
    fixture.sql(
        "INSERT INTO media_assets (id, sha256, original_name, original_path, source_kind, "
        "import_mode, duration_ms, container, created_at, size_bytes, video_codec, width, "
        "height, fps_num, fps_den, color_metadata_json) VALUES "
        "(?, ?, 'Capture 01 — Café.mp4', ?, 'xbox', 'reference', 120000, 'mp4', "
        "'2026-11-20T10:20:00Z', ?, 'h264', 1920, 1080, 60, 1, '{\"hdr\": false}')",
        (AST, SHA, str(source), source.stat().st_size),
    )
    fixture.sql(
        "INSERT INTO session_assets (session_id, asset_id, order_index, session_start_ms) "
        "VALUES (?, ?, 0, 0)",
        (SES, AST),
    )
    fixture.sql(
        "INSERT INTO stories (id, session_id, title, timeline_json, review_state, created_at, "
        "updated_at) VALUES (?, ?, 'Six-star escape', '{}', 'edited', '2026-11-20T05:40:10Z', "
        "'2026-11-20T05:45:00Z')",
        (PRJ, SES),
    )

    def event(
        eid: str, type_: str, start: int, end: int, confidence: float, text: str | None
    ) -> None:
        fixture.sql(
            "INSERT INTO events (id, session_id, asset_id, type, start_ms, end_ms, confidence, "
            "attributes_json, evidence_json, source_kind, detector_id, detector_version, "
            "profile_id, profile_version, review_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "'detector', 'wanted-stars', '0.3.0', 'open-world-vi-1080p-en', '1.0.0', "
            "'unreviewed')",
            (
                eid,
                SES,
                AST,
                type_,
                start,
                end,
                confidence,
                json.dumps({"text": text} if text else {}),
                json.dumps(
                    [{"kind": "region_template", "region": [0.78, 0.02, 0.2, 0.12], "score": 0.9}]
                ),
            ),
        )

    event(
        "evt_01JCBQ00000000000000000031",
        "openworld.wanted_level_changed",
        20000,
        22000,
        0.97,
        "WANTED",
    )
    event("evt_01JCBQ00000000000000000032", "openworld.vehicle_crash", 5000, 6000, 0.6, None)
    event("evt_01JCBQ00000000000000000033", "openworld.busted", 52000, 53000, 0.8, "BUSTED")
    event("evt_01JCBQ00000000000000000034", "openworld.wasted", 40000, 41000, 0.5, None)
    key_row = None
    from openworld_moments.review.service import layout_info

    with contextlib.closing(database.connect()) as conn:
        key_row, _ = layout_info(conn, SES)
    for eid in ("31", "32", "33", "34"):
        fixture.sql(
            "INSERT INTO event_observations VALUES (?, ?, '{}', ?, '2026-11-21T09:00:00Z')",
            (f"evt_01JCBQ000000000000000000{eid}", SES, key_row),
        )
    decisions = {
        "31": ("confirmed", "openworld.wanted_level_changed", 20000, 22000),
        "33": ("corrected", "openworld.busted", 52500, 53500),
        "34": ("rejected", "openworld.wasted", 40000, 41000),
    }
    for eid, (state, type_, start, end) in decisions.items():
        fixture.sql(
            "INSERT INTO event_decisions VALUES (?, 1, ?)",
            (
                f"evt_01JCBQ000000000000000000{eid}",
                json.dumps(
                    {
                        "revision": 1,
                        "state": state,
                        "type": type_,
                        "start_ms": start,
                        "end_ms": end,
                        "created_at": "2026-11-21T10:00:00Z",
                    }
                ),
            ),
        )
    fixture.save(copy.deepcopy(DOCUMENT))
    acknowledge(database, PRJ)
    return fixture


@pytest.fixture
def project(tmp_path: Path) -> Fixture:
    media = tmp_path / "media"
    media.mkdir()
    return build(Database.open(tmp_path / "library" / "database.sqlite3"), media)
