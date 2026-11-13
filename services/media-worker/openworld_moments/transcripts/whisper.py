# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional local whisper.cpp adapter (M18).

The engine is an executable the user installs (``whisper-cli``). It is invoked with
a fixed argument array on an owned temporary WAV, through the cancellable runner,
and its full JSON output (segments with token timings and probabilities) is parsed
under strict bounds. Nothing is downloaded, uploaded or logged; transcript text
never appears in errors.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments.media.process import ToolCancelled, ToolError, ToolNotStarted, run_tool
from openworld_moments.native import executable_problem
from openworld_moments.redaction import Redactor

ENGINE = "whisper.cpp"
EXECUTABLE_NAMES = ("whisper-cli", "whisper-cpp")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_SEGMENTS = 20_000
MAX_WORDS_PER_SEGMENT = 1000
MAX_SEGMENT_TEXT = 2000
MAX_WORD_TEXT = 200
_SPECIAL = re.compile(r"^\s*(\[_[A-Z_]+[0-9]*_?\]|<\|[^|]*\|>)\s*$")


class TranscriptionError(Exception):
    """A safe, user-facing failure. Messages never contain transcript text or paths."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TranscriptionCancelled(Exception):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    confidence: float


@dataclass(frozen=True)
class Segment:
    """Source-clip times, as whisper.cpp reports them (milliseconds)."""

    text: str
    start_ms: int
    end_ms: int
    words: tuple[Word, ...]

    @property
    def confidence(self) -> float:
        if not self.words:
            return 0.0
        return round(math.fsum(w.confidence for w in self.words) / len(self.words), 4)


@dataclass(frozen=True)
class Recognition:
    language: str | None
    segments: tuple[Segment, ...]


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(what)
    return float(value)


def _clean(text: Any, limit: int) -> str:
    if not isinstance(text, str):
        raise ValueError("text")
    value = " ".join(text.split())
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("control")
    return value[:limit]


def parse_output(data: bytes, duration_ms: int) -> Recognition:
    """Parse whisper.cpp ``--output-json-full``. Tokens that start with a space begin a
    new word; special tokens (``[_BEG_]``, ``<|en|>``) are skipped. Times are clamped
    into the clip and made monotonic. Raises ``TranscriptionError`` on anything else."""
    try:
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("size")
        doc = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
        if not isinstance(doc, dict) or not isinstance(doc.get("transcription"), list):
            raise ValueError("shape")
        language = (doc.get("result") or {}).get("language")
        if language is not None and (
            not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language)
        ):
            language = None
        if len(doc["transcription"]) > MAX_SEGMENTS:
            raise ValueError("segments")

        def clamp(ms: float) -> int:
            return max(0, min(duration_ms, round(ms)))

        segments: list[Segment] = []
        last_end = 0
        for raw in doc["transcription"]:
            if not isinstance(raw, dict):
                raise ValueError("segment")
            offsets = raw.get("offsets") or {}
            seg_start = clamp(_number(offsets.get("from"), "from"))
            seg_end = clamp(_number(offsets.get("to"), "to"))
            words: list[list[Any]] = []  # [text, start, end, [probabilities]]
            for token in raw.get("tokens") or []:
                if not isinstance(token, dict):
                    raise ValueError("token")
                text = token.get("text")
                if not isinstance(text, str) or _SPECIAL.match(text) or not text.strip():
                    continue
                p = _clamp01(_number(token.get("p", 0), "p"))
                tok = token.get("offsets") or {}
                t0 = clamp(_number(tok.get("from", seg_start), "token from"))
                t1 = clamp(_number(tok.get("to", t0), "token to"))
                if text.startswith(" ") or not words:
                    words.append([text.strip(), t0, max(t0, t1), [p]])
                else:
                    words[-1][0] += text
                    words[-1][2] = max(words[-1][2], t1)
                    words[-1][3].append(p)
            text = _clean(raw.get("text", ""), MAX_SEGMENT_TEXT)
            if not text:
                continue
            seg_start = max(seg_start, last_end)  # segments never go back in time
            seg_end = max(seg_start, seg_end)
            built: list[Word] = []
            cursor = seg_start
            for wtext, w0, w1, probs in words[:MAX_WORDS_PER_SEGMENT]:
                clean = _clean(wtext, MAX_WORD_TEXT)
                if not clean:
                    continue
                start = max(cursor, min(max(w0, seg_start), seg_end))
                end = max(start, min(max(w1, start), seg_end))
                built.append(Word(clean, start, end, round(min(probs), 4)))
                cursor = start
            segments.append(Segment(text, seg_start, seg_end, tuple(built)))
            last_end = seg_end
        return Recognition(language, tuple(segments))
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise TranscriptionError(
            "transcription.invalid_output", "The local speech engine returned invalid output."
        ) from exc


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def sha256_file(path: Path, check: Callable[[], None] = lambda: None) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            check()
            sha.update(block)
    return sha.hexdigest()


@dataclass(frozen=True)
class Engine:
    """A located whisper.cpp executable. ``command`` may hold an interpreter prefix
    (used by tests); ``executable`` is the file whose digest is recorded."""

    command: tuple[str, ...]
    executable: Path
    version: str
    sha256: str


def locate(explicit: str | None = None) -> Path | None:
    """``explicit``, then ``OWM_WHISPER``, then ``whisper-cli``/``whisper-cpp`` on PATH."""
    for candidate in (explicit, os.environ.get("OWM_WHISPER")):
        if candidate:
            path = Path(candidate)
            return path if path.is_file() else None
    for name in EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def probe_engine(
    path: Path,
    cancel: threading.Event | None = None,
    *,
    command: tuple[str, ...] | None = None,
) -> Engine:
    """Check the executable runs and record its version (best effort) and digest.
    ``command`` defaults to the executable itself (tests pass an interpreter prefix)."""
    argv = command or (str(path),)
    if command is None and (problem := executable_problem(path)):
        # M34: wrong architecture or quarantined download; never run it.
        raise TranscriptionError("transcription.engine_incompatible", problem)
    try:
        result = run_tool(
            [*argv, "--help"],
            timeout_s=15,
            cancel=cancel,
            max_stdout=256 * 1024,
            redactor=Redactor([str(path)]),
        )
    except ToolCancelled:
        raise
    except ToolError as exc:
        raise TranscriptionError(
            "transcription.engine_missing", "The local speech engine could not be started."
        ) from exc
    text = result.stdout.decode("utf-8", errors="replace") + result.stderr_tail
    if "--output-json-full" not in text and "-ojf" not in text:
        raise TranscriptionError(
            "transcription.engine_unsupported",
            "This whisper.cpp build does not support full JSON output; update whisper.cpp.",
        )
    match = re.search(r"(?:version|v)\s*([0-9]+\.[0-9]+\.[0-9]+)", text)
    return Engine(argv, path, match[1] if match else "unknown", sha256_file(path))


def transcribe_wav(
    engine: Engine,
    model: Path,
    wav: Path,
    *,
    language: str,
    duration_ms: int,
    threads: int,
    cancel: threading.Event,
) -> Recognition:
    """Run whisper.cpp on ``wav`` (16 kHz mono PCM in an owned folder)."""
    if not re.fullmatch(r"auto|[a-z]{2,3}", language):
        raise TranscriptionError("transcription.invalid_request", "Unsupported language code.")
    out = wav.with_suffix("")
    try:
        result = run_tool(
            [
                *engine.command,
                "-m",
                str(model),
                "-f",
                str(wav),
                "-l",
                language,
                "-t",
                str(max(1, threads)),
                "-ojf",
                "-of",
                str(out),
                "-np",
            ],
            # Slower than real time on old CPUs is fine; a hung engine is not.
            timeout_s=max(600.0, 6 * duration_ms / 1000),
            cancel=cancel,
            max_stdout=1024 * 1024,
            cwd=wav.parent,
            redactor=Redactor([str(wav.parent), str(model.parent), str(engine.executable)]),
        )
    except ToolCancelled as exc:
        raise TranscriptionCancelled from exc
    except ToolNotStarted as exc:
        raise TranscriptionError(
            "transcription.engine_missing", "The local speech engine could not be started."
        ) from exc
    except ToolError as exc:
        raise TranscriptionError(
            "transcription.engine_failed", "The local speech engine stopped unexpectedly."
        ) from exc
    if cancel.is_set():
        raise TranscriptionCancelled
    output = out.with_suffix(".json")
    if result.returncode or not output.is_file():
        raise TranscriptionError(
            "transcription.engine_failed", "The local speech engine could not transcribe this clip."
        )
    if output.stat().st_size > MAX_JSON_BYTES:
        raise TranscriptionError(
            "transcription.invalid_output", "The local speech engine returned invalid output."
        )
    return parse_output(output.read_bytes(), duration_ms)
