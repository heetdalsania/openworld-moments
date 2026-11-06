# SPDX-License-Identifier: AGPL-3.0-or-later
"""The import pipeline end to end on synthetic media (M05).

Covers the brief's required validation: reference source hash/mtime, interrupted
copy recovery, symlink/path traversal, mixed-validity batches, and a simulated
full disk.
"""

from __future__ import annotations

import errno
import hashlib
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, BinaryIO

import pytest
from openworld_moments_contracts import load

from openworld_moments.ingest import files as files_module
from openworld_moments.ingest.files import ImportCancelled
from openworld_moments.ingest.importer import Importer, ImportFailure
from openworld_moments.ingest.library import LibraryPaths
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import AssetImportRepository, AssetRepository, Database


class FixedTools(MediaTools):
    def __init__(self, ffprobe: ToolInfo) -> None:
        super().__init__()
        self._fixed = ffprobe

    def tool(self, name: str) -> ToolInfo:
        return self._fixed if name == "ffprobe" else super().tool(name)  # type: ignore[arg-type]


def _fingerprint(path: Path) -> tuple[str, int, int]:
    info = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns


def _tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


class Harness:
    def __init__(self, tmp_path: Path, ffprobe: ToolInfo, **options: Any) -> None:
        self.database = Database.open(tmp_path / "library" / "database.sqlite3")
        self.library = LibraryPaths.for_database(self.database.path)
        self.importer = Importer(self.database, FixedTools(ffprobe), **options)
        self.cancel = threading.Event()
        self.progress: list[tuple[int, int, str]] = []
        self._reader: sqlite3.Connection | None = None

    def run(
        self, *paths: Path, mode: str = "reference", recursive: bool = True, job: str | None = None
    ) -> dict[str, Any]:
        params = {
            "paths": [str(p) for p in paths],
            "mode": mode,
            "recursive": recursive,
            "source_kind": "xbox",
        }
        result = self.importer.run_import(
            params,
            job_id=job or "job_01JCBQ00000000000000000099",
            cancel=self.cancel,
            progress=lambda d, t, m: self.progress.append((d, t, m)),
        )
        load("import", result)  # contract-valid, including totals consistency
        return result

    def assets(self) -> AssetRepository:
        # One reader connection, closed by the fixture (Windows cannot delete open files).
        # Autocommit statements always see the latest committed import.
        if self._reader is None:
            self._reader = self.database.connect()
        return AssetRepository(self._reader)

    def asset_count(self) -> int:
        return int(self.assets().conn.execute("SELECT count(*) FROM media_assets").fetchone()[0])

    def provenance_count(self) -> int:
        return AssetImportRepository(self.assets().conn).count()

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None


@pytest.fixture
def harness(tmp_path: Path, ffprobe: ToolInfo) -> Iterator[Harness]:
    with closing(Harness(tmp_path, ffprobe)) as h:
        yield h


@pytest.fixture
def clip(media_dir: Path, tmp_path: Path) -> Path:
    target = tmp_path / "source" / "Capture ✓ 日本語.mp4"
    target.parent.mkdir()
    shutil.copyfile(media_dir / "h264_aac.mp4", target)
    return target


# -- reference mode -------------------------------------------------------------------


def test_reference_import_never_writes_the_source(harness: Harness, clip: Path) -> None:
    before = _fingerprint(clip)
    result = harness.run(clip)
    assert result["totals"]["imported"] == 1
    assert _fingerprint(clip) == before, "source bytes or mtime changed"
    assert sorted(p.name for p in clip.parent.iterdir()) == [clip.name], "wrote beside the source"
    assert _tree(harness.library.managed) == [], "reference mode must not copy"

    asset_id = result["items"][0]["asset_id"]
    repo = harness.assets()
    asset = repo.get(asset_id)
    location = repo.location(asset_id)
    assert asset.sha256 == before[0]
    assert asset.size_bytes == before[1]
    assert asset.import_mode == "reference" and asset.source_kind == "xbox"
    assert asset.original_name == clip.name
    assert asset.video is not None and asset.video.codec == "h264"
    assert asset.capture_time is not None
    assert location.original_path == str(clip) and location.managed_path is None
    assert harness.progress[-1][:2] == (1, 1)


