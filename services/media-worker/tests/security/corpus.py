# SPDX-License-Identifier: AGPL-3.0-or-later
"""Malformed-input corpus (M30), generated at test time; nothing binary is committed.

Deterministic for a seed. Structural cases model known attack shapes (empty and
tiny files, disguised formats, absurd box sizes); mutants are seeded corruptions of
a real 1-second MP4, the classic way fuzzers find parser bugs.
"""

from __future__ import annotations

import random
import struct
from pathlib import Path


def box(kind: bytes, payload: bytes = b"", size: int | None = None) -> bytes:
    return struct.pack(">I", len(payload) + 8 if size is None else size) + kind + payload


def structural() -> dict[str, bytes]:
    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    rng = random.Random(30)  # noqa: S311 - deterministic test data
    return {
        "empty.mp4": b"",
        "one-byte.mp4": b"\x00",
        "random-64k.mp4": rng.randbytes(64 * 1024),
        "text.mov": b"this is a plain text file, not a video\n" * 100,
        "png-header.mov": b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048,
        "zip-header.mkv": b"PK\x03\x04" + b"\x00" * 2048,
        "ebml-garbage.mkv": b"\x1aE\xdf\xa3" + rng.randbytes(4096),
        "ftyp-only.mp4": ftyp,
        "ftyp-max-size.mp4": box(b"ftyp", b"isom", size=0xFFFFFFFF) + b"\x00" * 64,
        "huge-moov.mp4": ftyp + box(b"moov", b"\x00" * 64, size=0x7FFFFFFF),
        "box-size-zero-loop.mp4": ftyp + box(b"free", size=0) * 32,
        "64bit-size-overflow.mp4": ftyp + struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 2**63),
        "nested-boxes.mp4": ftyp + box(b"moov", box(b"trak", box(b"mdia", box(b"minf") * 200))),
    }


def truncations(valid: bytes, cuts: int = 10) -> dict[str, bytes]:
    step = max(1, len(valid) // (cuts + 1))
    return {f"truncated-{i:02d}.mp4": valid[: i * step] for i in range(1, cuts + 1)}


def mutants(valid: bytes, count: int = 40, seed: int = 30) -> dict[str, bytes]:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    out = {}
    for i in range(count):
        data = bytearray(valid)
        strategy = i % 4
        if strategy == 0:  # scattered bit flips
            for _ in range(rng.randint(1, 64)):
                data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        elif strategy == 1:  # zero a block
            start = rng.randrange(len(data))
            data[start : start + rng.randint(16, 4096)] = b"\x00" * min(4096, len(data) - start)
        elif strategy == 2:  # duplicate a chunk somewhere else
            start = rng.randrange(len(data) // 2)
            chunk = data[start : start + rng.randint(64, 8192)]
            at = rng.randrange(len(data))
            data[at:at] = chunk
        else:  # overwrite header bytes with 0xFF
            for _ in range(rng.randint(1, 16)):
                data[rng.randrange(min(len(data), 4096))] = 0xFF
        out[f"mutant-{i:02d}.mp4"] = bytes(data)
    return out


#: Names an attacker or a careless file system might hand us.
HOSTILE_NAMES = [
    "../../../etc/passwd.mp4",
    "..\\..\\Windows\\System32\\evil.mov",
    "C:\\Users\\victim\\clip.mp4",
    "/absolute/clip.mkv",
    "CON.mp4",
    "nul.mov",
    "COM1.mkv",
    "clip\u202emp4.exe",  # right-to-left override hiding an extension
    "a" * 400 + ".mp4",
    "nul\x00byte.mp4",
    "line\nbreak.mp4",
    " .mp4",
    "....mp4",
    "%2e%2e%2fencoded.mp4",
    "\u0000",
    "",
]


def write(folder: Path, files: dict[str, bytes]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in sorted(files.items()):
        path = folder / name
        path.write_bytes(data)
        paths.append(path)
    return paths
