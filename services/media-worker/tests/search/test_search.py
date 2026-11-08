# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search over the trigger-maintained index: ranking, filters, text handling, deletion."""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from openworld_moments.search.filters import SearchFilters
from openworld_moments.search.service import SearchError, segments
from openworld_moments.storage import transaction
from openworld_moments.transcripts.service import Transcriber
from tests.search.conftest import Library


def test_results_identify_the_source_and_exact_time_range(lib: Library) -> None:
    sid = lib.session("Saturday heist")
    aid = lib.clip(sid, "Capture 0001.mp4")
    eid = lib.event(sid, aid, start_ms=4200, end_ms=5100, text="WANTED")
    tid = lib.span(sid, aid, "the getaway car is here", start_ms=7000, end_ms=8400)

    event = lib.search("wanted")["items"][0]
    assert event["key"] == f"event:{eid}"
    assert (event["session_id"], event["asset_id"], event["event_id"]) == (sid, aid, eid)
    assert event["range"] == {"timebase": "session", "start_ms": 4200, "end_ms": 5100}
    assert event["matched_in"] == ["label", "on-screen text"]

    span = lib.search("getaway")["items"][0]
    assert span["key"] == f"transcript:{tid}" and span["transcript_id"] == tid
    assert span["range"] == {"timebase": "session", "start_ms": 7000, "end_ms": 8400}
    assert span["source_range"] == {"asset_id": aid, "start_ms": 7500, "end_ms": 8900}

    clip = lib.search("capture")["items"][0]
    assert clip["range"] == {"timebase": "clip", "start_ms": 0, "end_ms": 30_000}
    session = lib.search("saturday")["items"][0]
    assert session["key"] == f"session:{sid}" and session["range"]["end_ms"] == 30_000


def test_review_decisions_change_the_indexed_label_interval_and_state(lib: Library) -> None:
    sid = lib.session()
    aid = lib.clip(sid)
    eid = lib.event(sid, aid, "openworld.vehicle_crash", start_ms=100, end_ms=900)
    assert lib.keys("crash") == [f"event:{eid}"]
    lib.decide(eid, "corrected", type="openworld.busted", start_ms=300, end_ms=1200)
    assert lib.keys("crash") == []
    corrected = lib.search("busted")["items"][0]
    assert (
        corrected["review_state"] == "corrected" and corrected["event_type"] == "openworld.busted"
    )
    assert corrected["range"] == {"timebase": "session", "start_ms": 300, "end_ms": 1200}
    lib.decide(eid, "rejected", revision=2, type="openworld.busted")
    assert lib.search("busted", review_states=["rejected"])["total"] == 1


def test_ranking_weights_titles_review_state_and_confidence(lib: Library) -> None:
    sid = lib.session()
    aid = lib.clip(sid)
    # "busted" in the label (title) outranks "busted" only in the on-screen text.
    title = lib.event(sid, aid, "openworld.busted", text="lose the cops")
    body = lib.event(sid, aid, "openworld.vehicle_crash", text="busted")
    assert lib.keys("busted")[:2] == [f"event:{title}", f"event:{body}"]
    # With equal text, confirmed beats unreviewed beats rejected; confidence breaks ties.
    sid2 = lib.session("Other")
    confirmed = lib.event(sid2, None, "openworld.wasted", confidence=0.5)
    unreviewed_high = lib.event(sid2, None, "openworld.wasted", confidence=1.0)
    unreviewed_low = lib.event(sid2, None, "openworld.wasted", confidence=0.4)
    rejected = lib.event(sid2, None, "openworld.wasted", confidence=1.0)
    lib.decide(confirmed, "confirmed")
    lib.decide(rejected, "rejected")
    assert lib.keys("wasted") == [
        f"event:{e}" for e in (confirmed, unreviewed_high, unreviewed_low, rejected)
    ]


