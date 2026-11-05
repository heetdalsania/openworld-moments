# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured JSON logging to stderr with redaction.

stdout is reserved for the worker's startup protocol, so logs always go to
stderr. Every record passes through a Redactor before it is written.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

from openworld_moments.redaction import Redactor

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return self.redactor(json.dumps(payload, default=str, ensure_ascii=False))


def configure_logging(
    redactor: Redactor, *, level: int = logging.INFO, stream: TextIO | None = None
) -> None:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter(redactor))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's own loggers: keep errors, drop access logs (they contain paths and headers).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # Python warnings would otherwise print raw text to stderr.
    logging.captureWarnings(True)
