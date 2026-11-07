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
from dataclasses import dataclass
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


def _delete(conn: sqlite3.Connection, table: str, row_id: str | int, what: str) -> None:
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
    #: How the session was grouped (contract ``SessionGrouping``), since 0008.
    grouping: dict[str, JsonValue] | None = None
    updated_at: str | None = None


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


class AssetLocation(_Model):
    """Where an asset's bytes live. Paths are local data: never log them."""

    id: str
    import_mode: Literal["reference", "managed"]
    original_path: str | None
    managed_path: str | None
    size_bytes: int | None
    missing_at: str | None


class AssetImport(_Model):
    """Provenance: one place an asset's bytes were imported from."""

    asset_id: str
    import_mode: Literal["reference", "managed"]
    source_kind: str
    source_path: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int
    job_id: str | None = None
    first_seen_at: str
    last_seen_at: str


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
        container_created_at: str | None = None,
    ) -> None:
        d = _dump_model(asset)
        capture = d.get("capture_time")
        video = d.get("video")
        audio = d.get("audio")
        avg = video.get("average_frame_rate") if video else None
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
                "container_created_at": container_created_at,
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
                "rotation": video.get("rotation") if video else None,
                "avg_fps_num": avg["num"] if avg else None,
                "avg_fps_den": avg["den"] if avg else None,
                "variable_frame_rate": (
                    int(video["variable_frame_rate"])
                    if video and "variable_frame_rate" in video
                    else None
                ),
                "audio_streams_json": _dumps(audio) if audio is not None else None,
                "audio_codec": audio[0]["codec"] if audio else None,
                "size_bytes": d.get("size_bytes"),
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

    def query(
        self,
        *,
        missing: bool | None = None,
        limit: int = 200,
        offset: int = 0,
        newest: bool = False,
        after: str | None = None,
    ) -> list[MediaAsset]:
        """Assets oldest first (``newest``: newest first). ``missing`` filters on whether
        ``missing_at`` is set. ``after`` is an asset ID: only assets after it in this order
        are returned (keyset pagination, stable while new assets arrive). Raises
        NotFoundError for an unknown ``after``."""
        clauses = {None: [], True: ["missing_at IS NOT NULL"], False: ["missing_at IS NULL"]}[
            missing
        ]
        params: list[Any] = []
        if after is not None:
            anchor = self.conn.execute(
                "SELECT created_at, id FROM media_assets WHERE id = ?", (after,)
            ).fetchone()
            if anchor is None:
                raise NotFoundError(f"asset {after} not found")
            clauses.append("(created_at, id) < (?, ?)" if newest else "(created_at, id) > (?, ?)")
            params += [anchor["created_at"], anchor["id"]]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "created_at DESC, id DESC" if newest else "created_at, id"
        rows = self.conn.execute(
            f"SELECT * FROM media_assets {where} "  # noqa: S608 - fixed fragments
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def locations(self) -> list[AssetLocation]:
        """Where every asset's bytes should be, for the missing-source check."""
        rows = self.conn.execute(
            "SELECT id, import_mode, original_path, managed_path, size_bytes, missing_at "
            "FROM media_assets ORDER BY created_at, id"
        ).fetchall()
        return [AssetLocation(**dict(r)) for r in rows]

    def location(self, asset_id: str) -> AssetLocation:
        row = self.conn.execute(
            "SELECT id, import_mode, original_path, managed_path, size_bytes, missing_at "
            "FROM media_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"asset {asset_id} not found")
        return AssetLocation(**dict(row))

    def set_original_path(self, asset_id: str, path: str) -> None:
        """Point a referenced asset at a verified new location and clear ``missing_at``."""
        cur = self.conn.execute(
            "UPDATE media_assets SET original_path = ?, missing_at = NULL WHERE id = ?",
            (path, asset_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"asset {asset_id} not found")

    def set_fast_hash(self, asset_id: str, value: str) -> None:
        cur = self.conn.execute(
            "UPDATE media_assets SET fast_hash = ? WHERE id = ?", (value, asset_id)
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"asset {asset_id} not found")

    def ids_by_fast_hash(self, value: str, size_bytes: int) -> list[str]:
        """Assets that may hold exactly these bytes: same fast hash and size (or unknown size)."""
        rows = self.conn.execute(
            "SELECT id FROM media_assets WHERE fast_hash = ? "
            "AND (size_bytes IS NULL OR size_bytes = ?) ORDER BY created_at, id",
            (value, size_bytes),
        ).fetchall()
        return [str(r["id"]) for r in rows]

    def ids_with_duration(self, low_ms: int, high_ms: int, *, exclude: str) -> list[str]:
        """Video assets whose duration lies in [low_ms, high_ms], except ``exclude``."""
        rows = self.conn.execute(
            "SELECT id FROM media_assets WHERE duration_ms BETWEEN ? AND ? AND id <> ? "
            "AND video_codec IS NOT NULL ORDER BY created_at, id",
            (low_ms, high_ms, exclude),
        ).fetchall()
        return [str(r["id"]) for r in rows]

    def ids(self) -> list[str]:
        rows = self.conn.execute("SELECT id FROM media_assets ORDER BY created_at, id").fetchall()
        return [str(r["id"]) for r in rows]

    def clear_missing(self, asset_id: str) -> None:
        cur = self.conn.execute(
            "UPDATE media_assets SET missing_at = NULL WHERE id = ?", (asset_id,)
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"asset {asset_id} not found")

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
            "size_bytes": row["size_bytes"],
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
                    "rotation": row["rotation"],
                    "average_frame_rate": (
                        {"num": row["avg_fps_num"], "den": row["avg_fps_den"]}
                        if row["avg_fps_num"] is not None
                        else None
                    ),
                    "variable_frame_rate": (
                        bool(row["variable_frame_rate"])
                        if row["variable_frame_rate"] is not None
                        else None
                    ),
                }
            )
        if row["audio_streams_json"] is not None:
            doc["audio"] = _loads(row["audio_streams_json"])
        return load("media-asset", _drop_none(doc))  # type: ignore[return-value]


class AssetImportRepository:
    """asset_imports. One row per (asset, source path); re-imports refresh it."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(
        self,
        *,
        asset_id: str,
        import_mode: str,
        source_kind: str,
        source_path: str,
        size_bytes: int,
        mtime_ns: int,
        job_id: str | None,
        when: str | None = None,
    ) -> None:
        now = when or utc_now()
        try:
            self.conn.execute(
                "INSERT INTO asset_imports (asset_id, import_mode, source_kind, source_path, "
                "size_bytes, mtime_ns, job_id, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (asset_id, source_path) DO UPDATE SET "
                "import_mode = excluded.import_mode, source_kind = excluded.source_kind, "
                "size_bytes = excluded.size_bytes, mtime_ns = excluded.mtime_ns, "
                "job_id = excluded.job_id, last_seen_at = excluded.last_seen_at",
                (
                    asset_id,
                    import_mode,
                    source_kind,
                    source_path,
                    size_bytes,
                    mtime_ns,
                    job_id,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def for_asset(self, asset_id: str) -> list[AssetImport]:
        rows = self.conn.execute(
            "SELECT asset_id, import_mode, source_kind, source_path, size_bytes, mtime_ns, "
            "job_id, first_seen_at, last_seen_at FROM asset_imports WHERE asset_id = ? "
            "ORDER BY first_seen_at, id",
            (asset_id,),
        ).fetchall()
        return [AssetImport(**dict(r)) for r in rows]

    def count(self) -> int:
        return int(self.conn.execute("SELECT count(*) FROM asset_imports").fetchone()[0])


FingerprintKind = Literal["fast", "frames", "audio"]


class StoredFingerprint(_Model):
    asset_id: str
    kind: FingerprintKind
    algorithm: str
    version: int = Field(ge=1)
    data: dict[str, JsonValue]
    computed_at: str


class FingerprintRepository:
    """asset_fingerprints: one versioned fingerprint per (asset, kind); cascades with the asset."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def put(self, fp: StoredFingerprint) -> None:
        try:
            self.conn.execute(
                "INSERT INTO asset_fingerprints (asset_id, kind, algorithm, version, data_json, "
                "computed_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (asset_id, kind) DO UPDATE SET "
                "algorithm = excluded.algorithm, version = excluded.version, "
                "data_json = excluded.data_json, computed_at = excluded.computed_at",
                (fp.asset_id, fp.kind, fp.algorithm, fp.version, _dumps(fp.data), fp.computed_at),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def for_asset(self, asset_id: str) -> dict[str, StoredFingerprint]:
        rows = self.conn.execute(
            "SELECT * FROM asset_fingerprints WHERE asset_id = ?", (asset_id,)
        ).fetchall()
        return {r["kind"]: self._from_row(r) for r in rows}

    def delete(self, asset_id: str, kind: FingerprintKind) -> None:
        self.conn.execute(
            "DELETE FROM asset_fingerprints WHERE asset_id = ? AND kind = ?", (asset_id, kind)
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredFingerprint:
        return StoredFingerprint(
            asset_id=row["asset_id"],
            kind=row["kind"],
            algorithm=row["algorithm"],
            version=row["version"],
            data=_loads(row["data_json"]),
            computed_at=row["computed_at"],
        )


DerivedKind = Literal["proxy", "filmstrip", "waveform"]


class DerivedArtifactRow(_Model):
    """One derived artifact (M08). ``relpath`` is relative to the library folder."""

    asset_id: str
    kind: DerivedKind
    status: Literal["ready", "failed"]
    cache_key: str = Field(min_length=64, max_length=64)
    recipe: dict[str, JsonValue]
    info: dict[str, JsonValue] | None = None
    relpath: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    created_at: str | None = None
    last_error: dict[str, JsonValue] | None = None
    updated_at: str


class DerivedArtifactRepository:
    """derived_artifacts: which derived file is current per (asset, kind); cascades with
    the asset. Rows never delete files; the derived-media service does."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, asset_id: str, kind: DerivedKind) -> DerivedArtifactRow | None:
        row = self.conn.execute(
            "SELECT * FROM derived_artifacts WHERE asset_id = ? AND kind = ?", (asset_id, kind)
        ).fetchone()
        return self._from_row(row) if row else None

    def for_asset(self, asset_id: str) -> dict[str, DerivedArtifactRow]:
        rows = self.conn.execute(
            "SELECT * FROM derived_artifacts WHERE asset_id = ?", (asset_id,)
        ).fetchall()
        return {r["kind"]: self._from_row(r) for r in rows}

    def put(self, row: DerivedArtifactRow) -> None:
        """Insert or replace the row for (asset, kind)."""
        try:
            self.conn.execute(
                "INSERT INTO derived_artifacts (asset_id, kind, status, cache_key, recipe_json, "
                "info_json, relpath, size_bytes, sha256, created_at, last_error_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (asset_id, kind) DO UPDATE SET status = excluded.status, "
                "cache_key = excluded.cache_key, "
                "recipe_json = excluded.recipe_json, info_json = excluded.info_json, "
                "relpath = excluded.relpath, size_bytes = excluded.size_bytes, "
                "sha256 = excluded.sha256, created_at = excluded.created_at, "
                "last_error_json = excluded.last_error_json, updated_at = excluded.updated_at",
                (
                    row.asset_id,
                    row.kind,
                    row.status,
                    row.cache_key,
                    _dumps(row.recipe),
                    _dumps(row.info) if row.info is not None else None,
                    row.relpath,
                    row.size_bytes,
                    row.sha256,
                    row.created_at,
                    _dumps(row.last_error) if row.last_error is not None else None,
                    row.updated_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def record_failure(
        self,
        asset_id: str,
        kind: DerivedKind,
        *,
        cache_key: str,
        recipe: dict[str, JsonValue],
        error: dict[str, JsonValue],
    ) -> None:
        """Remember a failed attempt. A previous ready artifact stays current."""
        now = utc_now()
        existing = self.get(asset_id, kind)
        if existing is not None and existing.status == "ready":
            self.conn.execute(
                "UPDATE derived_artifacts SET last_error_json = ?, updated_at = ? "
                "WHERE asset_id = ? AND kind = ?",
                (_dumps(error), now, asset_id, kind),
            )
            return
        self.put(
            DerivedArtifactRow(
                asset_id=asset_id,
                kind=kind,
                status="failed",
                cache_key=cache_key,
                recipe=recipe,
                last_error=error,
                updated_at=now,
            )
        )

    def relpaths(self) -> list[str]:
        """Stored paths of every artifact (current ones, kept by cleanup)."""
        rows = self.conn.execute(
            "SELECT relpath FROM derived_artifacts WHERE relpath IS NOT NULL"
        ).fetchall()
        return [r["relpath"] for r in rows]

    def delete(self, asset_id: str, kind: DerivedKind) -> None:
        self.conn.execute(
            "DELETE FROM derived_artifacts WHERE asset_id = ? AND kind = ?", (asset_id, kind)
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DerivedArtifactRow:
        return DerivedArtifactRow(
            asset_id=row["asset_id"],
            kind=row["kind"],
            status=row["status"],
            cache_key=row["cache_key"],
            recipe=_loads(row["recipe_json"]),
            info=_loads(row["info_json"]) if row["info_json"] is not None else None,
            relpath=row["relpath"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            created_at=row["created_at"],
            last_error=_loads(row["last_error_json"])
            if row["last_error_json"] is not None
            else None,
            updated_at=row["updated_at"],
        )


OverlapStatus = Literal["matched", "weak", "ambiguous", "no_match", "insufficient", "pending"]


class OverlapRow(_Model):
    """Alignment of clip B after clip A (M12). ``override_overlap_ms`` is the user's."""

    asset_a: str
    asset_b: str
    algorithm: str
    version: int = Field(ge=1)
    status: OverlapStatus
    offset_ms: int | None = None
    overlap_ms: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, JsonValue]
    computed_at: str
    override_overlap_ms: int | None = Field(default=None, ge=0)
    overridden_at: str | None = None


@dataclass(frozen=True)
class EffectiveOverlap:
    """What a session timeline uses for a pair: how much of B repeats A's end."""

    overlap_ms: int
    confidence: float | None
    source: Literal["user", "auto", "none"]


class OverlapRepository:
    """asset_overlaps: cached alignments per ordered pair, plus user overrides."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, asset_a: str, asset_b: str) -> OverlapRow | None:
        row = self.conn.execute(
            "SELECT * FROM asset_overlaps WHERE asset_a = ? AND asset_b = ?", (asset_a, asset_b)
        ).fetchone()
        return self._from_row(row) if row else None

    def save_result(self, row: OverlapRow) -> None:
        """Insert or replace the automatic result; an existing override is kept."""
        try:
            self.conn.execute(
                "INSERT INTO asset_overlaps (asset_a, asset_b, algorithm, version, status, "
                "offset_ms, overlap_ms, confidence, evidence_json, computed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (asset_a, asset_b) DO UPDATE SET algorithm = excluded.algorithm, "
                "version = excluded.version, status = excluded.status, "
                "offset_ms = excluded.offset_ms, overlap_ms = excluded.overlap_ms, "
                "confidence = excluded.confidence, evidence_json = excluded.evidence_json, "
                "computed_at = excluded.computed_at",
                (
                    row.asset_a,
                    row.asset_b,
                    row.algorithm,
                    row.version,
                    row.status,
                    row.offset_ms,
                    row.overlap_ms,
                    row.confidence,
                    _dumps(row.evidence),
                    row.computed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def set_override(
        self, asset_a: str, asset_b: str, overlap_ms: int | None, *, algorithm: str, version: int
    ) -> None:
        """Set (or clear, with None) the user's overlap for a pair. 0 means "no overlap"."""
        now = utc_now() if overlap_ms is not None else None
        try:
            self.conn.execute(
                "INSERT INTO asset_overlaps (asset_a, asset_b, algorithm, version, status, "
                "evidence_json, computed_at, override_overlap_ms, overridden_at) "
                "VALUES (?, ?, ?, ?, 'pending', '{}', ?, ?, ?) "
                "ON CONFLICT (asset_a, asset_b) DO UPDATE SET "
                "override_overlap_ms = excluded.override_overlap_ms, "
                "overridden_at = excluded.overridden_at",
                (asset_a, asset_b, algorithm, version, utc_now(), overlap_ms, now),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def effective(
        self, pairs: list[tuple[str, str]], *, algorithm: str, version: int
    ) -> dict[tuple[str, str], EffectiveOverlap]:
        """Overlaps a timeline applies: the user's override, else a current ``matched``
        result. Weak, ambiguous, stale, or missing results apply nothing."""
        out: dict[tuple[str, str], EffectiveOverlap] = {}
        for a, b in pairs:
            row = self.get(a, b)
            if row is None:
                continue
            if row.override_overlap_ms is not None:
                out[(a, b)] = EffectiveOverlap(row.override_overlap_ms, 1.0, "user")
            elif (
                row.status == "matched"
                and (row.algorithm, row.version) == (algorithm, version)
                and row.overlap_ms is not None
            ):
                out[(a, b)] = EffectiveOverlap(row.overlap_ms, row.confidence, "auto")
        return out

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OverlapRow:
        data = dict(row)
        evidence = data.pop("evidence_json")
        return OverlapRow(**data, evidence=_loads(evidence))


ReviewState = Literal["unreviewed", "duplicate", "distinct"]


class DuplicateCandidateRow(_Model):
    id: int
    asset_a: str
    asset_b: str
    kind: Literal["perceptual"]
    score: float = Field(ge=0, le=1)
    evidence: dict[str, JsonValue]
    algorithm: str
    version: int
    review_state: ReviewState
    created_at: str
    updated_at: str


class DuplicateCandidateRepository:
    """duplicate_candidates. Recording a pair again refreshes its score and evidence but
    never changes a person's ``review_state``. Nothing here deletes media."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(
        self,
        asset_x: str,
        asset_y: str,
        *,
        score: float,
        evidence: dict[str, JsonValue],
        algorithm: str,
        version: int,
        when: str | None = None,
    ) -> tuple[int, bool]:
        """Insert or refresh a pair; returns ``(id, created)``."""
        if asset_x == asset_y:
            raise ConflictError("an asset cannot be a duplicate candidate of itself")
        a, b = sorted((asset_x, asset_y))
        now = when or utc_now()
        existing = self.conn.execute(
            "SELECT id FROM duplicate_candidates WHERE asset_a = ? AND asset_b = ? "
            "AND kind = 'perceptual'",
            (a, b),
        ).fetchone()
        try:
            if existing is not None:
                self.conn.execute(
                    "UPDATE duplicate_candidates SET score = ?, evidence_json = ?, algorithm = ?, "
                    "version = ?, updated_at = ? WHERE id = ?",
                    (score, _dumps(evidence), algorithm, version, now, existing["id"]),
                )
                return int(existing["id"]), False
            cur = self.conn.execute(
                "INSERT INTO duplicate_candidates (asset_a, asset_b, kind, score, evidence_json, "
                "algorithm, version, created_at, updated_at) "
                "VALUES (?, ?, 'perceptual', ?, ?, ?, ?, ?, ?)",
                (a, b, score, _dumps(evidence), algorithm, version, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc
        return int(cur.lastrowid or 0), True

    def get(self, candidate_id: int) -> DuplicateCandidateRow:
        row = self.conn.execute(
            "SELECT * FROM duplicate_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"duplicate candidate {candidate_id} not found")
        return self._from_row(row)

    def query(
        self,
        *,
        review_state: ReviewState | None = None,
        asset_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[DuplicateCandidateRow]:
        clauses: list[str] = []
        args: list[JsonValue] = []
        if review_state is not None:
            clauses.append("review_state = ?")
            args.append(review_state)
        if asset_id is not None:
            clauses.append("(asset_a = ? OR asset_b = ?)")
            args += [asset_id, asset_id]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM duplicate_candidates {where} "  # noqa: S608 - fixed fragments
            "ORDER BY created_at, id LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def set_review_state(self, candidate_id: int, state: ReviewState) -> DuplicateCandidateRow:
        cur = self.conn.execute(
            "UPDATE duplicate_candidates SET review_state = ?, updated_at = ? WHERE id = ?",
            (state, utc_now(), candidate_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"duplicate candidate {candidate_id} not found")
        return self.get(candidate_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DuplicateCandidateRow:
        return DuplicateCandidateRow(
            id=row["id"],
            asset_a=row["asset_a"],
            asset_b=row["asset_b"],
            kind=row["kind"],
            score=row["score"],
            evidence=_loads(row["evidence_json"]),
            algorithm=row["algorithm"],
            version=row["version"],
            review_state=row["review_state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


DEFAULT_EXCLUDE: tuple[str, ...] = (".*", "**/.*/**")


class WatchedFolderRow(_Model):
    id: int
    path: str
    source_kind: str
    mode: Literal["reference", "managed"]
    recursive: bool
    include: list[str]
    exclude: list[str]
    enabled: bool
    created_at: str
    updated_at: str
    last_scan_at: str | None
    availability: Literal["unknown", "available", "unavailable"]
    last_error: dict[str, JsonValue] | None


class WatchedFileRow(_Model):
    folder_id: int
    relative_path: str
    size_bytes: int
    mtime_ns: int
    attempts: int
    job_id: str | None
    updated_at: str


class WatchedFolderRepository:
    """watched_folders and watched_files. Removing a folder deletes only these records;
    files on disk are never touched."""

    _FIELDS = ("source_kind", "mode", "recursive", "include", "exclude", "enabled")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        path: str,
        source_kind: str = "other",
        mode: str = "reference",
        recursive: bool = True,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        enabled: bool = True,
        when: str | None = None,
    ) -> WatchedFolderRow:
        now = when or utc_now()
        try:
            cur = self.conn.execute(
                "INSERT INTO watched_folders (path, source_kind, enabled, created_at, mode, "
                "recursive, include_json, exclude_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    path,
                    source_kind,
                    int(enabled),
                    now,
                    mode,
                    int(recursive),
                    _dumps(include or []),
                    _dumps(list(DEFAULT_EXCLUDE) if exclude is None else exclude),
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ConflictError("this folder is already watched") from exc
            raise _translate(exc) from exc
        return self.get(int(cur.lastrowid or 0))

    def get(self, folder_id: int) -> WatchedFolderRow:
        row = self.conn.execute(
            "SELECT * FROM watched_folders WHERE id = ?", (folder_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"watched folder {folder_id} not found")
        return self._from_row(row)

    def all(self) -> list[WatchedFolderRow]:
        rows = self.conn.execute("SELECT * FROM watched_folders ORDER BY id").fetchall()
        return [self._from_row(r) for r in rows]

    def update(self, folder_id: int, changes: dict[str, JsonValue]) -> WatchedFolderRow:
        unknown = set(changes) - set(self._FIELDS)
        if unknown:
            raise ValueError(f"cannot change {', '.join(sorted(unknown))}")
        columns = {
            "source_kind": "source_kind",
            "mode": "mode",
            "recursive": "recursive",
            "include": "include_json",
            "exclude": "exclude_json",
            "enabled": "enabled",
        }

        def stored(key: str, value: JsonValue) -> JsonValue:
            if key in ("include", "exclude"):
                return _dumps(value)
            if key in ("recursive", "enabled"):
                return int(bool(value))
            return value

        sets = [f"{columns[k]} = ?" for k in changes]
        values = [stored(k, v) for k, v in changes.items()]
        cur = self.conn.execute(
            f"UPDATE watched_folders SET {', '.join([*sets, 'updated_at = ?'])} "  # noqa: S608
            "WHERE id = ?",
            (*values, utc_now(), folder_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"watched folder {folder_id} not found")
        return self.get(folder_id)

    def record_scan(
        self,
        folder_id: int,
        *,
        available: bool,
        scanned: bool,
        error: dict[str, JsonValue] | None,
        when: str | None = None,
    ) -> WatchedFolderRow:
        now = when or utc_now()
        cur = self.conn.execute(
            "UPDATE watched_folders SET availability = ?, last_error_json = ?, "
            "last_scan_at = CASE WHEN ? THEN ? ELSE last_scan_at END WHERE id = ?",
            (
                "available" if available else "unavailable",
                None if available or error is None else _dumps(error),
                int(scanned and available),
                now,
                folder_id,
            ),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"watched folder {folder_id} not found")
        return self.get(folder_id)

    def delete(self, folder_id: int) -> None:
        _delete(self.conn, "watched_folders", folder_id, "watched folder")

    # -- files -------------------------------------------------------------------------

    def file(self, folder_id: int, relative_path: str) -> WatchedFileRow | None:
        row = self.conn.execute(
            "SELECT * FROM watched_files WHERE folder_id = ? AND relative_path = ?",
            (folder_id, relative_path),
        ).fetchone()
        return None if row is None else WatchedFileRow(**dict(row))

    def files(self, folder_id: int, *, limit: int = 200, offset: int = 0) -> list[WatchedFileRow]:
        rows = self.conn.execute(
            "SELECT * FROM watched_files WHERE folder_id = ? "
            "ORDER BY updated_at DESC, relative_path LIMIT ? OFFSET ?",
            (folder_id, limit, offset),
        ).fetchall()
        return [WatchedFileRow(**dict(r)) for r in rows]

    def save_file(self, row: WatchedFileRow) -> None:
        try:
            self.conn.execute(
                "INSERT INTO watched_files (folder_id, relative_path, size_bytes, mtime_ns, "
                "attempts, job_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (folder_id, relative_path) DO UPDATE SET "
                "size_bytes = excluded.size_bytes, mtime_ns = excluded.mtime_ns, "
                "attempts = excluded.attempts, job_id = excluded.job_id, "
                "updated_at = excluded.updated_at",
                (
                    row.folder_id,
                    row.relative_path,
                    row.size_bytes,
                    row.mtime_ns,
                    row.attempts,
                    row.job_id,
                    row.updated_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _translate(exc) from exc

    def job_states(self, folder_id: int) -> list[tuple[str | None, str | None]]:
        """(job_id, job state) for every tracked file of a folder; state None when the
        job no longer exists."""
        rows = self.conn.execute(
            "SELECT f.job_id, j.state FROM watched_files f "
            "LEFT JOIN jobs j ON j.id = f.job_id WHERE f.folder_id = ?",
            (folder_id,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WatchedFolderRow:
        return WatchedFolderRow(
            id=row["id"],
            path=row["path"],
            source_kind=row["source_kind"],
            mode=row["mode"],
            recursive=bool(row["recursive"]),
            include=_loads(row["include_json"]),
            exclude=_loads(row["exclude_json"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
            last_scan_at=row["last_scan_at"],
            availability=row["availability"],
            last_error=_loads(row["last_error_json"]),
        )


# -- sessions -------------------------------------------------------------------------


class SessionRepository:
    """sessions and session_assets.

    Deleting a session cascades its membership rows, events, and transcripts, but
    is refused while stories reference it.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _row(session: Session) -> dict[str, Any]:
        row = session.model_dump(exclude={"grouping"})
        row["grouping_json"] = _dumps(session.grouping) if session.grouping is not None else None
        return row

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Session:
        data = dict(row)
        grouping = data.pop("grouping_json", None)
        return Session(**data, grouping=_loads(grouping) if grouping is not None else None)

    def add(self, session: Session) -> None:
        _insert(self.conn, "sessions", self._row(session))

    def update(self, session: Session) -> None:
        """Replace every stored field of an existing session."""
        row = self._row(session)
        fields = [k for k in row if k != "id"]
        cur = self.conn.execute(
            f"UPDATE sessions SET {', '.join(f'{k} = :{k}' for k in fields)} "  # noqa: S608
            "WHERE id = :id",
            row,
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"session {session.id} not found")

    def get(self, session_id: str) -> Session:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"session {session_id} not found")
        return self._from_row(row)

    def all(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at IS NULL, started_at, id"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def newest(self, *, limit: int = 200, offset: int = 0) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at IS NULL, started_at DESC, id DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def replace_assets(self, session_id: str, links: list[SessionAsset]) -> None:
        """Set a session's members and order in one go."""
        self.conn.execute("DELETE FROM session_assets WHERE session_id = ?", (session_id,))
        for link in links:
            self.add_asset(link)

    def session_of(self, asset_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT session_id FROM session_assets WHERE asset_id = ? ORDER BY session_id LIMIT 1",
            (asset_id,),
        ).fetchone()
        return row[0] if row else None

    def has_stories(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM stories WHERE session_id = ? LIMIT 1", (session_id,)
        ).fetchone()
        return row is not None

    #: Rows that belong to a session and would be lost (cascade) or block (restrict)
    #: if it were deleted: stories, events, transcript segments, collection items.
    ATTACHED_DATA_SQL = (
        "SELECT session_id FROM stories WHERE session_id IS NOT NULL "
        "UNION SELECT session_id FROM events "
        "UNION SELECT session_id FROM event_observations "
        "UNION SELECT session_id FROM transcript_segments "
        "UNION SELECT session_id FROM collection_items WHERE session_id IS NOT NULL"
    )

    def has_attached_data(self, session_id: str) -> bool:
        """Whether deleting the session would drop or be blocked by other rows."""
        row = self.conn.execute(
            f"SELECT 1 FROM ({self.ATTACHED_DATA_SQL}) WHERE session_id = ? LIMIT 1",  # noqa: S608
            (session_id,),
        ).fetchone()
        return row is not None

    def with_attached_data(self) -> set[str]:
        return {r[0] for r in self.conn.execute(self.ATTACHED_DATA_SQL).fetchall()}

    def log_correction(
        self,
        kind: Literal["merge", "split", "reorder", "remove", "confirm", "overlap"],
        session_ids: list[str],
        asset_ids: list[str],
        detail: dict[str, JsonValue] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO session_corrections (kind, session_ids_json, asset_ids_json, "
            "detail_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                kind,
                _dumps(session_ids),
                _dumps(asset_ids),
                _dumps(detail) if detail is not None else None,
                utc_now(),
            ),
        )
        return int(cur.lastrowid or 0)

    def corrections(self, session_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM session_corrections ORDER BY id").fetchall()
        out = []
        for row in rows:
            sessions = _loads(row["session_ids_json"])
            if session_id is not None and session_id not in (sessions or []):
                continue
            out.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "session_ids": sessions,
                    "asset_ids": _loads(row["asset_ids_json"]),
                    "detail": _loads(row["detail_json"]),
                    "created_at": row["created_at"],
                }
            )
        return out

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
                "tool_versions_json": _dumps(source["tool_versions"])
                if "tool_versions" in source
                else None,
                "input_key": source.get("input_key"),
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

    def page_for_session(self, session_id: str, *, limit: int, offset: int) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY start_ms, id LIMIT ? OFFSET ?",
            (session_id, limit, offset),
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
                    "tool_versions": _loads(row["tool_versions_json"]),
                    "input_key": row["input_key"],
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
            "params_json": _dumps(d["params"]) if "params" in d else None,
            "result_json": _dumps(d["result"]) if "result" in d else None,
            "attempt": d.get("attempt", 1),
            "progress_done": progress["done"] if progress else None,
            "progress_total": progress["total"] if progress else None,
            "message": d.get("message"),
            "error_json": _dumps(d["error"]) if "error" in d else None,
            "correlation_id": d.get("correlation_id"),
            "created_at": d["created_at"],
            "started_at": d.get("started_at"),
            "finished_at": d.get("finished_at"),
            "idempotency_key": d.get("idempotency_key"),
        }
        _insert(self.conn, "jobs", row, upsert=True, keep=("id",))

    def find_by_idempotency_key(self, key: str) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
        return None if row is None else self._from_row(row)

    def get(self, job_id: str) -> Job:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"job {job_id} not found")
        return self._from_row(row)

    def all(self, *, limit: int = 200) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._from_row(r) for r in rows]

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
                "params": _loads(row["params_json"]),
                "result": _loads(row["result_json"]),
                "attempt": row["attempt"],
                "progress": progress,
                "message": row["message"],
                "error": _loads(row["error_json"]),
                "correlation_id": row["correlation_id"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "idempotency_key": row["idempotency_key"],
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
