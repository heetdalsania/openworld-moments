# SPDX-License-Identifier: Apache-2.0
"""schema_version policy. See packages/contracts/VERSIONING.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from openworld_moments_contracts.errors import ContractVersionError

_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


#: Version every versioned contract is currently written at. Keep in sync with
#: SUPPORTED_VERSION in src/versioning.ts (a test enforces this).
SUPPORTED_VERSION = SchemaVersion(1, 7)


def check_version(contract: str, document: Any) -> SchemaVersion:
    """Return the document's version, or raise with an actionable message.

    Readers accept the supported major version at any minor version up to the
    supported one. Older majors need a migration; newer versions need a newer app.
    """
    if not isinstance(document, dict) or "schema_version" not in document:
        raise ContractVersionError(contract, ["missing required 'schema_version'"])
    raw = document["schema_version"]
    match = _VERSION.match(raw) if isinstance(raw, str) else None
    if match is None:
        raise ContractVersionError(
            contract, [f"malformed schema_version {raw!r}; expected 'MAJOR.MINOR' such as '1.0'"]
        )
    found = SchemaVersion(int(match.group(1)), int(match.group(2)))
    supported = SUPPORTED_VERSION
    if found.major < supported.major:
        raise ContractVersionError(
            contract,
            [
                f"schema_version {found} is older than the supported {supported.major}.x; "
                "migrate the file with the release that introduced the new format before "
                "opening it"
            ],
        )
    if found.major > supported.major or found.minor > supported.minor:
        raise ContractVersionError(
            contract,
            [
                f"schema_version {found} was written by a newer OpenWorld Moments; this "
                f"version reads up to {supported}. Update the app to open it"
            ],
        )
    return found
