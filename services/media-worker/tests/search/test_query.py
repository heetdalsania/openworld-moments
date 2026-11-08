# SPDX-License-Identifier: AGPL-3.0-or-later
"""The query grammar never lets user text become FTS5 syntax."""

from __future__ import annotations

import pytest

from openworld_moments.search.query import MAX_QUERY_CHARS, QueryError, parse_query


def test_words_phrases_prefixes_and_exclusions() -> None:
    parsed = parse_query('Wanted "police chase" heist* -bike')
    assert [t.text for t in parsed.terms] == ["Wanted", '"police chase"', "heist*", "-bike"]
    assert parsed.fts() == '"Wanted" AND "police chase" AND "heist"* NOT "bike"'


def test_operators_columns_and_quotes_are_plain_text() -> None:
    # FTS5 keywords, column filters, NEAR groups and parentheses are only words.
    parsed = parse_query("OR AND NOT NEAR(a b) title:secret ^start (x)")
    assert parsed.fts() == (
        '"OR" AND "AND" AND "NOT" AND "NEAR a" AND "b" AND "title secret" AND "start" AND "x"'
    )


def test_separators_split_like_the_index_tokenizer() -> None:
    assert parse_query("wanted_level").fts() == '"wanted level"'
    assert parse_query("wanted-level.changed").fts() == '"wanted level changed"'


def test_unicode_is_passed_to_the_index_tokenizer_unchanged() -> None:
    assert parse_query("ÉVENING クリップ Straße").fts() == '"ÉVENING" AND "クリップ" AND "Straße"'


def test_unclosed_quote_runs_to_the_end() -> None:
    assert parse_query('wanted "police chase').fts() == '"wanted" AND "police chase"'


def test_punctuation_only_items_are_ignored_and_reported() -> None:
    parsed = parse_query('!!! "" *** wanted -- ?')
    assert parsed.fts() == '"wanted"'
    assert parsed.ignored == ("!!!", '""', "***", "--", "?")
    assert parse_query("   ").empty and parse_query("").fts() is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("x" * (MAX_QUERY_CHARS + 1), "search.query_too_long"),
        ("a\x00b", "search.invalid_query"),
        ("a\x02b", "search.invalid_query"),
        ("w*", "search.prefix_too_short"),
        ("-bike -car", "search.only_exclusions"),
        (" ".join(f"w{i}" for i in range(13)), "search.too_many_terms"),
    ],
)
def test_malformed_queries_fail_with_a_reason(text: str, code: str) -> None:
    with pytest.raises(QueryError) as caught:
        parse_query(text)
    assert caught.value.code == code


def test_boundary_lengths_are_accepted() -> None:
    assert parse_query("x" * MAX_QUERY_CHARS).fts() == f'"{"x" * MAX_QUERY_CHARS}"'
    assert len(parse_query(" ".join(f"w{i}" for i in range(12))).terms) == 12
    assert parse_query("he*").fts() == '"he"*'
    assert parse_query("wanted_le*").fts() == '"wanted le"*'
