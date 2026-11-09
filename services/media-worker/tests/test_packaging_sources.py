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


def test_candidate_checksums_survive_reassembly_without_stale_media(tmp_path: Path) -> None:
    import hashlib
    import json

    spec = importlib.util.spec_from_file_location(
        "packaging_artifacts", Path(__file__).resolve().parents[3] / "scripts/windows/artifacts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__.update(
        ROOT=tmp_path, OUT=tmp_path / "output/packaging", RUNTIME=tmp_path / "runtime"
    )
    out, runtime = module.OUT, module.RUNTIME
    (out / "sources").mkdir(parents=True)
    (out / "sources/source.tar.xz").write_bytes(b"source archive fixture")
    (out / "media").mkdir()
    for name in ("compiler.txt", "build-packages.txt", "config.log"):
        (out / "media" / name).write_text("compiler fixture")
    (runtime / "notices").mkdir(parents=True)
    (runtime / "notices/LICENSE").write_text("license fixture")
    manifest = json.dumps({"files": {"worker": "a" * 64}})
    (runtime / "inventory.json").write_text(manifest)
    (out / "repro-first.json").write_text(manifest)
    for name in (
        "THIRD_PARTY_NOTICES.txt",
        "reproducibility.json",
        "native-import-render.json",
        "native-repair.json",
        "native-upgrade.json",
    ):
        (out / name).write_text("report fixture")
    scripts = tmp_path / "scripts/windows"
    scripts.mkdir(parents=True)
    for name in ("build-media.sh", "freeze-worker.py", "sources.json", "python-notices.json"):
        (scripts / name).write_text("build input fixture")
    installers = tmp_path / "target/x86_64-pc-windows-msvc/release/bundle/nsis"
    installers.mkdir(parents=True)
    (installers / "Moments_0.1.0-alpha.29_x64-setup.exe").write_bytes(b"installer fixture")
    module.main()
    release = out / "release"
    (release / "stale-media.mp4").write_bytes(b"never include stale generated media")
    module.main()
    assert not (release / "stale-media.mp4").exists()
    listed = []
    for line in (release / "checksums.txt").read_text().splitlines():
        expected, name = line.split("  ", 1)
        listed.append(name)
        assert hashlib.sha256((release / name).read_bytes()).hexdigest() == expected
    assert "checksums.txt" not in listed
    assert "runtime-notices.zip" in listed


def test_stdlib_archive_normalization_preserves_code_and_detects_changes(tmp_path: Path) -> None:
    import hashlib
    import zipfile

    spec = importlib.util.spec_from_file_location(
        "packaging_freeze", Path(__file__).resolve().parents[3] / "scripts/windows/freeze-worker.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archives = [tmp_path / f"stdlib-{i}.zip" for i in range(3)]
    payload = {"a.pyc": b"first module", "z.pyc": b"last module"}
    for i, archive in enumerate(archives):
        with zipfile.ZipFile(archive, "w") as target:
            for name in sorted(payload, reverse=i == 0):
                info = zipfile.ZipInfo(name, (2020 + i, 1, 1, 0, 0, 0))
                target.writestr(info, payload[name] + (b"changed" if i == 2 else b""))
        module.canonicalize_stdlib_zip(archive)
    assert archives[0].read_bytes() == archives[1].read_bytes()
    with zipfile.ZipFile(archives[0]) as result:
        assert {name: result.read(name) for name in result.namelist()} == payload
    assert (
        hashlib.sha256(archives[2].read_bytes()).digest()
        != hashlib.sha256(archives[0].read_bytes()).digest()
    )
