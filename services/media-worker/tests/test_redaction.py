# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import io
import json
import logging

from openworld_moments.ids import new_id, new_ulid
from openworld_moments.logs import configure_logging
from openworld_moments.redaction import BoundedTail, Redactor


def test_redactor_hides_secrets_bearer_tokens_and_paths() -> None:
    redact = Redactor(["supersecretvalue"])
    text = (
        "token=supersecretvalue Authorization: Bearer abc.def-123 "
        "file /Users/arun/Videos/clip.mp4 and C:\\Users\\arun\\clip.mp4 and \\\\nas\\share\\x.mp4"
    )
    out = redact(text)
    for leaked in ("supersecretvalue", "abc.def-123", "/Users/arun", "C:\\Users", "\\\\nas"):
        assert leaked not in out
    assert "Bearer [redacted]" in out and out.count("[path]") == 3


def test_short_strings_are_not_treated_as_secrets() -> None:
    assert Redactor(["ab"])("ab cd") == "ab cd"


def test_bounded_tail_keeps_the_end_and_redacts() -> None:
    tail = BoundedTail(max_bytes=100, redactor=Redactor(["topsecretvalue"]))
    for i in range(50):
        tail.write(f"line {i} topsecretvalue\n")
    text = tail.text()
    assert len(text) <= 100
    assert text.rstrip().endswith("line 49 [redacted]")
    assert "topsecretvalue" not in text and "line 0 " not in text


def test_bounded_tail_truncates_one_huge_line() -> None:
    tail = BoundedTail(max_bytes=64)
    tail.write("x" * 10_000)
    assert len(tail.text()) <= 64


def test_logging_is_json_and_redacted() -> None:
    stream = io.StringIO()
    configure_logging(Redactor(["log-secret-12345"]), stream=stream)
    logging.getLogger("t").info("value log-secret-12345", extra={"job_id": "job_x"})
    record = json.loads(stream.getvalue().strip())
    assert record["message"] == "value [redacted]" and record["job_id"] == "job_x"


def test_ids_are_sortable_ulids() -> None:
    assert new_ulid(0) < new_ulid(1)
    job_id = new_id("job")
    assert job_id.startswith("job_") and len(job_id) == 30
