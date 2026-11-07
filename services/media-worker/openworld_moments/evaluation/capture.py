# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local replay over hash-addressed media. Private paths never enter reports."""

from __future__ import annotations

import contextlib
import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.inputs import content_hash
from openworld_moments.detectors.profiles import ProfileCatalog, digest
from openworld_moments.detectors.sdk import checkpoint
from openworld_moments.detectors.service import Analyzer
from openworld_moments.evaluation.service import MAX_DOCUMENT_BYTES, EvaluationError
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.media.tools import MediaTools
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, EventRepository


def capture(
    manifest: dict[str, Any],
    media_map: Path,
    tools: MediaTools,
    catalog: ProfileCatalog | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    manifest = normalize(load("evaluation", manifest))
    cancel = cancel or threading.Event()
    try:
        with media_map.open("rb") as stream:
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("size")
        paths = json.loads(raw)
        if not isinstance(paths, dict) or set(paths) != {c["sha256"] for c in manifest["clips"]}:
            raise ValueError("map")
        if any(not isinstance(v, str) or not Path(v).is_absolute() for v in paths.values()):
            raise ValueError("path")
    except (ValueError, OSError, RecursionError) as exc:
        raise EvaluationError(
            "evaluation.invalid_map",
            "Provide an explicit private map from every media hash to an absolute local file.",
        ) from exc
    catalog = catalog or ProfileCatalog()
    profile = catalog.load(manifest["profile"]["id"]).document()
    if profile["profile_version"] != manifest["profile"]["version"]:
        raise EvaluationError(
            "evaluation.profile_changed",
            "The installed profile version differs from the annotation manifest.",
        )
    detectors = []
    observed = []
    with tempfile.TemporaryDirectory(prefix="owm-eval-") as scratch:
        for index, clip in enumerate(manifest["clips"]):
            checkpoint(cancel)
            path = Path(paths[clip["sha256"]])
            if path.is_symlink() or not path.is_file():
                raise EvaluationError(
                    "evaluation.media_missing",
                    "An explicitly mapped local media file is unavailable.",
                )
            identity = path.stat()
            if content_hash(path, cancel) != clip["sha256"]:
                raise EvaluationError(
                    "evaluation.hash_mismatch", "Mapped media does not match its annotation hash."
                )
            database = Database.open(Path(scratch) / str(index) / "database.sqlite3")
            imported = Importer(database, tools).run_import(
                {"paths": [str(path)], "mode": "reference"},
                job_id=new_id("job"),
                cancel=cancel,
                progress=lambda *_: None,
            )
            if imported["totals"]["failed"] or imported["totals"]["imported"] != 1:
                raise EvaluationError(
                    "evaluation.import_failed", "A mapped evaluation clip could not be imported."
                )
            sessions = SessionService(database)
            sessions.recompute({})
            with contextlib.closing(database.connect()) as conn:
                sid = sessions.list_docs(conn, limit=1, offset=0)[0]["id"]
                row = conn.execute(
                    "SELECT duration_ms,width,height,rotation FROM media_assets LIMIT 1"
                ).fetchone()
            width, height = (row[2], row[1]) if row[3] in (90, 270) else (row[1], row[2])
            if (row[0], width, height) != (clip["duration_ms"], clip["width"], clip["height"]):
                raise EvaluationError(
                    "evaluation.metadata_mismatch",
                    "Media duration or upright resolution differs from the annotation manifest.",
                )
            analyzer = Analyzer(database, tools, DerivedMedia(database, tools), catalog=catalog)
            start = time.perf_counter()
            result = analyzer.run(
                {"session_id": sid, "profile_id": profile["id"], "locale": clip["locale"]},
                job_id=new_id("job"),
                cancel=cancel,
            )
            elapsed = round((time.perf_counter() - start) * 1000, 6)
            if any(o["status"] not in ("computed", "cached") for o in result["outcomes"]):
                raise EvaluationError(
                    "evaluation.incomplete",
                    "At least one detector was skipped or failed. Refusing incomplete evaluation.",
                )
            with contextlib.closing(database.connect()) as conn:
                docs = [normalize(e) for e in EventRepository(conn).list_for_session(sid)]
            if len(docs) > 500:
                raise EvaluationError(
                    "evaluation.too_many_events",
                    "This clip exceeds the bounded evaluation event count.",
                )
            for setting in profile["detectors"]:
                if setting.get("enabled", True):
                    detector = analyzer.registry[setting["id"]]()
                    descriptor = {"id": detector.id, "version": detector.version}
                    if descriptor not in detectors:
                        detectors.append(descriptor)
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (
                identity.st_size,
                identity.st_mtime_ns,
            ) or content_hash(path, cancel) != clip["sha256"]:
                raise EvaluationError(
                    "evaluation.media_changed",
                    "Mapped media changed during evaluation; results were discarded.",
                )
            observed.append(
                {
                    "sha256": clip["sha256"],
                    "processing_ms": elapsed,
                    "events": [{k: e[k] for k in ("type", "start_ms", "end_ms")} for e in docs],
                }
            )
    return normalize(
        load(
            "evaluation-observations",
            {
                "schema_version": "1.14",
                "manifest_sha256": digest(manifest),
                "profile": manifest["profile"],
                "detectors": sorted(detectors, key=lambda d: d["id"]),
                "clips": observed,
            },
        )
    )
