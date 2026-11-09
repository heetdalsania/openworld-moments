# SPDX-License-Identifier: AGPL-3.0-or-later
"""Data roots for the repository and the frozen per-user application."""

from __future__ import annotations

import sys
from pathlib import Path


def data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parents[3]
