# SPDX-License-Identifier: AGPL-3.0-or-later
"""User query text to a safe FTS5 expression (M26).

The grammar is deliberately small. User text never reaches FTS5 as syntax: every
term is re-emitted as a quoted string, so operators, column filters, parentheses
and stray quotes are just text.

    query    := item*                       (implicit AND)
    item     := ["-"] (phrase | word)       ("-" excludes; needs one positive item)
    phrase   := '"' any-text '"' ["*"]      (an unclosed quote runs to the end)
    word     := non-space-text ["*"]        ("*" = prefix match, 2+ letters first)

Words are split into letters/digits the way the index tokenizer splits them, so
``wanted_level`` and ``wanted-level`` both match the indexed words ``wanted level``.
Items without any letter or digit are ignored and reported back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUERY_CHARS = 256
MAX_TERMS = 12
MIN_PREFIX_CHARS = 2

# Letters and digits in any script; underscores are separators, like unicode61.
_WORD = re.compile(r"[^\W_]+")
_ITEM = re.compile(r'(-?)(?:"([^"]*)(?:"(\*?)|$)|(\S+))')


class QueryError(ValueError):
    """The query cannot be searched. ``code``/``message`` are user-safe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Term:
    words: tuple[str, ...]
    phrase: bool = False
    prefix: bool = False
    exclude: bool = False

    @property
    def text(self) -> str:
        joined = " ".join(self.words)
        shown = f'"{joined}"' if self.phrase else joined
        return ("-" if self.exclude else "") + shown + ("*" if self.prefix else "")

    def fts(self) -> str:
        # Words contain only letters and digits, so they can never close the quote.
        quoted = '"' + " ".join(self.words) + '"'
        return quoted + ("*" if self.prefix else "")


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    terms: tuple[Term, ...] = ()
    ignored: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.terms

    def fts(self) -> str | None:
        """The MATCH expression, or None for a filter-only search."""
        positive = [t.fts() for t in self.terms if not t.exclude]
        if not positive:
            return None
        expression = " AND ".join(positive)
        for term in self.terms:
            if term.exclude:
                expression += " NOT " + term.fts()
        return expression


def parse_query(text: str) -> ParsedQuery:
    if len(text) > MAX_QUERY_CHARS:
        raise QueryError(
            "search.query_too_long", f"Searches are limited to {MAX_QUERY_CHARS} characters."
        )
    if any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        raise QueryError("search.invalid_query", "The search contains control characters.")
    terms: list[Term] = []
    ignored: list[str] = []
    for match in _ITEM.finditer(text):
        minus, quoted, star, bare = match.groups()
        raw = quoted if quoted is not None else bare or ""
        prefix = bool(star)
        if quoted is None and raw.endswith("*"):
            raw, prefix = raw.rstrip("*"), True
        # FTS5 lowercases and folds diacritics with the index tokenizer itself.
        words = tuple(_WORD.findall(raw))
        if not words:
            ignored.append(match.group(0))
            continue
        phrase = quoted is not None or len(words) > 1
        # FTS5 applies a trailing * to the last word of a phrase.
        if prefix and len(words[-1]) < MIN_PREFIX_CHARS:
            raise QueryError(
                "search.prefix_too_short",
                f"Type at least {MIN_PREFIX_CHARS} letters before * to search by prefix.",
            )
        terms.append(Term(words, phrase=phrase, prefix=prefix, exclude=bool(minus)))
    if len(terms) > MAX_TERMS:
        raise QueryError("search.too_many_terms", f"Use at most {MAX_TERMS} words or phrases.")
    if terms and all(t.exclude for t in terms):
        raise QueryError(
            "search.only_exclusions", "Add at least one word to search for, not only exclusions."
        )
    return ParsedQuery(tuple(terms), tuple(ignored))
