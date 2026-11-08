# SPDX-License-Identifier: AGPL-3.0-or-later
"""Versioned editor persistence. Every write is derived JSON; source media is read-only."""

from __future__ import annotations

import contextlib
import copy
import json
import sqlite3
import threading
from typing import Any, cast

from openworld_moments_contracts import ContractError, load, normalize
from openworld_moments_contracts.generated.project_schema import Project
from openworld_moments_contracts.versioning import SUPPORTED_VERSION
from pydantic import BaseModel, ConfigDict, Field

from openworld_moments.detectors.inputs import content_hash
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.ids import new_id
from openworld_moments.ingest.library import LibraryPaths, readable_source
from openworld_moments.review.service import layout_info
from openworld_moments.storage import (
    AssetRepository,
    Database,
    NotFoundError,
    StoryRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import Story
from openworld_moments.stories.algorithm import source_ranges

VERSION = str(SUPPORTED_VERSION)
MAX_BYTES = 4 * 1024 * 1024
ID = r"^ast_[0-9A-HJKMNP-TV-Z]{26}$"


class ProjectError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class SaveProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=9007199254740991)
    document: dict[str, Any]


class ManualProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=300)
    layout_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    start_ms: int = Field(ge=0, le=9007199254740991)
    end_ms: int = Field(ge=0, le=9007199254740991)


class RelinkProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=9007199254740991)
    bindings: dict[str, str] = Field(max_length=1000)
    confirm_replacements: list[str] = Field(default_factory=list, max_length=1000)


class ImportProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document: dict[str, Any]
    # Explicit choices only. Unmapped sources retain their edits and show relink state.
    bindings: dict[str, str] = Field(default_factory=dict, max_length=1000)
    confirm_replacements: list[str] = Field(default_factory=list, max_length=1000)


