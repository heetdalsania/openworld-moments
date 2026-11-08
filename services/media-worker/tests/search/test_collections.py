# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manual and rule-based collections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openworld_moments.search.filters import CollectionRule, SearchFilters
from openworld_moments.search.service import SearchError
from tests.search.conftest import Library


def rule(query: str = "", **filters: object) -> CollectionRule:
    return CollectionRule(query=query, filters=SearchFilters.model_validate(filters))


def test_rule_collections_explain_why_each_item_matched(lib: Library) -> None:
    sid = lib.session()
    aid = lib.clip(sid)
    hit = lib.event(sid, aid, "openworld.wanted_level_changed", confidence=0.92, text="WANTED")
    lib.decide(hit, "confirmed")
    lib.event(sid, aid, "openworld.wanted_level_changed", confidence=0.95, text="WANTED")
    lib.event(sid, aid, "openworld.wanted_level_changed", confidence=0.5, text="WANTED")
    created = lib.service.create(
        "Confirmed wanted",
        rule(
            "wanted -bike",
            kinds=["event"],
            review_states=["confirmed", "corrected"],
            min_confidence=0.8,
            occurred_from="2026-01-01T00:00:00Z",
            min_duration_ms=500,
        ),
    )
    assert created["kind"] == "rule" and "item_count" not in created
    page = lib.service.collection(created["id"])
    assert page["total"] == 1 and page["items"][0]["key"] == f"event:{hit}"
    reasons = {r["criterion"]: r["detail"] for r in page["items"][0]["reasons"]}
    assert reasons == {
        "text": "Matches wanted in the label and on-screen text, without bike",
        "kind": "Is an event (event allowed)",
        "review_state": "Review state is confirmed",
        "confidence": "Confidence 0.92 is at least 0.80",
        "date": "Date 2026-11-20T10:00:00Z is within 2026-01-01T00:00:00Z to any time",
        "duration": "Duration 1 s is at least 0.5 s",
    }
    # The rule is stored canonically and shown as data, never as SQL.
    assert page["rule"] == {
        "version": 1,
        "query": "wanted -bike",
        "filters": {
            "kinds": ["event"],
            "review_states": ["confirmed", "corrected"],
            "min_confidence": 0.8,
            "occurred_from": "2026-01-01T00:00:00Z",
            "min_duration_ms": 500,
        },
    }
    # Rule results follow the library live.
    lib.decide(hit, "rejected", revision=2)
    assert lib.service.collection(created["id"])["total"] == 0


def test_rules_need_a_criterion_and_a_valid_query(lib: Library) -> None:
    with pytest.raises(ValidationError):
        CollectionRule()
    with pytest.raises(ValidationError):
        CollectionRule.model_validate({"version": 2, "query": "x"})
    with pytest.raises(SearchError) as caught:
        lib.service.create("Bad", rule("-only"))
    assert caught.value.code == "search.only_exclusions"


def test_manual_collection_lifecycle(lib: Library) -> None:
    sid = lib.session("Night drive")
    aid = lib.clip(sid, "drive.mp4")
    eid = lib.event(sid, aid)
    tid = lib.span(sid, aid, "turn left")
    pid = lib.project(sid, "Drive edit")
    created = lib.service.create("  Favourite   moments ", None)
    cid = created["id"]
    assert created["name"] == "Favourite moments" and created["item_count"] == 0
    for kind, ident in (
        ("clip", aid),
        ("session", sid),
        ("event", eid),
        ("transcript", tid),
        ("project", pid),
    ):
        assert lib.service.add_item(cid, kind, ident)["added"] is True
    again = lib.service.add_item(cid, "event", eid)
    assert again["added"] is False
    page = lib.service.collection(cid)
    assert page["total"] == page["item_count"] == 5
    assert [i["kind"] for i in page["items"]] == [
        "clip",
        "session",
        "event",
        "transcript",
        "project",
    ]
    assert all("reasons" not in i and i["item_id"] >= 1 for i in page["items"])
    # Paging.
    assert [i["kind"] for i in lib.service.collection(cid, offset=3, limit=1)["items"]] == [
        "transcript"
    ]
    # Removing the source removes the item (no orphan reference survives).
    lib.sql("DELETE FROM transcript_segments WHERE id = ?", (tid,))
    lib.sql("DELETE FROM events WHERE id = ?", (eid,))
    assert lib.service.collection(cid)["total"] == 3
    item = lib.service.collection(cid)["items"][0]
    lib.service.remove_item(cid, item["item_id"])
    with pytest.raises(SearchError) as missing:
        lib.service.remove_item(cid, item["item_id"])
    assert missing.value.status == 404
    renamed = lib.service.update(cid, "Best drives", None)
    assert renamed["name"] == "Best drives"
    lib.service.delete(cid)
    with pytest.raises(SearchError) as gone:
        lib.service.collection(cid)
    assert gone.value.code == "collection.not_found"


def test_names_items_and_kinds_are_checked(lib: Library) -> None:
    sid = lib.session()
    manual = lib.service.create("Picks", None)["id"]
    ruled = lib.service.create("Auto", rule(kinds=["session"]))["id"]
    with pytest.raises(SearchError) as taken:
        lib.service.create("PICKS", None)
    assert taken.value.code == "collection.name_taken" and taken.value.status == 409
    with pytest.raises(SearchError) as renamed:
        lib.service.update(ruled, "picks", None)
    assert renamed.value.code == "collection.name_taken"
    for name in ("", "   ", "x" * 81):
        with pytest.raises(SearchError):
            lib.service.create(name, None)
    with pytest.raises(SearchError) as rule_items:
        lib.service.add_item(ruled, "session", sid)
    assert rule_items.value.code == "collection.rule_based"
    with pytest.raises(SearchError) as no_rule:
        lib.service.update(manual, None, rule(kinds=["clip"]))
    assert no_rule.value.code == "collection.not_rule"
    with pytest.raises(SearchError) as missing:
        lib.service.add_item(manual, "session", "ses_01JCBQ00000000000000000099")
    assert missing.value.code == "collection.item_missing"
    updated = lib.service.update(ruled, None, rule(kinds=["clip"]))
    assert updated["rule"]["filters"] == {"kinds": ["clip"]}
    assert [c["name"] for c in lib.service.collections()] == ["Auto", "Picks"]


def test_collected_sessions_count_as_attached_data(lib: Library) -> None:
    from contextlib import closing

    from openworld_moments.storage import SessionRepository

    sid = lib.session()
    cid = lib.service.create("Keep", None)["id"]
    lib.service.add_item(cid, "session", sid)
    with closing(lib.database.connect()) as conn:
        assert SessionRepository(conn).has_attached_data(sid)
