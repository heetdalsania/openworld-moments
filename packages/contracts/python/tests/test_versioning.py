# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re

import pytest
from conftest import CONTRACTS_ROOT

from openworld_moments_contracts import SUPPORTED_VERSION, ContractVersionError, check_version


@pytest.mark.parametrize(
    "version",
    [
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "1.7",
        "1.8",
        "1.9",
        "1.10",
        "1.11",
        "1.12",
        "1.13",
        "1.14",
        "1.15",
        "1.16",
        "1.17",
        "1.18",
        "1.19",
        "1.20",
        "1.21",
    ],
)
def test_supported_versions_pass(version: str) -> None:
    assert str(check_version("event", {"schema_version": version})) == version


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ({}, "missing"),
        ([], "missing"),
        ({"schema_version": 1}, "malformed"),
        ({"schema_version": "1"}, "malformed"),
        ({"schema_version": "01.0"}, "malformed"),
        ({"schema_version": "0.9"}, "older than the supported 1.x"),
        ({"schema_version": "1.22"}, "reads up to 1.21"),
        ({"schema_version": "2.0"}, "newer OpenWorld Moments"),
    ],
)
def test_unsupported_versions_explain_themselves(document: object, fragment: str) -> None:
    with pytest.raises(ContractVersionError, match=re.escape(fragment)):
        check_version("event", document)


def test_typescript_supported_version_matches() -> None:
    source = (CONTRACTS_ROOT / "src" / "versioning.ts").read_text("utf-8")
    match = re.search(r"SUPPORTED_VERSION = \{ major: (\d+), minor: (\d+) \}", source)
    assert match, "SUPPORTED_VERSION not found in src/versioning.ts"
    assert (int(match.group(1)), int(match.group(2))) == (
        SUPPORTED_VERSION.major,
        SUPPORTED_VERSION.minor,
    )
