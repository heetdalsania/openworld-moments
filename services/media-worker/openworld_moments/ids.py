# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract IDs: '<prefix>_' + 26-character Crockford base32 ULID."""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = frozenset({"ast", "ses", "evt", "job", "prj", "seg", "cor", "col"})


def new_ulid(timestamp_ms: int | None = None) -> str:
    """48-bit millisecond timestamp + 80 random bits, sortable by creation time."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown ID prefix {prefix!r}")
    return f"{prefix}_{new_ulid()}"
