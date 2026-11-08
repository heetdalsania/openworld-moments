# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local, conservative review. Findings are computed, never cached as copied text.

Stored decisions contain hashes only and are bound to the exact saved document,
configuration and evidence. They attest creator review, never privacy or legal safety.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from typing import Any, Literal

from openworld_moments_contracts import load, normalize
from pydantic import BaseModel, ConfigDict, Field, model_validator

from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.projects.service import ProjectService
from openworld_moments.storage import Database, EventRepository, NotFoundError, transaction
from openworld_moments.storage.repositories import SCHEMA_VERSION

VERSION = "conservative-review/1"
EMPTY: dict[str, Any] = {"labels": [], "ranges": []}
MAX_FLAGS = 2000
# Explicitly formatted telephone candidates only. Bare scores, coordinates and long
# digit runs are intentionally not phone candidates. Not a numbering-plan validator.
PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ -])?(?:\(\d{3}\)[ -]?|\d{3}[- ])\d{3}[- ]\d{4}(?![\w.])"
)
USERNAME = re.compile(
    r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{2,31}\b|"
    r"\b(?:username|gamertag|player id)\s*[:=]\s*[\w.-]{3,32}",
    re.I,
)


class PrivacyError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class SpoilerRange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_ms: int = Field(ge=0, le=9007199254740991)
    end_ms: int = Field(ge=1, le=9007199254740991)
    label: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def ordered(self) -> SpoilerRange:
        if self.start_ms >= self.end_ms:
            raise ValueError("Choose a non-empty spoiler range.")
        return self


class PrivacyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[str] = Field(max_length=50)
    ranges: list[SpoilerRange] = Field(max_length=100)

    @model_validator(mode="after")
    def bounded(self) -> PrivacyConfig:
        if any(not s.strip() or len(s) > 100 for s in self.labels):
            raise ValueError("Spoiler labels need 1-100 characters.")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["unresolved", "acknowledge", "ignore", "fixed"]


class ReviewChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    decisions: list[Decision] = Field(max_length=MAX_FLAGS)
    acknowledged: bool


def patterns(text: str, labels: list[str]) -> list[tuple[str, float]]:
    result: list[tuple[str, float]] = []
    if PHONE.search(text):
        result.append(("phone", 0.7))
    if USERNAME.search(text):
        result.append(("username", 0.65))
    if any(
        re.search(r"(?<!\w)" + re.escape(label.strip()) + r"(?!\w)", text, re.I) for label in labels
    ):
        result.append(("spoiler", 0.8))
    return result


def source_ranges(document: dict[str, Any], aid: str, start: int, end: int) -> list[dict[str, Any]]:
    ranges = []
    for track in document["project"]["tracks"]:
        for cut in track["segments"]:
            if cut["asset_id"] != aid:
                continue
            a, b = max(start, cut["source_in_ms"]), min(end, cut["source_out_ms"])
            if a < b:
                offset = cut["timeline_start_ms"] - cut["source_in_ms"]
                ranges.append(
                    dict(
                        asset_id=aid,
                        source_start_ms=a,
                        source_end_ms=b,
                        start_ms=a + offset,
                        end_ms=b + offset,
                    )
                )
    return ranges