def test_repeating_an_import_creates_no_new_rows(harness: Harness, clip: Path) -> None:
    first = harness.run(clip)
    second = harness.run(clip)
    third = harness.run(clip.parent)  # same file again, found through its folder
    asset_id = first["items"][0]["asset_id"]
    assert second["items"][0] == {"source": 0, "outcome": "existing", "asset_id": asset_id}
    assert third["items"][0]["outcome"] == "existing"
    assert harness.asset_count() == 1
    assert harness.provenance_count() == 1  # one (asset, path) pair, refreshed


def test_renamed_copy_is_the_same_asset(harness: Harness, clip: Path) -> None:
    copy = clip.with_name("renamed copy.mp4")
    shutil.copyfile(clip, copy)
    harness.run(clip)
    result = harness.run(copy)
    assert result["items"][0]["outcome"] == "existing"
    assert harness.asset_count() == 1
    assert harness.provenance_count() == 2  # both locations are recorded as provenance


# -- managed mode ---------------------------------------------------------------------


def test_managed_import_copies_into_content_addressed_storage(harness: Harness, clip: Path) -> None:
    sha, size, _ = before = _fingerprint(clip)
    result = harness.run(clip, mode="managed")
    assert _fingerprint(clip) == before
    expected = f"{sha[:2]}/{sha[2:4]}/{sha}.mp4"
    assert _tree(harness.library.managed) == [str(Path(expected))]
    stored = harness.library.managed / expected
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == sha
    assert _tree(harness.library.import_staging) == []

    location = harness.assets().location(result["items"][0]["asset_id"])
    assert location.managed_path == f"managed-media/{expected}"
    assert location.import_mode == "managed" and location.size_bytes == size

    again = harness.run(clip, mode="managed")
    assert again["items"][0]["outcome"] == "existing"
    assert _tree(harness.library.managed) == [str(Path(expected))]
    assert _tree(harness.library.import_staging) == []


@pytest.mark.parametrize(
    "name",
    ["clip with spaces.mp4", "-leading-dash.mp4", "100% done & more.mp4", "é" * 40 + ".mkv"],
)
def test_awkward_names_in_both_modes(
    media_dir: Path, tmp_path: Path, ffprobe: ToolInfo, name: str
) -> None:
    folder = tmp_path / "folder with spaces ünïcødé"
    folder.mkdir()
    shutil.copyfile(media_dir / "h264_aac.mp4", folder / name)
    for mode in ("reference", "managed"):
        with closing(Harness(tmp_path / mode, ffprobe)) as harness:
            result = harness.run(folder, mode=mode)
        assert result["items"][0]["relative_path"] == name
        assert result["items"][0]["outcome"] == "imported"


# -- batches --------------------------------------------------------------------------


def test_mixed_validity_batch_reports_every_file(
    media_dir: Path, tmp_path: Path, harness: Harness
) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    for name in ("h264_aac.mp4", "no_audio.mp4", "truncated.mp4", "garbage.mp4", "empty.mp4"):
        shutil.copyfile(media_dir / name, folder / name)
    shutil.copyfile(media_dir / "still.png", folder / "still.png")
    shutil.copyfile(media_dir / "audio_only.m4a", folder / "audio.mp4")  # lies about its type
    (folder / "notes.txt").write_text("hello", "utf-8")

    result = harness.run(folder, mode="managed")
    outcomes = {
        i["relative_path"]: (i["outcome"], i.get("error", {}).get("code")) for i in result["items"]
    }
    assert outcomes == {
        "audio.mp4": ("failed", "media.no_video_stream"),
        "empty.mp4": ("failed", "media.empty_file"),
        "garbage.mp4": ("failed", "media.damaged"),
        "h264_aac.mp4": ("imported", None),
        "no_audio.mp4": ("imported", None),
        "notes.txt": ("skipped", "import.not_media_extension"),
        "still.png": ("skipped", "import.not_media_extension"),
        "truncated.mp4": ("failed", "media.damaged"),
    }
    assert result["totals"] == {
        "files": 8,
        "imported": 2,
        "existing": 0,
        "relinked": 0,
        "skipped": 2,
        "failed": 4,
    }
    # Unsupported media never reaches canonical storage or the database.
    assert len(_tree(harness.library.managed)) == 2
    assert harness.asset_count() == 2
    for item in result["items"]:
        assert str(folder) not in str(item.get("error", {}))