def canonical(doc: dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate(document: dict[str, Any]) -> dict[str, Any]:
    try:
        if len(canonical(document).encode()) > MAX_BYTES:
            raise ProjectError("project.too_large", "Project JSON exceeds 4 MiB.")
        return normalize(load("editor-project", document))
    except (ContractError, ValueError, TypeError, RecursionError) as exc:
        raise ProjectError("project.invalid", "Invalid or unsupported editor project.") from exc


def source_doc(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    asset = AssetRepository(conn).get(asset_id)
    return {
        "asset_id": asset.id,
        "sha256": asset.sha256,
        "original_name": asset.original_name,
        "duration_ms": asset.duration_ms,
    }


def migrate_project(conn: sqlite3.Connection, project: dict[str, Any]) -> dict[str, Any]:
    """Legacy EDL -> v1. Preserve timings and IDs; refuse unsupported edits, never flatten."""
    p = normalize(load("project", copy.deepcopy(project)))
    p["schema_version"] = VERSION
    if not p["tracks"]:
        p["tracks"] = [{"kind": "video", "segments": []}]
    ids = sorted({s["asset_id"] for t in p["tracks"] for s in t["segments"]})
    try:
        sources = [source_doc(conn, aid) for aid in ids]
    except NotFoundError as exc:
        raise ProjectError(
            "project.migration_source_missing",
            "Legacy project needs source metadata before migration.",
            409,
        ) from exc
    return validate(
        {
            "schema_version": VERSION,
            "model_version": 1,
            "project": p,
            "layout": {"aspect_ratio": "16:9"},
            "sources": sources,
        }
    )


def _same_edit(a: dict[str, Any], b: dict[str, Any]) -> bool:
    left, right = copy.deepcopy(a), copy.deepcopy(b)
    for doc in (left, right):
        doc["project"].pop("updated_at", None)
    return left == right


class ProjectService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.library = LibraryPaths.for_database(database.path)

    def page(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ProjectError("project.invalid_page", "Invalid project page.")
        with contextlib.closing(self.database.connect()) as conn:
            conn.execute("BEGIN")
            try:
                total = conn.execute("SELECT count(*) FROM stories").fetchone()[0]
                rows = conn.execute(
                    "SELECT s.id,s.title,s.session_id,s.updated_at,"
                    "coalesce(e.revision,0) AS revision "
                    "FROM stories s LEFT JOIN editor_projects e ON e.project_id=s.id "
                    "ORDER BY s.updated_at DESC,s.id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                return {"items": [dict(r) for r in rows], "total": total, "offset": offset}
            finally:
                conn.execute("ROLLBACK")

    def selection(self, session_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            key, duration = layout_info(conn, session_id)
            return {"layout_key": key, "duration_ms": duration}

    @staticmethod
    def _read(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM editor_projects WHERE project_id=?", (project_id,)
        ).fetchone()
        if row is None:
            story = StoryRepository(conn).get(project_id)
            doc = migrate_project(conn, normalize(story.timeline))
            return {"document": doc, "revision": 0, "recovery": None}
        return {
            "document": validate(json.loads(row["document_json"])),
            "revision": row["revision"],
            "recovery": validate(json.loads(row["recovery_json"]))
            if row["recovery_json"]
            else None,
        }

    def _availability(self, conn: sqlite3.Connection, doc: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for source in doc["sources"]:
            aid, status = source["asset_id"], "missing"
            try:
                asset = source_doc(conn, aid)
                if (
                    asset["sha256"] != source["sha256"]
                    or asset["duration_ms"] != source["duration_ms"]
                ):
                    status = "mismatch"
                elif not source.get("requires_relink", False):
                    path = readable_source(self.library, AssetRepository(conn).location(aid))
                    if path is not None and path.is_file():
                        status = "available_unverified"
            except NotFoundError:
                pass
            result.append({"asset_id": aid, "state": status})
        return result

    def get(self, project_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            conn.execute("BEGIN")
            try:
                state = self._read(conn, project_id)
                state["sources"] = self._availability(conn, state["document"])
                return state
            finally:
                conn.execute("ROLLBACK")

    @staticmethod
    def _check_bindings(
        conn: sqlite3.Connection, doc: dict[str, Any], previous: dict[str, Any] | None
    ) -> None:
        old = {s["asset_id"]: s for s in previous["sources"]} if previous else {}
        for source in doc["sources"]:
            # Unavailable imported bindings can be retained, but never silently replaced.
            if old.get(source["asset_id"]) == source:
                continue
            if source["asset_id"] in old:
                raise ProjectError(
                    "project.source_mismatch",
                    "Existing source bindings are immutable; import a confirmed replacement.",
                    409,
                )
            try:
                asset = source_doc(conn, source["asset_id"])
            except NotFoundError as exc:
                raise ProjectError(
                    "project.source_missing", "New source binding is not in this library."
                ) from exc
            if any(asset[k] != source[k] for k in ("sha256", "duration_ms", "original_name")):
                raise ProjectError(
                    "project.source_mismatch",
                    "Source identity differs; import with explicit replacement confirmation.",
                    409,
                )

    def _write(
        self,
        conn: sqlite3.Connection,
        doc: dict[str, Any],
        revision: int,
        *,
        imported: bool = False,
    ) -> dict[str, Any]:
        doc = copy.deepcopy(doc)
        doc["schema_version"] = VERSION
        doc["project"]["schema_version"] = VERSION
        pid = doc["project"]["id"]
        try:
            previous = self._read(conn, pid)
        except NotFoundError:
            previous = None
        current = previous["revision"] if previous else 0
        if revision != current:
            if previous and revision == current - 1 and _same_edit(doc, previous["document"]):
                return previous  # A lost acknowledgement can be retried without another write.
            raise ProjectError(
                "project.revision_conflict",
                "A newer save exists. Reload or export your unsaved edits.",
                409,
            )
        if previous:
            old = previous["document"]["project"]
            if any(doc["project"].get(k) != old.get(k) for k in ("id", "created_at", "session_id")):
                raise ProjectError(
                    "project.identity_changed",
                    "Project identity and session binding are immutable.",
                )
        if not imported:
            self._check_bindings(conn, doc, previous["document"] if previous else None)
        now = utc_now()
        doc = copy.deepcopy(doc)
        doc["project"]["updated_at"] = now
        project = cast(Project, load("project", doc["project"]))
        if previous:
            story = (
                StoryRepository(conn)
                .get(pid)
                .model_copy(
                    update={
                        "title": project.title,
                        "timeline": project,
                        "review_state": "edited",
                        "updated_at": now,
                    }
                )
            )
        else:
            story = Story(
                id=pid,
                session_id=doc["project"].get("session_id"),
                title=project.title,
                timeline=project,
                review_state="edited",
                created_at=project.created_at,
                updated_at=now,
            )
        StoryRepository(conn).save(story)
        recovery = previous["document"] if previous else None
        conn.execute(
            "INSERT INTO editor_projects(project_id,revision,document_json,recovery_json,saved_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,"
            "document_json=excluded.document_json,"
            "recovery_json=excluded.recovery_json,saved_at=excluded.saved_at",
            (pid, current + 1, canonical(doc), canonical(recovery) if recovery else None, now),
        )
        return {"document": doc, "revision": current + 1, "recovery": recovery}

    def save(self, project_id: str, request: SaveProject) -> dict[str, Any]:
        doc = validate(request.document)
        if doc["project"]["id"] != project_id:
            raise ProjectError("project.identity_changed", "Route and project ID differ.")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            # Saving cannot create arbitrary project IDs; create/import are explicit.
            StoryRepository(conn).get(project_id)
            return self._write(conn, doc, request.expected_revision)

    def create(self, session_id: str, request: ManualProject) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            key, duration = layout_info(conn, session_id)
            if key != request.layout_key:
                raise ProjectError(
                    "project.stale_session", "Session layout changed. Select the range again.", 409
                )
            if not 0 <= request.start_ms < request.end_ms <= duration:
                raise ProjectError(
                    "project.invalid_range", "Select a non-empty range inside the session."
                )
            members, position = [], 0
            for i, row in enumerate(
                conn.execute(
                    "SELECT sa.asset_id,a.duration_ms,sa.overlap_with_previous_ms "
                    "FROM session_assets sa JOIN media_assets a ON a.id=sa.asset_id "
                    "WHERE sa.session_id=? "
                    "ORDER BY sa.order_index LIMIT 1001",
                    (session_id,),
                )
            ):
                hidden = row[2] if i else 0
                size = max(0, row[1] - hidden)
                members.append(
                    {
                        "asset_id": row[0],
                        "start_ms": position,
                        "end_ms": position + size,
                        "hidden_ms": hidden,
                    }
                )
                position += size
            if len(members) > 1000:
                raise ProjectError(
                    "project.too_large", "Split this session before creating a project."
                )
            segments, position = [], 0
            for r in source_ranges(members, request.start_ms, request.end_ms):
                segments.append(
                    {
                        "id": new_id("seg"),
                        "asset_id": r["asset_id"],
                        "source_in_ms": r["source_in_ms"],
                        "source_out_ms": r["source_out_ms"],
                        "timeline_start_ms": position,
                        "crop": {"mode": "fit", "keyframes": []},
                    }
                )
                position += r["source_out_ms"] - r["source_in_ms"]
            now = utc_now()
            project = {
                "schema_version": VERSION,
                "id": new_id("prj"),
                "session_id": session_id,
                "title": request.title,
                "created_at": now,
                "updated_at": now,
                "tracks": [{"kind": "video", "segments": segments}],
                "captions": [],
                "overlays": [],
                "audio": {"gain_db": 0, "mute_ranges": []},
            }
            doc = validate(
                {
                    "schema_version": VERSION,
                    "model_version": 1,
                    "project": project,
                    "layout": {"aspect_ratio": "16:9"},
                    "sources": [
                        source_doc(conn, aid) for aid in sorted({s["asset_id"] for s in segments})
                    ],
                }
            )
            return self._write(conn, doc, 0)

    def export(self, project_id: str) -> dict[str, Any]:
        # A detached copy, no paths, host state, history, or executable references.
        return self.get(project_id)["document"]  # type: ignore[no-any-return]

    def _bind(
        self,
        conn: sqlite3.Connection,
        document: dict[str, Any],
        request: ImportProject | RelinkProject,
        cancel: threading.Event | None,
        *,
        detach_unmapped: bool = False,
    ) -> dict[str, Any]:
        doc = copy.deepcopy(document)
        known = {s["asset_id"] for s in doc["sources"]}
        if (
            not request.bindings.keys() <= known
            or not set(request.confirm_replacements) <= request.bindings.keys()
        ):
            raise ProjectError(
                "project.invalid_bindings",
                "Bindings and confirmations must name portable source IDs.",
            )
        cancel = cancel or threading.Event()
        mapped = {}
        for source in doc["sources"]:
            old_id = source["asset_id"]
            if old_id not in request.bindings:
                if detach_unmapped:
                    source["requires_relink"] = True
                continue
            aid = request.bindings[old_id]
            local = source_doc(conn, aid)
            path = readable_source(self.library, AssetRepository(conn).location(aid))
            if path is None:
                raise ProjectError("project.source_missing", "Selected source is unavailable.", 409)
            try:
                actual = content_hash(path, cancel)
            except AnalysisCancelled as exc:
                raise ProjectError("project.cancelled", "Project import cancelled.", 409) from exc
            except OSError as exc:
                raise ProjectError(
                    "project.source_missing", "Selected source cannot be read.", 409
                ) from exc
            if actual != local["sha256"]:
                raise ProjectError(
                    "project.source_changed",
                    "Selected file changed since import. Import it again.",
                    409,
                )
            if local["sha256"] != source["sha256"] and old_id not in request.confirm_replacements:
                raise ProjectError(
                    "project.confirm_replacement",
                    "Source hash differs. Confirm this source replacement explicitly.",
                    409,
                )
            if local["sha256"] != source["sha256"]:
                local["replaces_sha256"] = source["sha256"]
            mapped[old_id] = local
        for track in doc["project"]["tracks"]:
            for seg in track["segments"]:
                if seg["asset_id"] in mapped:
                    seg["asset_id"] = mapped[seg["asset_id"]]["asset_id"]
        # Deduplicate explicit mappings only when their provenance agrees.
        sources: dict[str, dict[str, Any]] = {}
        for source in doc["sources"]:
            new = mapped.get(source["asset_id"], source)
            if new["asset_id"] in sources and sources[new["asset_id"]] != new:
                raise ProjectError("project.invalid_bindings", "Conflicting source mappings.")
            sources[new["asset_id"]] = new
        doc["sources"] = list(sources.values())
        doc = validate(doc)
        if cancel.is_set():
            raise ProjectError("project.cancelled", "Project import cancelled.", 409)
        return doc

    def import_document(
        self, request: ImportProject, cancel: threading.Event | None = None
    ) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            doc = self._bind(
                conn, validate(request.document), request, cancel, detach_unmapped=True
            )
            p = doc["project"]
            p["id"], p["created_at"], p["updated_at"] = new_id("prj"), utc_now(), utc_now()
            p.pop("session_id", None)
            with transaction(conn):
                return self._write(conn, doc, 0, imported=True)

    def relink(
        self, project_id: str, request: RelinkProject, cancel: threading.Event | None = None
    ) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            state = self._read(conn, project_id)
            if state["revision"] != request.expected_revision:
                raise ProjectError(
                    "project.revision_conflict",
                    "A newer save exists. Reload before relinking.",
                    409,
                )
            doc = self._bind(conn, state["document"], request, cancel)
            # Hashing does not hold the write lock. Recheck revision atomically at commit.
            with transaction(conn):
                return self._write(conn, doc, request.expected_revision, imported=True)
