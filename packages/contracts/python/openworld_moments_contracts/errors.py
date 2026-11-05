# SPDX-License-Identifier: Apache-2.0
"""Exceptions raised when a document does not satisfy its contract."""

from __future__ import annotations


class ContractError(ValueError):
    """A document failed version, schema, or semantic validation."""

    def __init__(self, contract: str, issues: list[str]) -> None:
        self.contract = contract
        self.issues = issues
        joined = "; ".join(issues)
        super().__init__(f"{contract}: {joined}")


class ContractVersionError(ContractError):
    """The document's schema_version is missing, malformed, or unsupported."""