def test_batch_where_everything_fails_fails_the_job_with_the_report(
    media_dir: Path, tmp_path: Path, harness: Harness
) -> None:
    bad = tmp_path / "bad.mp4"
    shutil.copyfile(media_dir / "garbage.mp4", bad)
    with pytest.raises(ImportFailure) as single:
        harness.run(bad)
    assert single.value.code == "media.damaged"  # one file: its own error
    assert single.value.result is not None and single.value.result["totals"]["failed"] == 1

    empty = tmp_path / "empty.mp4"
    shutil.copyfile(media_dir / "empty.mp4", empty)
    with pytest.raises(ImportFailure) as several:
        harness.run(bad, empty)
    assert several.value.code == "import.all_failed"
    assert several.value.details == {"failed": 2}


def test_folder_without_media_fails_clearly(tmp_path: Path, harness: Harness) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("x", "utf-8")
    with pytest.raises(ImportFailure) as caught:
        harness.run(tmp_path / "docs")
    assert caught.value.code == "import.no_media_found"
    assert caught.value.result is not None and caught.value.result["totals"]["skipped"] == 1


def test_symlink_escape_is_not_imported(media_dir: Path, tmp_path: Path, harness: Harness) -> None:
    outside = tmp_path / "private" / "secret.mp4"
    outside.parent.mkdir()
    shutil.copyfile(media_dir / "h264_aac.mp4", outside)
    root = tmp_path / "selected"
    root.mkdir()
    shutil.copyfile(media_dir / "no_audio.mp4", root / "mine.mp4")
    try:
        (root / "escape.mp4").symlink_to(outside)
        (root / "linked-dir").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra privileges on this Windows runner")
    result = harness.run(root, mode="managed")
    outcomes = {i["relative_path"]: i["outcome"] for i in result["items"]}
    assert outcomes == {"escape.mp4": "skipped", "linked-dir": "skipped", "mine.mp4": "imported"}
    assert harness.asset_count() == 1
    secret_sha = _fingerprint(outside)[0]
    assert not any(secret_sha in p for p in _tree(harness.library.managed))


def test_file_size_limit(tmp_path: Path, ffprobe: ToolInfo, clip: Path) -> None:
    with (
        closing(Harness(tmp_path, ffprobe, max_file_bytes=1024)) as harness,
        pytest.raises(ImportFailure) as caught,
    ):
        harness.run(clip)
    assert caught.value.code == "import.file_too_large"


def test_missing_ffprobe_fails_the_whole_job(tmp_path: Path, clip: Path) -> None:
    missing = ToolInfo("ffprobe", (), "path", "missing", None, problem="not found")
    with closing(Harness(tmp_path, missing)) as harness, pytest.raises(ImportFailure) as caught:
        harness.run(clip)
    assert caught.value.code == "tool.ffprobe_missing" and caught.value.retryable


# -- interruption, cancellation, and write failures ----------------------------------


def _hook_writes(monkeypatch: pytest.MonkeyPatch, hook: Callable[[int], None]) -> None:
    """Small chunks, and ``hook(n)`` before the n-th staging write (1-based)."""
    real = files_module.write_chunk
    calls = [0]

    def write(handle: BinaryIO, chunk: bytes) -> None:
        calls[0] += 1
        hook(calls[0])
        real(handle, chunk)

    monkeypatch.setattr(files_module, "CHUNK_BYTES", 4096)
    monkeypatch.setattr(files_module, "write_chunk", write)


