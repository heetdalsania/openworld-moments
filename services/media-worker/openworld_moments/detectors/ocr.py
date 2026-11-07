# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded local OCR adapter. Only derived ROI pixels enter an owned scratch directory."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Protocol

from openworld_moments.detectors.sdk import AnalysisError, Frame, checkpoint
from openworld_moments.media.process import ToolError, ToolNotStarted, run_tool
from openworld_moments.redaction import Redactor

PREPROCESS_VERSION = "text-gray-border-v1"
MAX_MODEL_BYTES = 128 * 1024 * 1024
BORDER = 8


@dataclass(frozen=True)
class Line:
    text: str
    region: tuple[float, ...]
    score: float


@dataclass(frozen=True)
class Reading:
    lines: tuple[Line, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def score(self) -> float:
        return min((line.score for line in self.lines), default=0)


class OcrBackend(Protocol):
    def prepare(self, language: str, cancel: threading.Event) -> dict[str, str]: ...
    def read(self, frame: Frame, mode: str, cancel: threading.Event) -> Reading: ...


def preprocess(frame: Frame, mode: str) -> bytes | None:
    if (
        mode not in ("contrast", "threshold")
        or frame.width <= 0
        or frame.height <= 0
        or frame.width * frame.height > 640 * 128
        or len(frame.pixels) != frame.width * frame.height
    ):
        raise AnalysisError("ocr.invalid_sample", "A bounded grayscale OCR region is required.")
    lo, hi = min(frame.pixels), max(frame.pixels)
    if hi - lo < 20:
        return None
    edge = frame.pixels[: frame.width] + frame.pixels[-frame.width :]
    invert = median(edge) < (lo + hi) / 2
    table = []
    for value in range(256):
        v = max(0, min(255, round((value - lo) * 255 / (hi - lo))))
        v = 255 - v if invert else v
        table.append((0 if v < 128 else 255) if mode == "threshold" else v)
    width, height = frame.width + BORDER * 2, frame.height + BORDER * 2
    image = bytearray([255]) * (width * height)
    mapped = frame.pixels.translate(bytes(table))
    for row in range(frame.height):
        start = (row + BORDER) * width + BORDER
        image[start : start + frame.width] = mapped[row * frame.width : (row + 1) * frame.width]
    return f"P5\n{width} {height}\n255\n".encode() + image


def parse_tsv(data: bytes, frame: Frame) -> Reading:
    """Validate every word box before projecting line boxes into global source ROIs."""
    if frame.region is None:
        raise AnalysisError("ocr.invalid_sample", "OCR samples must identify their source ROI.")
    try:
        text = data.decode("utf-8", errors="strict")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
        expected = [
            "level",
            "page_num",
            "block_num",
            "par_num",
            "line_num",
            "word_num",
            "left",
            "top",
            "width",
            "height",
            "conf",
            "text",
        ]
        if reader.fieldnames != expected:
            raise ValueError("header")
        groups: dict[tuple[int, ...], list[tuple[str, float, int, int, int, int]]] = {}
        count = 0
        for index, row in enumerate(reader):
            if index >= 512 or None in row or any(v is None for v in row.values()):
                raise ValueError("rows")
            if int(row["level"]) != 5:
                continue
            value = " ".join(row["text"].split())
            if not value:
                continue
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("control")
            score = float(row["conf"])
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            if (
                not math.isfinite(score)
                or not 0 <= score <= 100
                or x < 0
                or y < 0
                or w <= 0
                or h <= 0
                or x + w > frame.width + BORDER * 2
                or y + h > frame.height + BORDER * 2
            ):
                raise ValueError("box")
            x0, y0 = max(0, x - BORDER), max(0, y - BORDER)
            x1, y1 = min(frame.width, x + w - BORDER), min(frame.height, y + h - BORDER)
            if x1 <= x0 or y1 <= y0:
                raise ValueError("padding")
            key = tuple(int(row[k]) for k in ("page_num", "block_num", "par_num", "line_num"))
            if any(k < 0 for k in key):
                raise ValueError("line")
            groups.setdefault(key, []).append((value, score / 100, x0, y0, x1, y1))
            count += len(value) + 1
            if count > 500 or len(groups) > 32:
                raise ValueError("text limit")
        rx, ry, rw, rh = frame.region
        lines = []
        for words in groups.values():
            x0, y0 = min(w[2] for w in words), min(w[3] for w in words)
            x1, y1 = max(w[4] for w in words), max(w[5] for w in words)
            lines.append(
                Line(
                    " ".join(w[0] for w in words),
                    (
                        rx + rw * x0 / frame.width,
                        ry + rh * y0 / frame.height,
                        rw * (x1 - x0) / frame.width,
                        rh * (y1 - y0) / frame.height,
                    ),
                    min(w[1] for w in words),
                )
            )
        return Reading(tuple(lines))
    except (UnicodeError, ValueError, KeyError, TypeError, csv.Error) as exc:
        raise AnalysisError(
            "ocr.invalid_output", "The local OCR tool returned invalid bounded TSV."
        ) from exc


class Tesseract:
    def __init__(self, executable: str | None = None) -> None:
        self.requested = executable
        self.executable = ""
        self.language = ""
        self.data_dir = Path()
        self.model_digest = ""
        self.model_stat: tuple[int, int] | None = None

    def prepare(self, language: str, cancel: threading.Event) -> dict[str, str]:
        checkpoint(cancel)
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", language):
            raise AnalysisError(
                "profile.incompatible", "locales.ocr_language: invalid installed language ID"
            )
        location = self.requested or os.environ.get("OWM_TESSERACT") or shutil.which("tesseract")
        if not location and os.name == "nt":
            candidate = (
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
                / "Tesseract-OCR/tesseract.exe"
            )
            if candidate.is_file():
                location = str(candidate)
        if not location or not Path(location).is_file():
            raise AnalysisError(
                "ocr.unavailable",
                "Install local Tesseract 5+ and the selected language data to enable OCR.",
            )
        try:
            version = run_tool(
                [location, "--version"], timeout_s=10, cancel=cancel, max_stdout=32768
            )
            # Distribution builds may prefix their reported version with `v`.
            match = re.search(rb"tesseract v?(\d+\.\d+\.\d+[^\s]*)", version.stdout)
            if version.returncode or not match or int(match[1].split(b".")[0]) < 5:
                raise ValueError("version")
            langs = run_tool(
                [location, "--list-langs"], timeout_s=10, cancel=cancel, max_stdout=32768
            )
            listing = langs.stdout.decode("utf-8", errors="strict")
            directory = re.search(r'List of available languages in "([^"]+)"', listing)
            if langs.returncode or not directory or language not in listing.splitlines()[1:]:
                raise ValueError("language")
            data_dir = Path(directory[1])
            model = data_dir / f"{language}.traineddata"
            stat = model.stat()
            if not model.is_file() or not 0 < stat.st_size <= MAX_MODEL_BYTES:
                raise ValueError("model")
            sha = hashlib.sha256()
            with model.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    checkpoint(cancel)
                    sha.update(block)
            after = model.stat()
            if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("model changed")
            self.executable, self.language, self.data_dir = location, language, data_dir
            self.model_digest = sha.hexdigest()
            self.model_stat = (after.st_size, after.st_mtime_ns)
            return {
                "ocr_engine": "tesseract-" + match[1].decode("ascii"),
                "ocr_language": language,
                "ocr_model_sha256": self.model_digest,
                "ocr_preprocess": PREPROCESS_VERSION,
            }
        except (OSError, ValueError, ToolError) as exc:
            # Cancellation must retain the worker's existing cancellation semantics.
            from openworld_moments.media.process import ToolCancelled

            if isinstance(exc, ToolCancelled):
                raise
            raise AnalysisError(
                "ocr.unavailable",
                "Local OCR or its language data is unavailable; other detectors remain usable.",
            ) from exc

    def read(self, frame: Frame, mode: str, cancel: threading.Event) -> Reading:
        checkpoint(cancel)
        self.check_model_stat()
        image = preprocess(frame, mode)
        if image is None:
            return Reading()
        if not self.executable:
            raise AnalysisError("ocr.unavailable", "Prepare the local OCR adapter first.")
        try:
            with tempfile.TemporaryDirectory(prefix="owm-ocr-") as tmp:
                root = Path(tmp)
                (root / "input.pgm").write_bytes(image)
                result = run_tool(
                    [
                        self.executable,
                        "input.pgm",
                        "stdout",
                        "--tessdata-dir",
                        str(self.data_dir),
                        "-l",
                        self.language,
                        "--oem",
                        "1",
                        "--psm",
                        "6",
                        "--dpi",
                        "150",
                        "tsv",
                    ],
                    timeout_s=10,
                    cancel=cancel,
                    max_stdout=256 * 1024,
                    cwd=root,
                    redactor=Redactor([tmp, self.executable, str(self.data_dir)]),
                )
            if result.returncode:
                raise AnalysisError(
                    "ocr.process_failed", "Local OCR failed; no replacement events were saved."
                )
            checkpoint(cancel)
            self.check_model_stat()
            return parse_tsv(result.stdout, frame)
        except ToolNotStarted as exc:
            raise AnalysisError(
                "ocr.unavailable", "The local OCR executable is unavailable."
            ) from exc

    def check_model_stat(self) -> None:
        if self.model_stat is None:
            return
        try:
            stat = (self.data_dir / f"{self.language}.traineddata").stat()
            if (stat.st_size, stat.st_mtime_ns) == self.model_stat:
                return
        except OSError:
            pass
        raise AnalysisError("ocr.model_changed", "OCR language data changed; analyze again.")

    def verify_model(self, cancel: threading.Event) -> None:
        self.check_model_stat()
        sha = hashlib.sha256()
        with (self.data_dir / f"{self.language}.traineddata").open("rb") as stream:
            while block := stream.read(1024 * 1024):
                checkpoint(cancel)
                sha.update(block)
        self.check_model_stat()
        if sha.hexdigest() != self.model_digest:
            raise AnalysisError("ocr.model_changed", "OCR language data changed; analyze again.")
