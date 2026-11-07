# SPDX-License-Identifier: Apache-2.0
"""Trusted built-in detector API. No paths, mutable models, database, or writers."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

SDK_VERSION = "1.0.0"


class AnalysisCancelled(Exception):
    pass


class AnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Frame:
    source_ms: int
    width: int
    height: int
    pixels: bytes  # packed, row-major grayscale, 0..255


@dataclass(frozen=True, slots=True)
class Detection:
    type: str
    start_ms: int  # source coordinates; host maps to unique session time
    end_ms: int
    confidence: float
    evidence: tuple[Mapping[str, Any], ...]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    asset_id: str
    duration_ms: int
    frames: tuple[Frame, ...]
    regions: Mapping[str, tuple[float, ...]]
    settings: Mapping[str, Any]
    vocabulary: Mapping[str, tuple[str, ...]]
    check_cancelled: Callable[[], None]
    progress: Callable[[int, int], None]


class Detector(Protocol):
    id: str
    version: str
    capabilities: frozenset[str]
    required_regions: frozenset[str]

    def setup(self, context: AnalysisContext) -> None: ...

    def detect(self, context: AnalysisContext) -> Iterable[Detection]: ...

    def close(self) -> None: ...


def checkpoint(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise AnalysisCancelled
