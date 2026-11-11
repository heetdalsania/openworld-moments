# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remove build-machine paths from text that ships with the package (M30).

Build logs and version strings name the CI workspace and the runner's temp folder.
Release text artifacts replace them with placeholders, so they carry no absolute
paths while keeping every flag readable.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

ROOT = Path(__file__).resolve().parents[2]
_HOME = re.compile(r"(?:[A-Za-z]:)?[\\/]Users[\\/][^\\/\s\"']+|/home/[^/\s\"']+")


def _forms(path: PurePath) -> list[str]:
    native = str(path)
    posix = path.as_posix()
    forms = {native, posix}
    if len(posix) > 2 and posix[1] == ":":  # D:/a/x -> /d/a/x (MSYS form)
        forms.add("/" + posix[0].lower() + posix[2:])
    return sorted(forms, key=len, reverse=True)


def redact(text: str, root: PurePath = ROOT) -> str:
    for form in _forms(root):
        text = text.replace(form, "<build-root>")
    return _HOME.sub("<user-home>", text)
