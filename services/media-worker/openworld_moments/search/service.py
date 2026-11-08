# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local search and collections (M26).

Ranking (documented in docs/architecture/search.md):

- With words: FTS5 BM25 with the title column weighted 3 and the body 1, scaled by
  review state (confirmed/corrected x1.25, unreviewed or none x1.0, rejected x0.5)
  and, when a confidence exists, by ``0.75 + 0.25 * confidence``. Lower is better;
  ties break by document key so pages are stable.
- Without words (filters only): newest first by date, then kind and key.

Snippets come from FTS5 with private marker characters and are returned as
segments ``{text, match}``; the UI renders them as text, never HTML.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections import Counter
from collections.abc import Mapping
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.ids import new_id
from openworld_moments.search.filters import CollectionRule, SearchFilters, SearchRequest
from openworld_moments.search.index import INDEX_VERSION
from openworld_moments.search.query import ParsedQuery, QueryError, parse_query
from openworld_moments.storage import Database, transaction, utc_now
from openworld_moments.storage.repositories import SCHEMA_VERSION

START, END = "\x02", "\x03"
FACETS = ("kind", "event_type", "review_state", "source_kind")
FACET_LIMIT = 20
MAX_COLLECTIONS = 500
MAX_ITEMS = 5000
SCORE = (
    "bm25(search_fts, 3.0, 1.0)"
    " * (CASE d.review_state WHEN 'confirmed' THEN 1.25 WHEN 'corrected' THEN 1.25"
    " WHEN 'rejected' THEN 0.5 ELSE 1.0 END)"
    " * (CASE WHEN d.confidence IS NULL THEN 1.0 ELSE 0.75 + 0.25 * d.confidence END)"
)
DOC_COLUMNS = (
    "d.id, d.doc_key, d.kind, d.session_id, d.asset_id, d.event_id, d.transcript_id, "
    "d.project_id, d.title, d.body, d.start_ms, d.end_ms, d.source_start_ms, d.source_end_ms, "
    "d.occurred_at, d.duration_ms, d.source_kind, d.event_type, d.confidence, d.review_state"
)
#: What the title and body columns hold, per kind (for explanations).
FIELDS = {
    "clip": ("file name", "text"),
    "session": ("title", "text"),
    "event": ("label", "on-screen text"),
    "transcript": ("speaker", "spoken text"),
    "project": ("title", "text"),
}
ITEM_COLUMNS = {
    "clip": "asset_id",
    "session": "session_id",
    "event": "event_id",
    "transcript": "transcript_id",
    "project": "story_id",
}
DOC_KEY_COLUMN = {
    "clip": "asset_id",
    "session": "session_id",
    "event": "event_id",
    "transcript": "transcript_id",
    "project": "project_id",
}


class SearchError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _unavailable() -> SearchError:
    return SearchError(
        "search.index_unavailable",
        "The search index is damaged or missing. Rebuild it from the Search screen.",
        503,
    )


def segments(marked: str) -> list[dict[str, Any]]:
    """Split FTS5 marker text into ``{text, match}`` segments."""
    out: list[dict[str, Any]] = []
    match = False
    buffer = ""
    for char in marked:
        if char in (START, END):
            if buffer:
                out.append({"text": buffer, "match": match})
            buffer, match = "", char == START
        else:
            buffer += char
    if buffer:
        out.append({"text": buffer, "match": match})
    return out


def result(
    row: Mapping[str, Any], title: str | None = None, body: str | None = None
) -> dict[str, Any]:
    kind = row["kind"]
    item: dict[str, Any] = {
        "key": row["doc_key"],
        "kind": kind,
        "title": segments(title if title is not None else row["title"]),
        "snippet": segments(body) if body is not None else [],
        "matched_in": [],
    }
    if title is not None and START in title:
        item["matched_in"].append(FIELDS[kind][0])
    if body is not None and START in body:
        item["matched_in"].append(FIELDS[kind][1])
    if body is None and row["body"]:
        item["snippet"] = [{"text": row["body"][:240], "match": False}]
    for column in ("session_id", "asset_id", "event_id", "transcript_id", "project_id"):
        if row[column] is not None:
            item[column] = row[column]
    if row["start_ms"] is not None and row["end_ms"] is not None:
        item["range"] = {
            "timebase": "clip" if kind == "clip" else "session",
            "start_ms": row["start_ms"],
            "end_ms": max(row["start_ms"], row["end_ms"]),
        }
    if (
        row["asset_id"] is not None
        and row["source_start_ms"] is not None
        and row["source_end_ms"] is not None
    ):
        item["source_range"] = {
            "asset_id": row["asset_id"],
            "start_ms": row["source_start_ms"],
            "end_ms": max(row["source_start_ms"], row["source_end_ms"]),
        }
    for column in ("occurred_at", "duration_ms", "source_kind", "event_type", "review_state"):
        if row[column] is not None:
            item[column] = row[column]
    if row["confidence"] is not None:
        item["confidence"] = round(float(row["confidence"]), 4)
    return item