class PrivacyReviewService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.projects = ProjectService(database)

    def _read(self, conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
        try:
            return self.projects._read(conn, project_id)
        except NotFoundError as exc:
            raise PrivacyError("privacy.not_found", "That project does not exist.", 404) from exc

    def assess(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        document: dict[str, Any] | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        if document is None:
            state = self._read(conn, project_id)
            document, revision = state["document"], state["revision"]
        project = document["project"]
        row = conn.execute(
            "SELECT * FROM privacy_reviews WHERE project_id=?", (project_id,)
        ).fetchone()
        config = json.loads(row["config_json"]) if row else EMPTY
        flags: list[dict[str, Any]] = []
        evidence_identity: list[Any] = []

        def flag(
            category: str,
            confidence: float,
            kind: str,
            evidence: str,
            span: dict[str, Any],
            region: list[float] | None = None,
        ) -> None:
            value = dict(
                category=category,
                confidence=confidence,
                evidence_kind=kind,
                evidence=evidence[:2000],
                **span,
            )
            if region is not None:
                value["region"] = region
            value["id"] = digest([VERSION, value])
            value["decision"] = "unresolved"
            flags.append(value)
            if len(flags) > MAX_FLAGS:
                raise PrivacyError(
                    "privacy.too_many_findings",
                    "More than 2,000 findings. Shorten the project before reviewing.",
                    422,
                )

        def text_flags(
            text: str,
            kind: str,
            span: dict[str, Any],
            region: list[float] | None = None,
            subtitle: bool = False,
            spoiler: bool = False,
        ) -> None:
            found = patterns(text, config["labels"])
            if subtitle:
                found.append(("subtitle", 0.6))
            if spoiler and not any(c == "spoiler" for c, _ in found):
                found.append(("spoiler", 0.6))
            for category, confidence in found:
                flag(category, confidence, kind, text, span, region)

        # Captions are output text, so their exact project ranges are authoritative.
        for cue in project["captions"]:
            span = dict(start_ms=cue["start_ms"], end_ms=cue["end_ms"])
            text_flags(cue["text"], "caption", span, subtitle=True)
        for overlay in project["overlays"]:
            if overlay["kind"] == "text":
                text_flags(
                    overlay["text"],
                    "caption",
                    dict(start_ms=overlay["start_ms"], end_ms=overlay["end_ms"]),
                    overlay["region"],
                )
        sid = project.get("session_id")
        if sid:
            for transcript in conn.execute(
                "SELECT * FROM transcript_segments WHERE session_id=?", (sid,)
            ):
                if (
                    transcript["asset_id"] is None
                    or transcript["source_start_ms"] is None
                    or transcript["source_end_ms"] is None
                ):
                    continue
                spans = source_ranges(
                    document,
                    transcript["asset_id"],
                    transcript["source_start_ms"],
                    transcript["source_end_ms"],
                )
                if spans:
                    evidence_identity.append(tuple(transcript))
                for span in spans:
                    text_flags(transcript["text"], "transcript", span)
                    flag(
                        "speech",
                        0.5,
                        "transcript",
                        "Transcribed audio may include another person. Muting affects the "
                        "complete mixed track.",
                        span,
                    )
            # Event times are session time; map through current membership only when
            # its observation proves the same layout. Stale text still receives a
            # conservative whole retained-source range rather than a false exact seek.
            from openworld_moments.review.service import layout_info

            key, _ = layout_info(conn, sid)
            members: dict[str, tuple[int, int]] = {}
            at = 0
            for i, member in enumerate(
                conn.execute(
                    "SELECT sa.asset_id,a.duration_ms,sa.overlap_with_previous_ms "
                    "FROM session_assets sa JOIN media_assets a ON a.id=sa.asset_id "
                    "WHERE session_id=? ORDER BY order_index",
                    (sid,),
                )
            ):
                hidden = member[2] if i else 0
                members[member[0]] = (at, hidden)
                at += max(0, member[1] - hidden)
            for event in EventRepository(conn).list_for_session(sid):
                e = normalize(event)
                aid = e.get("asset_id")
                observation = conn.execute(
                    "SELECT layout_key FROM event_observations WHERE event_id=?", (e["id"],)
                ).fetchone()
                current = bool(observation and observation[0] == key and aid in members)
                origin, hidden = members.get(aid or "", (0, 0))
                start = e["start_ms"] - origin + hidden if current else 0
                end = e["end_ms"] - origin + hidden if current else 9007199254740991
                spans = source_ranges(document, aid, start, end) if aid else []
                if not spans:
                    # M27 event JSONL exports the whole session, even evidence outside
                    # this cut. Review that text too, with an honest session-time seek.
                    spans = [
                        dict(
                            start_ms=e["start_ms"],
                            end_ms=max(e["end_ms"], e["start_ms"] + 1),
                            time_domain="session",
                        )
                    ]
                if spans:
                    evidence_identity.append([e, observation[0] if observation else None, key])
                for ev in e["evidence"]:
                    for span in spans:
                        if ev["kind"] == "ocr":
                            # Evidence retains the sampled ROI in original source space.
                            text_flags(
                                (
                                    "Earlier analysis; conservative source range. "
                                    if not current
                                    else ""
                                )
                                + ev["text"],
                                "ocr",
                                span,
                                ev["region"],
                                subtitle=e["type"] == "openworld.subtitle",
                                spoiler=bool(e["attributes"].get("spoiler_risk")),
                            )
                        elif ev["kind"] == "transcript":
                            text_flags(ev["text"], "transcript", span)
                        elif ev["kind"] == "audio" and ev.get("feature") == "speech_activity":
                            flag(
                                "speech",
                                0.5,
                                "audio",
                                "Speech-like activity; could also be music. Consider muting this "
                                "range.",
                                span,
                            )
        # Metadata cannot tell game dialogue from voice chat. Always expose uncertainty
        # for every retained source with audio, including clips without transcription.
        for track in project["tracks"]:
            for cut in track["segments"]:
                asset = conn.execute(
                    "SELECT audio_codec,audio_streams_json FROM media_assets WHERE id=?",
                    (cut["asset_id"],),
                ).fetchone()
                evidence_identity.append([cut["asset_id"], tuple(asset) if asset else None])
                if asset and asset[0]:
                    span = dict(
                        asset_id=cut["asset_id"],
                        source_start_ms=cut["source_in_ms"],
                        source_end_ms=cut["source_out_ms"],
                        start_ms=cut["timeline_start_ms"],
                        end_ms=cut["timeline_start_ms"]
                        + cut["source_out_ms"]
                        - cut["source_in_ms"],
                    )
                    flag(
                        "mixed_audio",
                        0.35,
                        "audio_metadata",
                        "The first audio track may mix voice chat, game dialogue and "
                        "music. This editor cannot separate speakers or tracks; muting "
                        "removes all sound in the range.",
                        span,
                    )
        duration = sum(
            c["source_out_ms"] - c["source_in_ms"] for t in project["tracks"] for c in t["segments"]
        )
        for item in config["ranges"]:
            if item["end_ms"] > duration:
                raise PrivacyError(
                    "privacy.range_outside_project",
                    "A saved spoiler range is outside the current project. Edit or "
                    "clear the spoiler ranges.",
                    422,
                )
            flag(
                "spoiler",
                1.0,
                "manual",
                item["label"],
                dict(start_ms=item["start_ms"], end_ms=item["end_ms"]),
            )
        # Deduplicate identical evidence, keeping stable deterministic ordering.
        flags = sorted(
            {f["id"]: f for f in flags}.values(),
            key=lambda f: (f["start_ms"], f["end_ms"], f["category"], f["id"]),
        )
        token = digest([VERSION, document, revision, config, flags, evidence_identity])
        current = bool(row and row["token"] == token and row["acknowledged"])
        decisions = (
            {d["id"]: d["state"] for d in json.loads(row["decisions_json"])}
            if row and row["token"] == token
            else {}
        )
        for f in flags:
            f["decision"] = decisions.get(f["id"], "unresolved")
        summary = dict(
            token=token,
            detector_version=VERSION,
            acknowledged=current,
            unresolved=sum(f["decision"] == "unresolved" for f in flags),
            findings=[dict(id=f["id"], category=f["category"], state=f["decision"]) for f in flags],
        )
        return normalize(
            load(
                "privacy-review",
                dict(
                    schema_version=SCHEMA_VERSION,
                    project_id=project_id,
                    revision=revision,
                    detector_version=VERSION,
                    token=token,
                    **({"session_id": sid} if sid else {}),
                    config=config,
                    flags=flags,
                    current=current and summary["unresolved"] == 0,
                    summary=summary,
                ),
            )
        )

    def get(self, project_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            return self.assess(conn, project_id)

    def configure(self, project_id: str, config: PrivacyConfig) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            self._read(conn, project_id)
            conn.execute(
                "INSERT INTO privacy_reviews(project_id,config_json) VALUES (?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET "
                "config_json=excluded.config_json,token=NULL,decisions_json='[]',acknowledged=0",
                (project_id, canonical(config.model_dump())),
            )
            return self.assess(conn, project_id)

    def decide(self, project_id: str, change: ReviewChange) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            report = self.assess(conn, project_id)
            if report["token"] != change.token:
                raise PrivacyError(
                    "privacy.stale_review",
                    "The project or supporting evidence changed. Scan and review again.",
                )
            ids = {f["id"] for f in report["flags"]}
            decisions = [d.model_dump() for d in change.decisions]
            if (
                len({d["id"] for d in decisions}) != len(decisions)
                or {d["id"] for d in decisions} != ids
            ):
                raise PrivacyError(
                    "privacy.incomplete_decisions",
                    "Choose a decision for every current finding.",
                    422,
                )
            conn.execute(
                "INSERT INTO privacy_reviews VALUES (?,?,?,?,?) ON "
                "CONFLICT(project_id) DO UPDATE SET "
                "token=excluded.token,decisions_json=excluded.decisions_json,acknowledged=excluded.acknowledged",
                (
                    project_id,
                    canonical(report["config"]),
                    change.token,
                    canonical(decisions),
                    int(change.acknowledged),
                ),
            )
            return self.assess(conn, project_id)

    def require(
        self, conn: sqlite3.Connection, project_id: str, document: dict[str, Any], revision: int
    ) -> dict[str, Any]:
        report = self.assess(conn, project_id, document, revision)
        if not report["current"]:
            raise PrivacyError(
                "privacy.review_required",
                "Complete privacy and spoiler review for the current saved "
                "project before exporting.",
            )
        return dict(report["summary"])

    def clear(self, project_id: str) -> dict[str, bool]:
        with contextlib.closing(self.database.connect()) as conn:
            conn.execute("PRAGMA secure_delete=ON")
            with transaction(conn):
                self._read(conn, project_id)
                conn.execute("DELETE FROM privacy_reviews WHERE project_id=?", (project_id,))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"deleted": True}

    def delete_text(self, project_id: str) -> dict[str, bool]:
        """Explicit text-only purge. Does not touch sources, proxies, models or media.

        Session OCR/transcripts (including historical observations and cache keys)
        and this project's copied caption/overlay text and recovery are removed.
        Other projects/externally saved exports and backups remain user-controlled.
        """
        with contextlib.closing(self.database.connect()) as conn:
            conn.execute("PRAGMA secure_delete=ON")
            with transaction(conn):
                state = self._read(conn, project_id)
                doc = state["document"]
                sid = doc["project"].get("session_id")
                active = conn.execute(
                    "SELECT 1 FROM jobs WHERE kind IN ('analyze','transcribe') AND "
                    "state NOT IN ('ready','failed','cancelled') AND "
                    "json_extract(params_json,'$.session_id')=? LIMIT 1",
                    (sid,),
                ).fetchone()
                if active:
                    raise PrivacyError(
                        "privacy.jobs_active",
                        "Cancel or finish this session's analysis and transcription jobs "
                        "before deleting text.",
                    )

                if sid:
                    conn.execute("DELETE FROM transcript_segments WHERE session_id=?", (sid,))
                    conn.execute("DELETE FROM transcript_runs WHERE session_id=?", (sid,))
                    conn.execute(
                        "DELETE FROM events WHERE session_id=? AND "
                        "(EXISTS(SELECT 1 FROM json_each(evidence_json) "
                        "WHERE json_extract(value,'$.kind') IN ('ocr','transcript')) "
                        "OR json_type(attributes_json,'$.text') IS NOT NULL)",
                        (sid,),
                    )
                    conn.execute(
                        "DELETE FROM event_observations WHERE session_id=? AND "
                        "(EXISTS(SELECT 1 FROM json_each(original_json,'$.evidence') "
                        "WHERE json_extract(value,'$.kind') IN ('ocr','transcript')) OR "
                        "json_type(original_json,'$.attributes.text') IS NOT NULL)",
                        (sid,),
                    )
                    conn.execute("DELETE FROM detector_runs WHERE session_id=?", (sid,))
                doc["project"]["captions"] = []
                doc["project"]["overlays"] = [
                    o for o in doc["project"]["overlays"] if o["kind"] != "text"
                ]
                self.projects._write(conn, doc, state["revision"])
                conn.execute(
                    "UPDATE editor_projects SET recovery_json=NULL WHERE project_id=?",
                    (project_id,),
                )
                conn.execute("DELETE FROM privacy_reviews WHERE project_id=?", (project_id,))
            conn.execute("INSERT INTO search_fts(search_fts) VALUES ('optimize')")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"deleted": True}