def test_filters_for_each_field(lib: Library) -> None:
    early = lib.session("Early", "2026-01-05T10:00:00Z")
    late = lib.session("Late", "2026-06-05T10:00:00Z")
    xbox = lib.clip(
        early, "a.mp4", source_kind="xbox", duration_ms=10_000, captured_at="2026-01-05T10:00:00Z"
    )
    ps = lib.clip(
        late,
        "b.mp4",
        source_kind="playstation",
        duration_ms=90_000,
        captured_at="2026-06-05T10:00:00Z",
    )
    high = lib.event(early, xbox, "openworld.busted", confidence=0.95, start_ms=0, end_ms=4000)
    low = lib.event(late, ps, "openworld.wasted", confidence=0.4, start_ms=0, end_ms=500)
    lib.decide(high, "confirmed")
    span = lib.span(late, ps, "hello there")

    assert set(lib.keys(kinds=["event"])) == {f"event:{high}", f"event:{low}"}
    assert set(lib.keys(session_ids=[early])) == {
        f"session:{early}",
        f"clip:{xbox}",
        f"event:{high}",
    }
    # A session takes the source of its first clip.
    assert set(lib.keys(source_kinds=["playstation"])) == {
        f"session:{late}",
        f"clip:{ps}",
        f"event:{low}",
        f"transcript:{span}",
    }
    assert lib.keys(event_types=["openworld.wasted"]) == [f"event:{low}"]
    assert lib.keys(review_states=["confirmed"]) == [f"event:{high}"]
    # Only documents with a confidence can pass a confidence filter.
    assert set(lib.keys(min_confidence=0.9)) == {f"event:{high}", f"transcript:{span}"}
    assert set(lib.keys(occurred_to="2026-02-01T00:00:00Z")) == {
        f"session:{early}",
        f"clip:{xbox}",
        f"event:{high}",
    }
    assert f"clip:{ps}" in lib.keys(occurred_from="2026-06-01T00:00:00Z")
    assert lib.keys(kinds=["clip"], min_duration_ms=60_000) == [f"clip:{ps}"]
    assert lib.keys(kinds=["event"], max_duration_ms=1000) == [f"event:{low}"]
    # Fields combine with AND; list values with OR.
    assert set(lib.keys(kinds=["event", "clip"], source_kinds=["xbox"], min_duration_ms=4000)) == {
        f"clip:{xbox}",
        f"event:{high}",
    }


