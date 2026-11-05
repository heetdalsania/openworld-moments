# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed repositories over the library database.

Assets, events, and jobs use the M01 contract models directly; every row read
back is re-validated through ``openworld_moments_contracts.load`` so storage can
never hand out a document that breaks its contract. Sessions, session
membership, and stories have no M01 contract yet and use the models below.

Repositories never open transactions themselves. Callers group writes with
``database.transaction(conn)`` so related changes commit or roll back together.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from openworld_moments_contracts import load
from openworld_moments_contracts.generated.event_schema import Event
from openworld_moments_contracts.generated.job_schema import Job
from openworld_moments_contracts.generated.media_asset_schema import MediaAsset
from openworld_moments_contracts.generated.project_schema import Project
from openworld_moments_contracts.versioning import SUPPORTED_VERSION
from pydantic import BaseModel, ConfigDict, Field

from openworld_moments.storage.database import StorageError, utc_now

SCHEMA_VERSION = str(SUPPORTED_VERSION)

JsonValue = Any


class NotFoundError(StorageError):
    """No row with the requested ID."""


class ConflictError(StorageError):
    """A uniqueness or reference rule rejected the write."""


class InUseError(ConflictError):
    """The row is still referenced and its delete policy is RESTRICT."""


def _dumps(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _loads(text: str | None) -> JsonValue:
    return None if text is None else json.loads(text)


def _dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _translate(exc: sqlite3.IntegrityError, *, delete: bool = False) -> StorageError:
    message = str(exc)
    if delete and "FOREIGN KEY" in message:
        return InUseError("still referenced by other records; remove those references first")
    return ConflictError(message)


def _insert(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    *,
    upsert: bool = False,
    keep: tuple[str, ...] = ("id",),
) -> None:
    """INSERT a row (or upsert on ``id``), mapping integrity errors to storage errors.

    Table and column names come from this module, never from callers' data.
    """
    columns = ", ".join(row)
    values = ", ".join(f":{k}" for k in row)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({values})"  # noqa: S608
    if upsert:
        updates = ", ".join(f"{k} = excluded.{k}" for k in row if k not in keep)
        sql += f" ON CONFLICT (id) DO UPDATE SET {updates}"
    try:
        conn.execute(sql, row)
    except sqlite3.IntegrityError as exc:
        raise _translate(exc) from exc


def _delete(conn: sqlite3.Connection, table: str, row_id: str, what: str) -> None:
    try:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
    except sqlite3.IntegrityError as exc:
        raise _translate(exc, delete=True) from exc
    if cur.rowcount == 0:
        raise NotFoundError(f"{what} {row_id} not found")


# -- models without an M01 contract ---------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Session(_Model):
    id: str = Field(pattern=r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")
    title: str = Field(min_length=1, max_length=300)
    started_at: str | None = None
    ended_at: str | None = None
    source_profile_id: str | None = None
    game_profile_id: str | None = None
    grouping_confidence: float | None = Field(default=None, ge=0, le=1)
    review_state: Literal["unreviewed", "confirmed", "corrected"] = "unreviewed"
    created_at: str


class SessionAsset(_Model):
    session_id: str
    asset_id: str
    order_index: int = Field(ge=0)
    session_start_ms: int = Field(ge=0)
    trim_in_ms: int = Field(default=0, ge=0)
    trim_out_ms: int | None = None
    overlap_with_previous_ms: int = Field(default=0, ge=0)
    alignment_confidence: float | None = Field(default=None, ge=0, le=1)


class Story(_Model):
    """A candidate or edited story. Its timeline is a Project (EDL) contract; IDs match."""

    id: str = Field(pattern=r"^prj_[0-9A-HJKMNP-TV-Z]{26}$")
    session_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    preset: Literal["moment", "short", "extended_short", "highlight", "compilation"] | None = None
    score: float | None = None
    score_components: dict[str, float] | None = None
    timeline: Project
    layout: dict[str, JsonValue] | None = None
    review_state: Literal["suggested", "accepted", "rejected", "edited"] = "suggested"
    created_at: str
    updated_at: str


# -- assets ---------------------------------------------------------------------------


class AssetRepository:
    """media_assets. Deleting an asset referenced by a session or event is refused."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(
        self,
        asset: MediaAsset,
        *,
        original_path: str | None = None,
        managed_path: str | None = None,
        source_profile_id: str | None = None,
    ) -> None:
        d = _dump_model(asset)
        capture = d.get("capture_time")
        video = d.get("video")
        audio = d.get("audio")
        _insert(
            self.conn,
            "media_assets",
            {
                "id": d["id"],
                "sha256": d["sha256"],
                "fast_hash": d.get("fast_hash"),
                "original_name": d["original_name"],
                "original_path": original_path,
                "managed_path": managed_path,
                "source_kind": d["source_kind"],
                "import_mode": d["import_mode"],
                "source_profile_id": source_profile_id,
                "captured_at": capture["captured_at"] if capture else None,
                "captured_at_confidence": capture["confidence"] if capture else None,
                "captured_at_basis_json": _dumps(capture["basis"]) if capture else None,
                "duration_ms": d["duration_ms"],
                "container": d["container"],
                "width": video["width"] if video else None,
                "height": video["height"] if video else None,
                "fps_num": video["frame_rate"]["num"] if video else None,
                "fps_den": video["frame_rate"]["den"] if video else None,
                "video_codec": video["codec"] if video else None,
                "pixel_format": video.get("pixel_format") if video else None,
                "color_metadata_json": _dumps(video["color"]) if video else None,
                "audio_streams_json": _dumps(audio) if audio is not None else None,
                "audio_codec": audio[0]["codec"] if audio else None,
                "created_at": d["created_at"],
                "missing_at": d.get("missing_at"),
            },
        )

    def get(self, asset_id: str) -> MediaAsset:
        row = self.conn.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"asset {asset_id} not found")
        return self._from_row(row)

    def find_by_sha256(self, sha256: str) -> MediaAsset | None:
        row = self.conn.execute("SELECT * FROM media_assets WHERE sha256 = ?", (sha256,)).fetchone()
        return None if row is None else self._from_row(row)

    def all(self) -> list[MediaAsset]:
        rows = self.conn.execute("SELECT * FROM media_assets ORDER BY created_at, id").fetchall()
        return [self._from_row(r) for r in rows]

    def original_path(self, asset_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT original_path FROM media_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"asset {asset_id} not found")
        return row["original_path"]  # type: ignore[no-any-return]

    def mark_missing(self, asset_id: str, when: str | None = None) -> None:
        cur = self.conn.execute(
            "UPDATE media_assets SET missing_at = ? WHERE id = ?", (when or utc_now(), asset_id)
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"asset {asset_id} not found")

    def delete(self, asset_id: str) -> None:
        _delete(self.conn, "media_assets", asset_id, "asset")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MediaAsset:
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": row["id"],
            "sha256": row["sha256"],
            "fast_hash": row["fast_hash"],
            "original_name": row["original_name"],
            "source_kind": row["source_kind"],
            "import_mode": row["import_mode"],
            "duration_ms": row["duration_ms"],
            "container": row["container"],
            "created_at": row["created_at"],
            "missing_at": row["missing_at"],
        }
        if row["captured_at"] is not None:
            doc["capture_time"] = {
                "captured_at": row["captured_at"],
                "confidence": row["captured_at_confidence"],
                "basis": _loads(row["captured_at_basis_json"]),
            }
        if row["video_codec"] is not None:
            doc["video"] = _drop_none(
                {
                    "codec": row["video_codec"],
                    "width": row["width"],
                    "height": row["height"],
                    "frame_rate": {"num": row["fps_num"], "den": row["fps_den"]},
                    "pixel_format": row["pixel_format"],
                    "color": _loads(row["color_metadata_json"]),
                }
            )
        if row["audio_streams_json"] is not None:
            doc["audio"] = _loads(row["audio_streams_json"])
        return load("media-asset", _drop_none(doc))  # type: ignore[return-value]


# -- sessions -------------------------------------------------------------------------


class SessionRepository:
    """sessions and session_assets.

    Deleting a session cascades its membership rows, events, and transcripts, but
    is refused while stories reference it.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, session: Session) -> None:
        _insert(self.conn, "sessions", session.model_dump())

    def get(self, session_id: str) -> Session:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"session {session_id} not found")
        return Session(**dict(row))

    def all(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at IS NULL, started_at, id"
        ).fetchall()
        return [Session(**dict(r)) for r in rows]

    def add_asset(self, link: SessionAsset) -> None:
        _insert(self.conn, "session_assets", link.model_dump())

    def remove_asset(self, session_id: str, asset_id: str) -> None:
        cur = self.conn.execute(
            "DELETE FROM session_assets WHERE session_id = ? AND asset_id = ?",
            (session_id, asset_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"asset {asset_id} is not in session {session_id}")

    def assets(self, session_id: str) -> list[SessionAsset]:
        rows = self.conn.execute(
            "SELECT * FROM session_assets WHERE session_id = ? ORDER BY order_index", (session_id,)
        ).fetchall()
        return [SessionAsset(**dict(r)) for r in rows]

    def delete(self, session_id: str) -> None:
        _delete(self.conn, "sessions", session_id, "session")


# -- events ---------------------------------------------------------------------------


class EventRepository:
    """events. Observations (detector/user) and suggestions (model) share one table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, event: Event) -> None:
        d = _dump_model(event)
        source = d["source"]
        frames = source.get("sampled_frames_ms")
        _insert(
            self.conn,
            "events",
            {
                "id": d["id"],
                "session_id": d["session_id"],
                "asset_id": d.get("asset_id"),
                "type": d["type"],
                "start_ms": d["start_ms"],
                "end_ms": d["end_ms"],
                "confidence": d["confidence"],
                "attributes_json": _dumps(d["attributes"]),
                "evidence_json": _dumps(d["evidence"]),
                "source_kind": source["kind"],
                "detector_id": source.get("detector_id"),
                "detector_version": source.get("detector_version"),
                "profile_id": source.get("profile_id"),
                "profile_version": source.get("profile_version"),
                "model_id": source.get("model_id"),
                "prompt_version": source.get("prompt_version"),
                "sampled_frames_json": _dumps(frames) if frames is not None else None,
                "review_state": d["review_state"],
            },
        )

    def get(self, event_id: str) -> Event:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"event {event_id} not found")
        return self._from_row(row)

    def list_for_session(self, session_id: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY start_ms, id", (session_id,)
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def set_review_state(
        self, event_id: str, state: Literal["unreviewed", "confirmed", "corrected", "rejected"]
    ) -> None:
        try:
            cur = self.conn.execute(
                "UPDATE events SET review_state = ? WHERE id = ?", (state, event_id)
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc
        if cur.rowcount == 0:
            raise NotFoundError(f"event {event_id} not found")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Event:
        kind = row["source_kind"]
        source: dict[str, Any]
        if kind == "detector":
            source = _drop_none(
                {
                    "kind": "detector",
                    "detector_id": row["detector_id"],
                    "detector_version": row["detector_version"],
                    "profile_id": row["profile_id"],
                    "profile_version": row["profile_version"],
                }
            )
        elif kind == "model":
            source = {
                "kind": "model",
                "model_id": row["model_id"],
                "prompt_version": row["prompt_version"],
                "sampled_frames_ms": _loads(row["sampled_frames_json"]),
            }
        else:
            source = {"kind": "user"}
        doc = _drop_none(
            {
                "schema_version": SCHEMA_VERSION,
                "id": row["id"],
                "session_id": row["session_id"],
                "asset_id": row["asset_id"],
                "type": row["type"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
                "confidence": row["confidence"],
                "attributes": _loads(row["attributes_json"]),
                "evidence": _loads(row["evidence_json"]),
                "source": source,
                "review_state": row["review_state"],
            }
        )
        return load("event", doc)  # type: ignore[return-value]


# -- jobs -----------------------------------------------------------------------------


class JobRepository:
    """jobs. ``save`` inserts or replaces the whole job document."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, job: Job) -> None:
        d = _dump_model(job)
        progress = d.get("progress")
        row = {
            "id": d["id"],
            "kind": d["kind"],
            "state": d["state"],
            "progress_done": progress["done"] if progress else None,
            "progress_total": progress["total"] if progress else None,
            "message": d.get("message"),
            "error_json": _dumps(d["error"]) if "error" in d else None,
            "correlation_id": d.get("correlation_id"),
            "created_at": d["created_at"],
            "started_at": d.get("started_at"),
            "finished_at": d.get("finished_at"),
        }
        _insert(self.conn, "jobs", row, upsert=True, keep=("id",))

    def get(self, job_id: str) -> Job:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"job {job_id} not found")
        return self._from_row(row)

    def list_unfinished(self) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE state NOT IN ('ready', 'cancelled', 'failed') "
            "ORDER BY created_at, id"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        progress = (
            {"done": row["progress_done"], "total": row["progress_total"]}
            if row["progress_total"] is not None
            else None
        )
        doc = _drop_none(
            {
                "schema_version": SCHEMA_VERSION,
                "id": row["id"],
                "kind": row["kind"],
                "state": row["state"],
                "progress": progress,
                "message": row["message"],
                "error": _loads(row["error_json"]),
                "correlation_id": row["correlation_id"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
        )
        return load("job", doc)  # type: ignore[return-value]


# -- stories --------------------------------------------------------------------------


class StoryRepository:
    """stories. The timeline is stored as a canonical Project document."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, story: Story) -> None:
        if story.timeline.id != story.id:
            raise ConflictError("story id must equal its timeline project id")
        components = story.score_components
        row = {
            "id": story.id,
            "session_id": story.session_id,
            "title": story.title,
            "preset": story.preset,
            "score": story.score,
            "score_components_json": _dumps(components) if components is not None else None,
            "timeline_json": _dumps(_dump_model(story.timeline)),
            "layout_json": _dumps(story.layout) if story.layout is not None else None,
            "review_state": story.review_state,
            "created_at": story.created_at,
            "updated_at": story.updated_at,
        }
        _insert(self.conn, "stories", row, upsert=True, keep=("id", "created_at"))

    def get(self, story_id: str) -> Story:
        row = self.conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"story {story_id} not found")
        return Story(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            preset=row["preset"],
            score=row["score"],
            score_components=_loads(row["score_components_json"]),
            timeline=load("project", _loads(row["timeline_json"])),  # type: ignore[arg-type]
            layout=_loads(row["layout_json"]),
            review_state=row["review_state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def delete(self, story_id: str) -> None:
        _delete(self.conn, "stories", story_id, "story")


# -- settings -------------------------------------------------------------------------


class SettingsRepository:
    """settings: small JSON values keyed by name. Never store secrets or footage here."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        row = self.conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def set(self, key: str, value: JsonValue) -> None:
        try:
            self.conn.execute(
                "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, _dumps(value), utc_now()),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def all(self) -> dict[str, JsonValue]:
        rows = self.conn.execute("SELECT key, value_json FROM settings ORDER BY key").fetchall()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}