class SearchService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # -- search ------------------------------------------------------------------------

    def _parse(self, text: str) -> ParsedQuery:
        try:
            return parse_query(text)
        except QueryError as exc:
            raise SearchError(exc.code, exc.message) from exc

    def _matches(
        self,
        conn: sqlite3.Connection,
        parsed: ParsedQuery,
        filters: SearchFilters,
        offset: int,
        limit: int,
    ) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """One pass over the matches (compact columns), then the page's full rows."""
        where, params = filters.sql("d")
        match = parsed.fts()
        compact = "d.id, d.doc_key, d.kind, d.event_type, d.review_state, d.source_kind"
        if match is not None:
            rows = conn.execute(
                f"SELECT {compact}, {SCORE} FROM search_fts "  # noqa: S608
                f"JOIN search_documents d ON d.id = search_fts.rowid "
                f"WHERE search_fts MATCH ? AND {where}",
                [match, *params],
            ).fetchall()
            rows.sort(key=lambda r: (r[6], r[1]))
        else:
            rows = conn.execute(
                f"SELECT {compact}, julianday(d.occurred_at) FROM search_documents d "  # noqa: S608
                f"WHERE {where}",
                params,
            ).fetchall()
            rows.sort(key=lambda r: (r[6] is None, -(r[6] or 0), r[2], r[1]))
        total = len(rows)
        facets: dict[str, list[dict[str, Any]]] = {}
        for column, name in enumerate(FACETS, start=2):
            counts = Counter(r[column] for r in rows if r[column] is not None)
            ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:FACET_LIMIT]
            facets[name] = [{"value": value, "count": count} for value, count in ranked]
        ids = [r[0] for r in rows[offset : offset + limit]]
        if not ids:
            return total, facets, []
        marks = ",".join("?" * len(ids))
        docs = {
            r["id"]: r
            for r in conn.execute(
                f"SELECT {DOC_COLUMNS} FROM search_documents d WHERE d.id IN ({marks})",  # noqa: S608
                ids,
            )
        }
        marked: dict[int, tuple[str, str]] = {}
        if match is not None:
            for rowid, title, body in conn.execute(
                "SELECT rowid, highlight(search_fts, 0, char(2), char(3)), "  # noqa: S608
                "snippet(search_fts, 1, char(2), char(3), '…', 16) FROM search_fts "
                f"WHERE search_fts MATCH ? AND rowid IN ({marks})",
                [match, *ids],
            ):
                marked[rowid] = (title, body)
        items = []
        for doc_id in ids:
            title, body = marked.get(doc_id, (None, None))
            items.append(result(docs[doc_id], title, body or None))
        return total, facets, items

    def search(self, request: SearchRequest) -> dict[str, Any]:
        parsed = self._parse(request.query)
        started = time.perf_counter()
        try:
            with contextlib.closing(self.database.connect()) as conn:
                state = conn.execute(
                    "SELECT status, index_version FROM search_index_state WHERE id = 1"
                ).fetchone()
                total, facets, items = self._matches(
                    conn, parsed, request.filters, request.offset, request.limit
                )
        except sqlite3.DatabaseError as exc:
            raise _unavailable() from exc
        if state is None:
            index_status = "cleared"
        elif state["index_version"] != INDEX_VERSION:
            index_status = "stale"
        else:
            index_status = state["status"]
        return normalize(
            load(
                "search",
                {
                    "schema_version": SCHEMA_VERSION,
                    "query": {
                        "text": request.query,
                        "terms": [t.text for t in parsed.terms],
                        "ignored": list(parsed.ignored),
                    },
                    "filters": request.filters.compact(),
                    "offset": request.offset,
                    "limit": request.limit,
                    "total": total,
                    "items": items,
                    "facets": facets,
                    "index_status": index_status,
                    "took_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
        )

    # -- collections -------------------------------------------------------------------

    @staticmethod
    def _collection_row(conn: sqlite3.Connection, cid: str) -> Any:
        row = conn.execute(
            "SELECT c.*, (SELECT count(*) FROM collection_items i WHERE i.collection_id = c.id) "
            "AS item_count FROM collections c WHERE c.id = ?",
            (cid,),
        ).fetchone()
        if row is None:
            raise SearchError("collection.not_found", "That collection does not exist.", 404)
        return row

    @staticmethod
    def _summary(row: Any) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if row["kind"] == "rule":
            summary["rule"] = json.loads(row["rule_json"])
        else:
            summary["item_count"] = row["item_count"]
        return summary

    def collections(self) -> list[dict[str, Any]]:
        with contextlib.closing(self.database.connect()) as conn:
            rows = conn.execute(
                "SELECT c.*, (SELECT count(*) FROM collection_items i "
                "WHERE i.collection_id = c.id) AS item_count FROM collections c "
                "ORDER BY c.name COLLATE NOCASE, c.id"
            ).fetchall()
        return [self._summary(r) for r in rows]

    def collection(self, cid: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        offset, limit = max(0, min(offset, 10_000)), max(1, min(limit, 100))
        try:
            with contextlib.closing(self.database.connect()) as conn:
                row = self._collection_row(conn, cid)
                summary = self._summary(row)
                if row["kind"] == "rule":
                    rule = CollectionRule.model_validate(summary["rule"])
                    parsed = self._parse(rule.query)
                    total, _, items = self._matches(conn, parsed, rule.filters, offset, limit)
                    for item in items:
                        item["reasons"] = self._reasons(rule, parsed, item, conn)
                else:
                    total, items = self._manual_items(conn, cid, offset, limit)
        except sqlite3.DatabaseError as exc:
            raise _unavailable() from exc
        return normalize(
            load(
                "collection",
                {
                    "schema_version": SCHEMA_VERSION,
                    **summary,
                    "offset": offset,
                    "total": total,
                    "items": items,
                },
            )
        )

    @staticmethod
    def _reasons(
        rule: CollectionRule,
        parsed: ParsedQuery,
        item: Mapping[str, Any],
        conn: sqlite3.Connection,
    ) -> list[dict[str, str]]:
        reasons: list[dict[str, str]] = []
        if not parsed.empty:
            words = ", ".join(t.text for t in parsed.terms if not t.exclude)
            where = " and ".join(item["matched_in"]) or "the indexed text"
            detail = f"Matches {words} in the {where}"
            excluded = [t.text.lstrip("-") for t in parsed.terms if t.exclude]
            if excluded:
                detail += f", without {', '.join(excluded)}"
            reasons.append({"criterion": "text", "detail": detail})
        doc = conn.execute(
            f"SELECT {DOC_COLUMNS} FROM search_documents d WHERE d.doc_key = ?",  # noqa: S608
            (item["key"],),
        ).fetchone()
        reasons.extend(rule.filters.explain(doc))
        return reasons

    def _manual_items(
        self, conn: sqlite3.Connection, cid: str, offset: int, limit: int
    ) -> tuple[int, list[dict[str, Any]]]:
        total = conn.execute(
            "SELECT count(*) FROM collection_items WHERE collection_id = ?", (cid,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT i.id AS item_id, i.added_at, "
            "CASE WHEN i.asset_id IS NOT NULL THEN 'clip:' || i.asset_id "
            "WHEN i.session_id IS NOT NULL THEN 'session:' || i.session_id "
            "WHEN i.event_id IS NOT NULL THEN 'event:' || i.event_id "
            "WHEN i.transcript_id IS NOT NULL THEN 'transcript:' || i.transcript_id "
            "ELSE 'project:' || i.story_id END AS key "
            "FROM collection_items i WHERE i.collection_id = ? "
            "ORDER BY i.position LIMIT ? OFFSET ?",
            (cid, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            doc = conn.execute(
                f"SELECT {DOC_COLUMNS} FROM search_documents d WHERE d.doc_key = ?",  # noqa: S608
                (row["key"],),
            ).fetchone()
            kind, _, ident = row["key"].partition(":")
            if doc is not None:
                item = result(doc)
            else:  # the index is incomplete; the item itself still exists
                item = {
                    "key": row["key"],
                    "kind": kind,
                    "title": [{"text": ident, "match": False}],
                    "snippet": [],
                    "matched_in": [],
                    DOC_KEY_COLUMN[kind]: int(ident) if kind == "transcript" else ident,
                }
            item["item_id"] = row["item_id"]
            item["added_at"] = row["added_at"]
            items.append(item)
        return total, items

    def create(self, name: str, rule: CollectionRule | None) -> dict[str, Any]:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 80:
            raise SearchError("collection.invalid_name", "Use a name of 1 to 80 characters.")
        if rule is not None:
            self._parse(rule.query)
        now = utc_now()
        cid = new_id("col")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            if conn.execute("SELECT count(*) FROM collections").fetchone()[0] >= MAX_COLLECTIONS:
                raise SearchError(
                    "collection.limit", f"A library can hold {MAX_COLLECTIONS} collections."
                )
            try:
                conn.execute(
                    "INSERT INTO collections (id, name, kind, rule_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        cid,
                        name,
                        "rule" if rule else "manual",
                        json.dumps(rule.canonical(), sort_keys=True) if rule else None,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SearchError(
                    "collection.name_taken", "Another collection already has that name.", 409
                ) from exc
            return self._summary(self._collection_row(conn, cid))

    def update(self, cid: str, name: str | None, rule: CollectionRule | None) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            row = self._collection_row(conn, cid)
            if rule is not None and row["kind"] != "rule":
                raise SearchError("collection.not_rule", "Only rule-based collections have a rule.")
            if rule is not None:
                self._parse(rule.query)
            new_name = row["name"] if name is None else " ".join(name.split())
            if not 1 <= len(new_name) <= 80:
                raise SearchError("collection.invalid_name", "Use a name of 1 to 80 characters.")
            try:
                conn.execute(
                    "UPDATE collections SET name = ?, rule_json = ?, updated_at = ? WHERE id = ?",
                    (
                        new_name,
                        json.dumps(rule.canonical(), sort_keys=True) if rule else row["rule_json"],
                        utc_now(),
                        cid,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SearchError(
                    "collection.name_taken", "Another collection already has that name.", 409
                ) from exc
            return self._summary(self._collection_row(conn, cid))

    def delete(self, cid: str) -> None:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            self._collection_row(conn, cid)
            conn.execute("DELETE FROM collections WHERE id = ?", (cid,))

    def add_item(self, cid: str, kind: str, ident: str | int) -> dict[str, Any]:
        column = ITEM_COLUMNS.get(kind)
        if column is None:
            raise SearchError("collection.invalid_item", "That item cannot be collected.")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            row = self._collection_row(conn, cid)
            if row["kind"] != "manual":
                raise SearchError(
                    "collection.rule_based",
                    "Rule-based collections fill themselves; edit the rule instead.",
                )
            if row["item_count"] >= MAX_ITEMS:
                raise SearchError("collection.limit", f"A collection can hold {MAX_ITEMS} items.")
            existing = conn.execute(
                f"SELECT id FROM collection_items WHERE collection_id = ? "  # noqa: S608
                f"AND {column} = ?",
                (cid, ident),
            ).fetchone()
            if existing is not None:
                return {"item_id": existing[0], "added": False}
            position = conn.execute(
                "SELECT coalesce(max(position) + 1, 0) FROM collection_items "
                "WHERE collection_id = ?",
                (cid,),
            ).fetchone()[0]
            try:
                cursor = conn.execute(
                    f"INSERT INTO collection_items (collection_id, {column}, position, "  # noqa: S608
                    "added_at) VALUES (?, ?, ?, ?)",
                    (cid, ident, position, utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise SearchError(
                    "collection.item_missing", "That item no longer exists.", 404
                ) from exc
            conn.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (utc_now(), cid))
            return {"item_id": cursor.lastrowid, "added": True}

    def remove_item(self, cid: str, item_id: int) -> None:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            self._collection_row(conn, cid)
            deleted = conn.execute(
                "DELETE FROM collection_items WHERE collection_id = ? AND id = ?", (cid, item_id)
            ).rowcount
            if not deleted:
                raise SearchError(
                    "collection.item_not_found", "That item is not in the collection.", 404
                )
            conn.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (utc_now(), cid))
