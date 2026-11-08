# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search filters and collection rules (M26).

One closed model serves both a search request's filters and a rule-based
collection. Every field compiles to a fixed SQL fragment over ``search_documents``
with bound parameters; no user text becomes SQL. Lists match any of their values;
different fields must all match.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["clip", "session", "event", "transcript", "project"]
ReviewState = Literal["unreviewed", "confirmed", "corrected", "rejected"]
SourceKind = Literal["xbox", "playstation", "obs", "capture_card", "phone_upload", "other"]
SessionId = Annotated[str, Field(pattern=r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")]
EventType = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=128)]
Timestamp = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3])"
        r":[0-5][0-9]:[0-5][0-9](\.[0-9]{1,3})?Z$"
    ),
]
MAX_DURATION_MS = 7 * 24 * 3600 * 1000

KIND_NOUNS = {
    "clip": "a clip",
    "session": "a session",
    "event": "an event",
    "transcript": "a transcript span",
    "project": "a project",
}


def _unique(values: list[Any]) -> list[Any]:
    if len(set(values)) != len(values):
        raise ValueError("values must be unique")
    return values


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[Kind] = Field(default_factory=list, max_length=5)
    session_ids: list[SessionId] = Field(default_factory=list, max_length=50)
    source_kinds: list[SourceKind] = Field(default_factory=list, max_length=6)
    event_types: list[EventType] = Field(default_factory=list, max_length=50)
    review_states: list[ReviewState] = Field(default_factory=list, max_length=4)
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    occurred_from: Timestamp | None = None
    occurred_to: Timestamp | None = None
    min_duration_ms: int | None = Field(default=None, ge=0, le=MAX_DURATION_MS)
    max_duration_ms: int | None = Field(default=None, ge=0, le=MAX_DURATION_MS)

    _unique_lists = field_validator(
        "kinds", "session_ids", "source_kinds", "event_types", "review_states"
    )(_unique)

    @model_validator(mode="after")
    def _ranges(self) -> SearchFilters:
        if (
            self.occurred_from
            and self.occurred_to
            and _time(self.occurred_to) < _time(self.occurred_from)
        ):
            raise ValueError("occurred_to must not be before occurred_from")
        if (
            self.min_duration_ms is not None
            and self.max_duration_ms is not None
            and self.max_duration_ms < self.min_duration_ms
        ):
            raise ValueError("max_duration_ms must not be below min_duration_ms")
        return self

    def compact(self) -> dict[str, Any]:
        return self.model_dump(exclude_defaults=True)

    def sql(self, alias: str = "d") -> tuple[str, list[Any]]:
        """``AND``-joined conditions (or ``1``) and their parameters."""
        clauses: list[str] = []
        params: list[Any] = []

        def any_of(column: str, values: list[Any]) -> None:
            if values:
                clauses.append(f"{alias}.{column} IN ({','.join('?' * len(values))})")
                params.extend(values)

        any_of("kind", list(self.kinds))
        any_of("session_id", list(self.session_ids))
        any_of("source_kind", list(self.source_kinds))
        any_of("event_type", list(self.event_types))
        any_of("review_state", list(self.review_states))
        if self.min_confidence is not None:
            clauses.append(f"{alias}.confidence >= ?")
            params.append(self.min_confidence)
        if self.occurred_from:
            clauses.append(f"julianday({alias}.occurred_at) >= julianday(?)")
            params.append(self.occurred_from)
        if self.occurred_to:
            clauses.append(f"julianday({alias}.occurred_at) <= julianday(?)")
            params.append(self.occurred_to)
        if self.min_duration_ms is not None:
            clauses.append(f"{alias}.duration_ms >= ?")
            params.append(self.min_duration_ms)
        if self.max_duration_ms is not None:
            clauses.append(f"{alias}.duration_ms <= ?")
            params.append(self.max_duration_ms)
        return (" AND ".join(clauses) or "1"), params

    def explain(self, doc: Mapping[str, Any]) -> list[dict[str, str]]:
        """Why ``doc`` satisfies each field that is set, using the document's values."""
        reasons: list[dict[str, str]] = []

        def add(criterion: str, detail: str) -> None:
            reasons.append({"criterion": criterion, "detail": detail})

        if self.kinds:
            add("kind", f"Is {KIND_NOUNS[doc['kind']]} ({_listing(self.kinds)} allowed)")
        if self.session_ids:
            add("session", f"Belongs to session {doc['session_id']}")
        if self.source_kinds:
            add("source", f"Source is {doc['source_kind']} ({_listing(self.source_kinds)} allowed)")
        if self.event_types:
            add("event_type", f"Label is {doc['event_type']}")
        if self.review_states:
            add("review_state", f"Review state is {doc['review_state']}")
        if self.min_confidence is not None:
            add(
                "confidence",
                f"Confidence {doc['confidence']:.2f} is at least {self.min_confidence:.2f}",
            )
        if self.occurred_from or self.occurred_to:
            window = f"{self.occurred_from or 'any time'} to {self.occurred_to or 'any time'}"
            add("date", f"Date {doc['occurred_at']} is within {window}")
        if self.min_duration_ms is not None or self.max_duration_ms is not None:
            bounds = []
            if self.min_duration_ms is not None:
                bounds.append(f"at least {self.min_duration_ms / 1000:g} s")
            if self.max_duration_ms is not None:
                bounds.append(f"at most {self.max_duration_ms / 1000:g} s")
            add(
                "duration",
                f"Duration {doc['duration_ms'] / 1000:g} s is {' and '.join(bounds)}",
            )
        return reasons


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=256)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    offset: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=25, ge=1, le=100)


class CollectionRule(BaseModel):
    """A saved search: the same query grammar and filters, version 1."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    query: str = Field(default="", max_length=256)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="after")
    def _not_everything(self) -> CollectionRule:
        if not self.query.strip() and not self.filters.compact():
            raise ValueError("A rule needs search words or at least one filter.")
        return self

    def canonical(self) -> dict[str, Any]:
        return {"version": 1, "query": self.query, "filters": self.filters.compact()}


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _listing(values: Sequence[str]) -> str:
    return ", ".join(values)