def test_simulated_full_disk_leaves_no_partial_library_file(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, clip: Path
) -> None:
    def full(n: int) -> None:
        if n == 3:
            raise OSError(errno.ENOSPC, "No space left on device")

    _hook_writes(monkeypatch, full)
    with pytest.raises(ImportFailure) as caught:
        harness.run(clip, mode="managed")
    assert caught.value.code == "import.disk_full" and caught.value.retryable
    assert _tree(harness.library.managed) == []
    assert _tree(harness.library.import_staging) == []
    assert harness.asset_count() == 0


def test_low_free_space_is_refused_before_copying(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, clip: Path
) -> None:
    usage = shutil.disk_usage(clip.parent)._replace(free=10)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage)
    with pytest.raises(ImportFailure) as caught:
        harness.run(clip, mode="managed")
    assert caught.value.code == "import.disk_full"
    assert _tree(harness.library.import_staging) == []


def test_cancel_during_copy_cleans_up(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, clip: Path
) -> None:
    _hook_writes(monkeypatch, lambda n: harness.cancel.set() if n == 2 else None)
    with pytest.raises(ImportCancelled):
        harness.run(clip, mode="managed")
    assert _tree(harness.library.managed) == []
    assert _tree(harness.library.import_staging) == []
    assert harness.asset_count() == 0


def test_crash_leftovers_are_swept_and_the_retry_succeeds(harness: Harness, clip: Path) -> None:
    # What a hard crash mid-copy leaves: a partial file in the job's staging folder.
    job = "job_01JCBQ00000000000000000042"
    leftover = harness.library.job_staging(job) / "import-abc123.part"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(clip.read_bytes()[:1000])
    assert _tree(harness.library.managed) == []  # never visible as a library file

    harness.library.clean_import_staging()  # worker start
    assert not leftover.exists()
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial")
    result = harness.run(clip, mode="managed", job=job)  # the requeued job
    assert result["items"][0]["outcome"] == "imported"
    assert not leftover.exists()
    (stored,) = harness.library.managed.rglob("*.mp4")
    assert stored.read_bytes() == clip.read_bytes()


def test_crash_after_promotion_is_adopted_on_retry(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, clip: Path
) -> None:
    def crash(*_: Any, **__: Any) -> None:
        raise SystemExit("simulated crash between promotion and commit")

    monkeypatch.setattr(AssetRepository, "add", crash)
    with pytest.raises(SystemExit):
        harness.run(clip, mode="managed")
    assert harness.asset_count() == 0
    assert len(_tree(harness.library.managed)) == 1  # complete, but unreferenced
    monkeypatch.undo()

    result = harness.run(clip, mode="managed")
    assert result["items"][0]["outcome"] == "imported"
    assert len(_tree(harness.library.managed)) == 1


def test_source_still_being_written_is_retryable(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, clip: Path
) -> None:
    def grow(n: int) -> None:
        if n == 1:
            with clip.open("ab") as handle:
                handle.write(b"more bytes from a slow sync")

    _hook_writes(monkeypatch, grow)
    with pytest.raises(ImportFailure) as caught:
        harness.run(clip, mode="managed")
    assert caught.value.code == "import.source_changed" and caught.value.retryable
    assert _tree(harness.library.managed) == []


# -- missing sources and relink -------------------------------------------------------


def _check(harness: Harness) -> dict[str, Any]:
    return harness.importer.check_sources(cancel=harness.cancel, progress=lambda *_: None)


def _relink(harness: Harness, asset_id: str, path: Path) -> dict[str, Any]:
    return harness.importer.relink(
        {"asset_id": asset_id, "path": str(path)},
        job_id="job_01JCBQ00000000000000000077",
        cancel=harness.cancel,
    )