def test_invalid_filters_are_refused() -> None:
    for bad in (
        {"kinds": ["clip", "clip"]},
        {"kinds": ["video"]},
        {"min_confidence": 1.5},
        {"occurred_from": "2026-06-01", "occurred_to": "2026-01-01T00:00:00Z"},
        {"occurred_from": "2026-06-01T00:00:00Z", "occurred_to": "2026-01-01T00:00:00Z"},
        {"min_duration_ms": 10, "max_duration_ms": 5},
        {"event_types": ["Not A Type"]},
        {"session_ids": ["ses_x"]},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            SearchFilters.model_validate(bad)


def test_unicode_diacritics_and_cjk(lib: Library) -> None:
    sid = lib.session("Café chase")
    aid = lib.clip(sid, "クリップ 一.mp4")
    lib.span(sid, aid, "Straße race in Zürich")
    assert lib.search("cafe")["total"] == 1 and lib.search("CAFÉ")["total"] == 1
    assert lib.search("zurich")["total"] == 1 and lib.search("Straße")["total"] == 1
    # unicode61 keeps a run of CJK characters as one word: exact word or prefix.
    assert lib.search("クリップ")["total"] == 1 and lib.search("クリ*")["total"] == 1


def test_phrases_prefixes_and_exclusions(lib: Library) -> None:
    sid = lib.session()
    a = lib.span(sid, None, "the police chase began")
    b = lib.span(sid, None, "chase the police car")
    c = lib.span(sid, None, "a bike chase")
    assert set(lib.keys("police chase")) == {f"transcript:{a}", f"transcript:{b}"}
    assert lib.keys('"police chase"') == [f"transcript:{a}"]
    assert set(lib.keys("pol*")) == {f"transcript:{a}", f"transcript:{b}"}
    assert lib.keys("chase -police") == [f"transcript:{c}"]
    assert lib.keys('"chase the pol"*') == [f"transcript:{b}"]


def test_special_characters_and_empty_queries_fail_safely(lib: Library) -> None:
    sid = lib.session()
    lib.span(sid, None, 'say "hi" (now) AND then: OR NOT')
    for text in [
        '"hi"',
        "(now)",
        "AND",
        "then:",
        "OR NOT",
        "NEAR(",
        "*",
        '"',
        "\\",
        "'; DROP TABLE x",
    ]:
        lib.search(text)  # never raises an FTS5 syntax error
    assert lib.search("then:")["total"] == 1
    assert lib.search("*")["query"]["ignored"] == ["*"]
    assert lib.search("")["total"] == 2  # filter-only browse: the session and the span
    for text, code in (("w*", "search.prefix_too_short"), ("-x", "search.only_exclusions")):
        with pytest.raises(SearchError) as caught:
            lib.search(text)
        assert caught.value.code == code and caught.value.status == 422


def test_snippets_are_text_segments(lib: Library) -> None:
    sid = lib.session()
    lib.span(sid, None, "<b>not html</b> watch out for the bike")
    item = lib.search("bike")["items"][0]
    assert {"text": "bike", "match": True} in item["snippet"]
    assert "".join(s["text"] for s in item["snippet"]).startswith("<b>not html</b>")
    assert segments("a\x02b\x03c") == [
        {"text": "a", "match": False},
        {"text": "b", "match": True},
        {"text": "c", "match": False},
    ]


def test_facets_and_pagination(lib: Library) -> None:
    sid = lib.session()
    for i in range(7):
        lib.event(sid, None, "openworld.busted" if i % 2 else "openworld.wasted", text="hit")
    page = lib.search("hit", limit=3, offset=0)
    assert page["total"] == 7 and len(page["items"]) == 3
    assert page["facets"]["kind"] == [{"value": "event", "count": 7}]
    assert page["facets"]["event_type"] == [
        {"value": "openworld.wasted", "count": 4},
        {"value": "openworld.busted", "count": 3},
    ]
    rest = (
        lib.search("hit", limit=3, offset=3)["items"]
        + lib.search("hit", limit=3, offset=6)["items"]
    )
    keys = [i["key"] for i in page["items"] + rest]
    assert len(keys) == len(set(keys)) == 7
    assert lib.search("hit", offset=50)["items"] == []


def test_deleted_transcripts_and_events_leave_results_on_commit(
    lib: Library, tmp_path: Path
) -> None:
    sid = lib.session()
    aid = lib.clip(sid)
    eid = lib.event(sid, aid, text="secret mission name")
    lib.span(sid, aid, "my secret plan")
    assert lib.search("secret")["total"] == 2
    with contextlib.closing(lib.database.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM events WHERE id = ?", (eid,))
        # Other connections still see the event until the transaction commits.
        assert lib.search("secret")["total"] == 2
        conn.execute("COMMIT")
    assert [i["kind"] for i in lib.search("secret")["items"]] == ["transcript"]
    # The transcript service's delete path removes the spans too.
    derived = SimpleNamespace(paths=SimpleNamespace(root=tmp_path))
    Transcriber(lib.database, tools=None, derived=derived).delete(sid)  # type: ignore[arg-type]
    assert lib.search("secret")["total"] == 0
    with contextlib.closing(lib.database.connect()) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM search_fts WHERE search_fts MATCH 'secret'"
            ).fetchone()[0]
            == 0
        )


def test_a_failed_canonical_transaction_leaves_the_index_unchanged(lib: Library) -> None:
    sid = lib.session()
    with (
        contextlib.closing(lib.database.connect()) as conn,
        pytest.raises(RuntimeError),
        transaction(conn),
    ):
        conn.execute(
            "INSERT INTO transcript_segments (session_id, start_ms, end_ms, text) "
            "VALUES (?, 0, 10, 'rolled back words')",
            (sid,),
        )
        raise RuntimeError
    assert lib.search("rolled")["total"] == 0


def test_session_and_clip_changes_and_deletion(lib: Library) -> None:
    sid = lib.session("Old title")
    aid = lib.clip(sid, "first.mp4", duration_ms=10_000)
    lib.clip(sid, "second.mp4", duration_ms=5_000, order=1)
    assert lib.search("old")["items"][0]["range"]["end_ms"] == 15_000
    lib.sql("UPDATE sessions SET title = 'New title' WHERE id = ?", (sid,))
    assert lib.search("old")["total"] == 0 and lib.search("new")["total"] == 1
    lib.span(sid, aid, "words")
    lib.project(sid, "Escape edit")
    lib.sql("DELETE FROM stories")
    lib.sql("DELETE FROM session_assets WHERE session_id = ?", (sid,))
    lib.sql("DELETE FROM sessions WHERE id = ?", (sid,))
    assert lib.search("words")["total"] == 0 and lib.search("new")["total"] == 0
    clip = lib.search("first")["items"][0]
    assert clip["key"] == f"clip:{aid}" and "session_id" not in clip
