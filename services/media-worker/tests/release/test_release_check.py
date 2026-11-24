# SPDX-License-Identifier: AGPL-3.0-or-later
"""M32 release tooling: one packaged version, verified release sets, CI summaries."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "scripts" / "windows"))

import release_check  # noqa: E402
import release_version  # noqa: E402

VERSION = "0.1.0-alpha.32"
INSTALLER = f"OpenWorld-Moments_{VERSION}_Windows_x64-setup.exe"


# -- the single packaged version ------------------------------------------------------


def test_repository_packaged_version_is_the_public_alpha() -> None:
    assert release_version.packaged_version() == VERSION
    assert release_version.installer_name(VERSION) == INSTALLER
    assert release_version.upgrade_test_version(VERSION) == f"{VERSION}.1"


@pytest.mark.parametrize(
    "value",
    ["0.1.0", "0.1.0-alpha", "0.1.0-alpha.01", "0.1.0-beta.1", "v0.1.0-alpha.1", 32, None],
)
def test_packaged_version_refuses_non_alpha_values(tmp_path: Path, value: object) -> None:
    config = tmp_path / release_version.CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"version": value}))
    with pytest.raises(ValueError, match=r"0\.1\.0-alpha\.N"):
        release_version.packaged_version(tmp_path)


def test_windows_packaging_scripts_do_not_repeat_the_version() -> None:
    """A release bump must not leave a stale hard-coded version behind (the M29 pattern)."""
    hard_coded = re.compile(r"\d+\.\d+\.\d+-alpha\.\d+")
    scripts = [*sorted((ROOT / "scripts/windows").iterdir()), ROOT / ".github/workflows/ci.yml"]
    offenders = [
        path.name
        for path in scripts
        if path.suffix in {".py", ".ps1", ".sh", ".yml"}
        and hard_coded.search(path.read_text("utf-8"))
    ]
    assert offenders == []


# -- verify-artifacts -----------------------------------------------------------------


def write_release(root: Path, version: str = VERSION) -> Path:
    root.mkdir()
    (root / release_version.installer_name(version)).write_bytes(b"installer fixture")
    for name in release_check.REQUIRED:
        (root / name).write_text("fixture")
    application = {"version": version}
    (root / "runtime-inventory.json").write_text(json.dumps({"application": version}))
    sbom = {"bomFormat": "CycloneDX", "metadata": {"component": {"version": version}}}
    (root / "sbom.cdx.json").write_text(json.dumps(sbom))
    for mode in ("import-render", "repair"):
        (root / f"native-{mode}.json").write_text(json.dumps({"application": application}))
    upgrade = {"application": {"version": f"{version}.1"}}
    # PowerShell's UTF-8 writes may carry a BOM; reports must still parse.
    (root / "native-upgrade.json").write_text("﻿" + json.dumps(upgrade), encoding="utf-8")
    (root / "reproducibility.json").write_text(json.dumps({"frozen_payload_identical": True}))
    rewrite_checksums(root)
    return root


def rewrite_checksums(root: Path) -> None:
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(root.iterdir())
        if p.name != "checksums.txt"
    ]
    (root / "checksums.txt").write_text("\n".join(lines) + "\n")


def failed(result: dict[str, Any]) -> set[str]:
    return {c["id"] for c in result["checks"] if not c["ok"]}


def test_complete_release_set_passes_and_lists_every_file(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    result = release_check.verify_artifacts(root, VERSION)
    assert result["ok"], failed(result)
    names = [f["name"] for f in result["files"]]
    assert INSTALLER in names and "checksums.txt" in names
    table = release_check.hash_table(result)
    assert f"| `{INSTALLER}` | 17 |" in table


def test_tampered_file_is_reported(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    (root / INSTALLER).write_bytes(b"installer fixturE")
    assert failed(release_check.verify_artifacts(root, VERSION)) == {"checksums:match"}


def test_unlisted_and_missing_files_are_reported(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    (root / "extra.txt").write_text("not in checksums")
    (root / "VERIFY.md").unlink()
    assert failed(release_check.verify_artifacts(root, VERSION)) == {
        "present:VERIFY.md",
        "checksums:every-file-listed",
        "checksums:every-listed-file-present",
    }


def test_upgrade_test_installer_and_wrong_version_are_refused(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    (root / f"OpenWorld Moments_{VERSION}.1_x64-setup.exe").write_bytes(b"test only")
    rewrite_checksums(root)
    assert failed(release_check.verify_artifacts(root, VERSION)) == {"installer:exactly-one"}
    other = write_release(tmp_path / "other", "0.1.0-alpha.31")
    assert "installer:exactly-one" in failed(release_check.verify_artifacts(other, VERSION))


def test_every_versioned_report_must_agree(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    (root / "runtime-inventory.json").write_text(json.dumps({"application": "0.1.0-alpha.29"}))
    (root / "native-upgrade.json").write_text(json.dumps({"application": {"version": VERSION}}))
    (root / "sbom.cdx.json").write_text("{not json")
    (root / "reproducibility.json").write_text(json.dumps({"frozen_payload_identical": False}))
    rewrite_checksums(root)
    assert failed(release_check.verify_artifacts(root, VERSION)) == {
        "version:runtime-inventory.json",
        "version:native-upgrade.json",
        "version:sbom.cdx.json",
        "sbom:format",
        "reproducibility:frozen-payload",
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "abc  file.txt\n",
        f"{'a' * 64} file.txt\n",  # one space
        f"{'a' * 64}  ../escape\n",
        f"{'a' * 64}  dir\\file\n",
        f"{'a' * 64}  ..\n",
        f"{'a' * 64}  same\n{'b' * 64}  same\n",
    ],
)
def test_malformed_checksum_files_are_refused(text: str) -> None:
    with pytest.raises(ValueError, match=r"checksums\.txt"):
        release_check.parse_checksums(text)


def test_links_and_folders_inside_the_release_are_refused(tmp_path: Path) -> None:
    root = write_release(tmp_path / "release")
    (root / "nested").mkdir()
    # Windows without symlink privilege: the folder alone must still fail the check.
    with contextlib.suppress(OSError):
        (root / "linked.txt").symlink_to(root / "VERIFY.md")
    result = release_check.verify_artifacts(root, VERSION)
    assert "layout:plain-files" in failed(result)
    with pytest.raises(ValueError, match="real directory"):
        release_check.verify_artifacts(tmp_path / "missing", VERSION)
    with pytest.raises(ValueError, match=r"0\.1\.0-alpha\.N"):
        release_check.verify_artifacts(root, "0.1.0")


def test_cli_writes_reports_outside_the_release_and_sets_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_release(tmp_path / "release")
    report, table = tmp_path / "verification.json", tmp_path / "hashes.md"
    args = ["verify-artifacts", str(root), "--version", VERSION]
    assert release_check.main([*args, "--report", str(report), "--markdown", str(table)]) == 0
    assert json.loads(report.read_text())["ok"] is True
    assert INSTALLER in table.read_text()
    (root / "SECURITY.md").write_text("changed")
    assert release_check.main([*args, "--report", str(report)]) == 1
    assert "FAILED checksums:match" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        release_check.main([*args, "--report", str(root / "inside.json")])
    assert not (root / "inside.json").exists()


# -- ci-summary -----------------------------------------------------------------------


def run(*jobs: tuple[str, str | None], status: str = "completed") -> dict[str, Any]:
    return {
        "databaseId": 1,
        "headSha": "c" * 40,
        "event": "push",
        "status": status,
        "conclusion": "success",
        "url": "https://github.com/example/repo/actions/runs/1",
        "jobs": [{"name": n, "conclusion": c} for n, c in jobs],
    }


def test_ci_summary_requires_every_job_to_succeed() -> None:
    ok = release_check.ci_summary(run(("Rust (windows)", "success"), ("TypeScript", "success")))
    assert ok["ok"] and [j["name"] for j in ok["jobs"]] == ["Rust (windows)", "TypeScript"]
    assert not release_check.ci_summary(run(("A", "success"), ("B", "failure")))["ok"]
    assert not release_check.ci_summary(run(("A", "cancelled")))["ok"]
    assert not release_check.ci_summary(run(("A", None), status="in_progress"))["ok"]


def test_ci_summary_allows_only_named_skips(tmp_path: Path) -> None:
    jobs = run(("A", "success"), ("DCO sign-off", "skipped"))
    assert not release_check.ci_summary(jobs)["ok"]
    assert release_check.ci_summary(jobs, ["DCO sign-off"])["ok"]
    path = tmp_path / "run.json"
    path.write_text(json.dumps(jobs))
    assert release_check.main(["ci-summary", str(path), "--allow-skipped", "DCO sign-off"]) == 0
    with pytest.raises(ValueError, match="no jobs"):
        release_check.ci_summary({"status": "completed"})


# -- post-release triage labels -------------------------------------------------------


def test_triage_labels_cover_every_issue_template() -> None:
    labels = json.loads((ROOT / ".github/labels.json").read_text("utf-8"))
    names = [label["name"] for label in labels]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[0-9a-f]{6}", label["color"]) for label in labels)
    assert all(0 < len(label["description"]) <= 100 for label in labels)
    assert {"release-blocker", "data-loss", "installer", f"alpha:{VERSION}"} <= set(names)
    used = set()
    for template in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        match = re.search(r"^labels: \[(.*)\]$", template.read_text("utf-8"), re.MULTILINE)
        if match:
            used |= {name.strip() for name in match.group(1).split(",") if name.strip()}
    assert used and used <= set(names)
