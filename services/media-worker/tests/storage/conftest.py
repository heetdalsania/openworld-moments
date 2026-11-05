# SPDX-License-Identifier: AGPL-3.0-or-later
"""Temporary database helpers for storage tests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.storage import Database

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_FIXTURES = REPO_ROOT / "packages" / "contracts" / "fixtures"
DATA_FIXTURES = Path(__file__).parent / "fixtures"


def contract_fixtures(contract: str) -> list[Path]:
    return sorted((CONTRACT_FIXTURES / contract / "valid").glob("*.json"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


@pytest.fixture
def database(tmp_path: Path) -> Database:
    """A fresh library database migrated to head in a temporary folder."""
    return Database.open(tmp_path / "library" / "database.sqlite3")


@pytest.fixture
def conn(database: Database) -> Iterator[sqlite3.Connection]:
    connection = database.connect()
    try:
        yield connection
    finally:
        connection.close()
