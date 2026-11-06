# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watched-folder include/exclude patterns (M07).

Same rules as the desktop host (``apps/desktop/src-tauri/src/watch/patterns.rs``);
both run the shared cases in ``packages/contracts/fixtures/watched-folder/patterns.json``.

* Paths are '/'-separated and relative to the watched folder; matching ignores case.
* A pattern without '/' matches the file name; one with '/' matches the whole path.
* ``*`` and ``?`` stay within one path segment; ``**`` as a whole segment spans any
  number of segments (inside a segment it acts like ``*``).
* A file is a candidate only with a supported video extension, whatever ``include``
  says; an empty ``include`` means every such file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath

from openworld_moments.media.probe import VIDEO_EXTENSIONS

MAX_PATTERNS = 32
MAX_PATTERN_CHARS = 256


@lru_cache(maxsize=512)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i) and (i == 0 or pattern[i - 1] == "/"):
            out.append("(?:[^/]*/)*")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif (
            pattern.startswith("**", i)
            and (i == 0 or pattern[i - 1] == "/")
            and i + 2 == len(pattern)
        ):
            out.append(".*")  # a whole trailing segment: anything
            i += 2
        elif pattern.startswith("**", i):
            out.append("[^/]*")  # inside a segment, '**' is just '*'
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


def matches(pattern: str, relative_path: str) -> bool:
    target = relative_path if "/" in pattern else relative_path.rsplit("/", 1)[-1]
    return compile_pattern(pattern).fullmatch(target) is not None


def is_candidate(relative_path: str, include: Iterable[str], exclude: Iterable[str]) -> bool:
    if PurePosixPath(relative_path).suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    includes = list(include)
    if includes and not any(matches(p, relative_path) for p in includes):
        return False
    return not any(matches(p, relative_path) for p in exclude)


def validate_patterns(value: object, name: str) -> list[str]:
    """Check a pattern list from a request. Raises ValueError (→ 422)."""
    if not isinstance(value, list) or len(value) > MAX_PATTERNS:
        raise ValueError(f"'{name}' must be a list of at most {MAX_PATTERNS} patterns")
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= MAX_PATTERN_CHARS:
            raise ValueError(f"'{name}' patterns must be 1 to {MAX_PATTERN_CHARS} characters")
        if "\\" in item or "\0" in item:
            raise ValueError(f"'{name}' patterns use '/' as the separator")
    return list(value)
