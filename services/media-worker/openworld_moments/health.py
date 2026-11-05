# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worker health reporting."""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

from openworld_moments import __version__

SUPPORTED_PYTHON = (3, 12)


@dataclass(frozen=True, slots=True)
class Health:
    """Snapshot of the worker's readiness."""

    status: str
    version: str
    python: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def health(python_version: tuple[int, int] | None = None) -> Health:
    """Report whether this worker can run on the current interpreter.

    ``python_version`` overrides the detected interpreter, for tests.
    """
    major, minor = python_version or (
        int(platform.python_version_tuple()[0]),
        int(platform.python_version_tuple()[1]),
    )
    status = "ok" if (major, minor) == SUPPORTED_PYTHON else "unsupported-python"
    return Health(status=status, version=__version__, python=f"{major}.{minor}")
