# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


def extraction(archive: Path, target: Path) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts/windows/prepare-sources.py"
    spec = importlib.util.spec_from_file_location("packaging_sources", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.extract(archive, target)


def test_sources_extract_without_the_archive_prefix(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as stream:
        item = tarfile.TarInfo("source-revision/LICENSE")
        item.size = 7
        stream.addfile(item, io.BytesIO(b"license"))
    extraction(archive, tmp_path / "extracted")
    assert (tmp_path / "extracted/LICENSE").read_bytes() == b"license"


@pytest.mark.parametrize(
    "name,link", [("../../escape", False), ("/absolute", False), ("source/link", True)]
)
def test_archive_paths_and_links_are_refused(tmp_path: Path, name: str, link: bool) -> None:
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as stream:
        item = tarfile.TarInfo(name)
        if link:
            item.type = tarfile.SYMTYPE
            item.linkname = "../../escape"
        stream.addfile(item)
    with pytest.raises(ValueError, match="Unsafe source archive"):
        extraction(archive, tmp_path / "extracted")
    assert not (tmp_path / "escape").exists()