def test_moved_reference_is_detected_and_relinked(harness: Harness, clip: Path) -> None:
    asset_id = harness.run(clip)["items"][0]["asset_id"]
    moved = clip.parent / "moved" / "elsewhere.mp4"
    moved.parent.mkdir()
    clip.rename(moved)

    report = _check(harness)
    assert report == {
        "checked": 1,
        "missing": 1,
        "newly_missing": 1,
        "restored": 0,
        "missing_asset_ids": [asset_id],
    }
    assert harness.assets().get(asset_id).missing_at is not None
    assert [a.id for a in harness.assets().query(missing=True)] == [asset_id]
    assert _check(harness)["newly_missing"] == 0  # already known

    assert _relink(harness, asset_id, moved) == {"asset_id": asset_id, "verified_by": "sha256"}
    repo = harness.assets()
    assert repo.get(asset_id).missing_at is None
    assert repo.location(asset_id).original_path == str(moved)
    assert harness.provenance_count() == 2
    assert _check(harness)["missing"] == 0


def test_relink_refuses_a_different_file(
    media_dir: Path, harness: Harness, clip: Path, tmp_path: Path
) -> None:
    asset_id = harness.run(clip)["items"][0]["asset_id"]
    other = tmp_path / "other.mp4"
    shutil.copyfile(media_dir / "no_audio.mp4", other)
    with pytest.raises(ImportFailure) as size_differs:
        _relink(harness, asset_id, other)
    assert size_differs.value.code == "relink.identity_mismatch"

    tampered = tmp_path / "tampered.mp4"
    data = bytearray(clip.read_bytes())
    data[-1] ^= 0xFF
    tampered.write_bytes(bytes(data))
    with pytest.raises(ImportFailure) as content_differs:
        _relink(harness, asset_id, tampered)
    assert content_differs.value.code == "relink.identity_mismatch"
    assert harness.assets().location(asset_id).original_path == str(clip)


def test_reimporting_a_moved_file_relinks_it(harness: Harness, clip: Path) -> None:
    asset_id = harness.run(clip)["items"][0]["asset_id"]
    moved = clip.with_name("moved.mp4")
    clip.rename(moved)
    _check(harness)
    result = harness.run(moved)
    assert result["items"][0] == {"source": 0, "outcome": "relinked", "asset_id": asset_id}
    assert harness.assets().location(asset_id).original_path == str(moved)
    assert harness.asset_count() == 1


def test_replaced_reference_counts_as_missing(harness: Harness, clip: Path) -> None:
    asset_id = harness.run(clip)["items"][0]["asset_id"]
    clip.write_bytes(clip.read_bytes() + b"edited")
    assert _check(harness)["missing_asset_ids"] == [asset_id]


def test_missing_managed_copy_is_restored_by_a_managed_reimport(
    harness: Harness, clip: Path
) -> None:
    asset_id = harness.run(clip, mode="managed")["items"][0]["asset_id"]
    (stored,) = harness.library.managed.rglob("*.mp4")
    stored.unlink()
    assert _check(harness)["newly_missing"] == 1
    with pytest.raises(ImportFailure) as caught:
        _relink(harness, asset_id, clip)
    assert caught.value.code == "relink.not_referenced"

    result = harness.run(clip, mode="managed")
    assert result["items"][0]["outcome"] == "relinked"
    assert stored.read_bytes() == clip.read_bytes()
    assert _check(harness) == {
        "checked": 1,
        "missing": 0,
        "newly_missing": 0,
        "restored": 0,
        "missing_asset_ids": [],
    }


def test_returning_file_is_restored_by_the_check(harness: Harness, clip: Path) -> None:
    harness.run(clip)
    hidden = clip.with_name("hidden.bin")
    clip.rename(hidden)
    _check(harness)
    hidden.rename(clip)
    report = _check(harness)
    assert (report["missing"], report["restored"]) == (0, 1)
