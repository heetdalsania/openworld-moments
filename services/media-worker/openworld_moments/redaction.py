# SPDX-License-Identifier: AGPL-3.0-or-later
"""Redaction for logs and captured tool output, plus a bounded stderr tail.

Logs and error reports must never contain the worker token, other secrets, or
full user paths (spec 14.1-14.3).
"""

from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Iterable

_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
# Absolute paths: POSIX home/volume paths and Windows drive or UNC paths.
_PATHS = re.compile(
    r"(?:(?<![\w.])/(?:Users|home|Volumes|mnt|media|private|var/folders)/[^\s'\"]+)"
    r"|(?:\b[A-Za-z]:\\[^\s'\"]+)"
    r"|(?:\\\\[^\s'\"\\]+\\[^\s'\"]+)"
)
REDACTED = "[redacted]"
REDACTED_PATH = "[path]"


class Redactor:
    """Replaces known secret values, bearer tokens, and user paths."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = sorted({s for s in secrets if len(s) >= 8}, key=len, reverse=True)

    def add_secret(self, secret: str) -> None:
        if len(secret) >= 8 and secret not in self._secrets:
            self._secrets = sorted([*self._secrets, secret], key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        text = _BEARER.sub(lambda m: m.group(1) + REDACTED, text)
        return _PATHS.sub(REDACTED_PATH, text)


class BoundedTail:
    """Keeps the last ``max_bytes`` of text, line-oriented and redacted on read.

    Used for subprocess stderr so a chatty tool cannot exhaust memory and error
    reports carry only the useful end of the output.
    """

    def __init__(self, max_bytes: int = 8192, redactor: Redactor | None = None) -> None:
        if max_bytes < 64:
            raise ValueError("max_bytes must be at least 64")
        self.max_bytes = max_bytes
        self._redactor = redactor or Redactor()
        self._lines: deque[str] = deque()
        self._size = 0
        self._dropped = False
        self._lock = threading.Lock()

    def write(self, chunk: str) -> None:
        with self._lock:
            for line in chunk.splitlines(keepends=True):
                if len(line) > self.max_bytes:
                    line = line[-self.max_bytes :]
                    self._dropped = True
                self._lines.append(line)
                self._size += len(line)
                while self._size > self.max_bytes and self._lines:
                    self._size -= len(self._lines.popleft())
                    self._dropped = True

    def text(self) -> str:
        with self._lock:
            body = "".join(self._lines)
            prefix = "[earlier output truncated]\n" if self._dropped else ""
        return self._redactor(prefix + body)[-self.max_bytes :]
