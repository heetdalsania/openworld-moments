# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures: the TypeScript suite runs the same files with the same expectations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES

from openworld_moments_contracts import (
    CONTRACTS,
    ContractError,
    ContractVersionError,
    load,
    normalize,
)
from openworld_moments_contracts.validate import _canonical


def _cases(kind: str) -> list[tuple[str, Path]]:
    return sorted((path.parent.parent.name, path) for path in FIXTURES.glob(f"*/{kind}/*.json"))


def _read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


@pytest.mark.parametrize(("contract", "path"), _cases("valid"), ids=lambda v: getattr(v, "stem", v))
def test_valid_fixture_parses_to_canonical_input(contract: str, path: Path) -> None:
    raw = _read(path)
    assert normalize(load(contract, raw)) == _canonical(raw)


@pytest.mark.parametrize(
    ("contract", "path"), _cases("invalid"), ids=lambda v: getattr(v, "stem", v)
)
def test_invalid_fixture_is_rejected_for_the_stated_reason(contract: str, path: Path) -> None:
    case = _read(path)
    with pytest.raises(ContractError) as caught:
        load(contract, case["document"])
    err = caught.value
    expect = case["expect"]

    if expect == "version":
        assert isinstance(err, ContractVersionError)
    else:
        assert not isinstance(err, ContractVersionError)

    if "message_contains" in case:
        assert any(case["message_contains"] in issue for issue in err.issues), err.issues
    if "path" in case:
        paths = [issue.split(": ", 1)[0] for issue in err.issues]
        assert any(p.startswith(case["path"]) for p in paths), paths

    if expect == "semantic":
        # Semantic failures must only happen after the schema accepted the document.
        assert all(":" in issue for issue in err.issues)


def test_every_contract_has_valid_and_invalid_fixtures() -> None:
    for contract in CONTRACTS:
        assert list((FIXTURES / contract / "valid").glob("*.json")), contract
        assert list((FIXTURES / contract / "invalid").glob("*.json")), contract
