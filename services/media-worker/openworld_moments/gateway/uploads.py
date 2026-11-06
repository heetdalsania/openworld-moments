# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upload rules for the phone gateway (M10): filename sanitizing, the media allowlist,
content sniffing, and limits. Pure functions, so the threat cases are easy to test."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Extensions a phone may send (PlayStation App and camera clips). Probing during the
#: import (M04/M05) decides whether a file really is usable video.
ALLOWED_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm"})
#: ISO-BMFF (MP4/MOV) top-level box types that may come first in a file.
_BMFF_BOXES = frozenset({b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip", b"pnot"})
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"  # Matroska / WebM
SNIFF_BYTES = 12

MAX_NAME_CHARS = 120
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 10 * 1024**3
    max_files: int = 100
    max_total_bytes: int = 50 * 1024**3
    #: Free space kept on the library volume after every accepted upload.
    free_space_margin: int = 1024**3
    #: Uploads that may run at the same time.
    max_concurrent: int = 2


class Rejected(Exception):
    """An upload is refused. ``reason`` is a stable code shown to the phone and desktop."""

    def __init__(self, status: int, reason: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message


def extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def sanitize_name(raw: str | None, fallback_index: int) -> str:
    """A safe single file name for staging, derived from what the phone sent.

    Only the last path component survives; control and reserved characters are
    replaced; leading dots, trailing dots and spaces, Windows device names, and
    overlong names are fixed. The extension must be allowed (checked separately).
    """
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFC", name)
    name = _UNSAFE.sub("_", name).strip()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 and dot < len(name) - 1 else ""  # case kept
    stem = name[:dot] if ext else name.rstrip(".")
    stem = stem.lstrip(".").rstrip(". ")
    if not stem or stem.split(".")[0].lower() in _WINDOWS_RESERVED:
        stem = f"clip-{fallback_index:04d}" if not stem else f"_{stem}"
    budget = MAX_NAME_CHARS - len(ext)
    if len(stem) > budget:
        stem = stem[:budget].rstrip(". ")
    return f"{stem}{ext}"


def check_name(name: str) -> None:
    if extension(name) not in ALLOWED_EXTENSIONS:
        raise Rejected(
            415,
            "unsupported_type",
            "Only video files can be sent: MP4, MOV, M4V, MKV, or WebM.",
        )


def sniff(head: bytes, name: str) -> None:
    """Refuse files whose first bytes do not match their video extension."""
    ext = extension(name)
    if ext in (".mkv", ".webm"):
        ok = head.startswith(_EBML_MAGIC)
    else:
        ok = len(head) >= 8 and head[4:8] in _BMFF_BOXES
    if not ok:
        raise Rejected(415, "not_video", "This file does not look like a video.")


def check_size(
    declared: int | None, *, limits: Limits, accepted_files: int, accepted_bytes: int, free: int
) -> int:
    """Validate the declared size before any byte is written; returns it."""
    if declared is None:
        raise Rejected(411, "length_required", "The upload did not say how large it is.")
    if declared <= 0:
        raise Rejected(400, "empty", "The file is empty.")
    if declared > limits.max_file_bytes:
        raise Rejected(
            413,
            "too_large",
            f"Files can be at most {limits.max_file_bytes // 1024**3} GB.",
        )
    if accepted_files >= limits.max_files:
        raise Rejected(
            413, "too_many_files", f"A session accepts at most {limits.max_files} files."
        )
    if accepted_bytes + declared > limits.max_total_bytes:
        raise Rejected(
            413,
            "session_full",
            f"A session accepts at most {limits.max_total_bytes // 1024**3} GB in total.",
        )
    if free - declared < limits.free_space_margin:
        raise Rejected(507, "disk_full", "The computer does not have enough free space.")
    return declared
