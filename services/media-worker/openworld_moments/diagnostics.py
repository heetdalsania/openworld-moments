# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diagnostics report (M31): what a maintainer needs to help, and nothing personal.

The report is built from facts the worker already has, never from footage:

* app, runtime and tool versions plus the system check;
* counts of what is in the library (no titles, names, paths or hashes of media);
* job totals by kind and state, and recent failures by error code.

Failure messages are left out by default because they can mention file names. When the
user opts in, each message is still passed through the path/token redactor and a file
name scrubber. The finished text is redacted once more before it is returned, so the
preview the user sees is exactly what is saved.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openworld_moments.redaction import Redactor

SCHEMA_VERSION = "1.24"
RECENT_FAILURES = 20
MAX_MESSAGE = 300

# Counted, never listed. Missing tables (older or partial databases) count as absent.
LIBRARY_TABLES: tuple[tuple[str, str], ...] = (
    ("clips", "media_assets"),
    ("sessions", "sessions"),
    ("projects", "editor_projects"),
    ("renders", "render_jobs"),
    ("watched_folders", "watched_folders"),
    ("collections", "collections_v2"),
    ("event_observations", "event_observations"),
    ("transcript_segments", "transcript_segments"),
)

# A bare file name with a media, image, data or archive extension (paths are handled
# by the redactor). Spaces are allowed inside a quoted name.
_QUOTED_FILE = re.compile(
    r"([\"'])[^\"'\r\n]{1,255}\.(?:[A-Za-z0-9]{2,5})\1",
)
_BARE_FILE = re.compile(
    r"(?<![\w.])[^\s\"'/\\:]{1,255}\.(?:mp4|m4v|mov|mkv|webm|avi|ts|m2ts|mts|wmv|flv|"
    r"jpe?g|png|gif|webp|heic|bmp|wav|mp3|m4a|aac|flac|ogg|opus|json|jsonl|srt|vtt|csv|"
    r"otio|fcpxml|txt|log|zip|7z|tar|gz|bin|gguf|db|sqlite)\b",
    re.IGNORECASE,
)
FILE = "[file]"


def scrub_message(text: str, redactor: Redactor) -> str:
    """Redact paths and secrets, then file names, then bound the length."""
    text = redactor(text)
    text = _QUOTED_FILE.sub(lambda m: m.group(1) + FILE + m.group(1), text)
    text = _BARE_FILE.sub(FILE, text)
    text = " ".join(text.split())
    return text[:MAX_MESSAGE] or "[empty]"


def library_counts(database_path: Path) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    try:
        conn = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {**{name: None for name, _ in LIBRARY_TABLES}, "database_schema": None}
    try:
        for name, table in LIBRARY_TABLES:
            try:
                # Table names come from the fixed tuple above, never from input.
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
                counts[name] = int(row[0])
            except sqlite3.Error:
                counts[name] = None
        try:
            counts["database_schema"] = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error:
            counts["database_schema"] = None
    finally:
        conn.close()
    return counts


def _job_fields(job: Any) -> tuple[str, str, Any, str]:
    """(kind, state, error, created_at) from a contract Job or a plain mapping."""
    if isinstance(job, Mapping):
        return (
            str(job.get("kind", "")),
            str(job.get("state", "")),
            job.get("error"),
            str(job.get("created_at", "")),
        )
    created = getattr(job, "created_at", "")
    created_text = created.isoformat() if isinstance(created, datetime) else str(created)
    return str(job.kind), str(getattr(job.state, "value", job.state)), job.error, created_text


def _error_field(error: Any, name: str) -> Any:
    if error is None:
        return None
    if isinstance(error, Mapping):
        return error.get(name)
    return getattr(error, name, None)


def job_summary(
    jobs: Iterable[Any], *, include_messages: bool, redactor: Redactor
) -> dict[str, Any]:
    totals: Counter[tuple[str, str]] = Counter()
    failures: list[dict[str, Any]] = []
    for job in jobs:
        kind, state, error, created = _job_fields(job)
        totals[(kind, state)] += 1
        if state != "failed" or len(failures) >= RECENT_FAILURES:
            continue
        failure: dict[str, Any] = {
            "kind": kind,
            "code": str(_error_field(error, "code") or "unknown"),
            "retryable": bool(_error_field(error, "retryable")),
            "date": created[:10] or "unknown",
        }
        message = _error_field(error, "message")
        if include_messages and isinstance(message, str):
            failure["message"] = scrub_message(message, redactor)
        failures.append(failure)
    return {
        "totals": [
            {"kind": kind, "state": state, "count": count}
            for (kind, state), count in sorted(totals.items())
        ],
        "recent_failures": failures,
    }


def model_summary(status: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not status:
        return []
    return [
        {
            "name": str(model.get("name", ""))[:100],
            "revision": str(model.get("revision", ""))[:100],
            "installed": model.get("active_sha256") is not None,
        }
        for model in status.get("models", [])
        if isinstance(model, Mapping)
    ]


def build_report(
    *,
    worker: Mapping[str, str],
    doctor_report: Mapping[str, Any] | None,
    database_path: Path,
    jobs: Sequence[Any],
    models: Mapping[str, Any] | None,
    include_messages: bool,
    secrets: Iterable[str] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    redactor = Redactor(secrets)
    generated = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    system: dict[str, Any] = {"available": doctor_report is not None}
    if doctor_report is not None:
        system.update(
            {
                "ready": bool(doctor_report.get("ready")),
                "packaged": bool(doctor_report.get("packaged")),
                "platform": str(doctor_report.get("platform", ""))[:100],
                "architecture": str(doctor_report.get("architecture", ""))[:100],
                "free_mib": int(doctor_report.get("free_bytes", 0)) // 1024**2,
                "checks": [
                    {
                        "id": str(c.get("id", ""))[:100],
                        "status": str(c.get("status", "")),
                        "message": scrub_message(str(c.get("message", "")), redactor),
                    }
                    for c in doctor_report.get("checks", [])
                ],
                "tools": [
                    {
                        "name": str(t.get("name", ""))[:100],
                        "version": scrub_message(str(t.get("version", "")), redactor)[:100],
                        "origin": str(t.get("origin", ""))[:100],
                    }
                    for t in doctor_report.get("tools", [])
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "worker": {key: str(value)[:100] for key, value in sorted(worker.items())},
        "system": system,
        "library": library_counts(database_path),
        "models": model_summary(models),
        "jobs": job_summary(jobs, include_messages=include_messages, redactor=redactor),
        "privacy": {
            "footage": "never included",
            "file_names": "removed",
            "paths": "removed",
            "tokens": "removed",
            "failure_messages": "included, redacted" if include_messages else "omitted",
        },
    }


def render(report: Mapping[str, Any], secrets: Iterable[str] = ()) -> str:
    """The exact text that is previewed and saved, redacted once more as a whole."""
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return Redactor(secrets)(text)


def filename(report: Mapping[str, Any]) -> str:
    day = str(report.get("generated_at", ""))[:10].replace("-", "")
    return f"openworld-moments-diagnostics-{day if day.isdigit() else 'report'}.json"
