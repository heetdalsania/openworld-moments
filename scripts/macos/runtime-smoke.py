# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise a frozen macOS runtime exactly as the desktop host starts it (M34).

    python3 scripts/macos/runtime-smoke.py apps/desktop/src-tauri/bundle-input/runtime
    python3 scripts/macos/runtime-smoke.py "<app>/Contents/Resources/runtime"

Runs with an empty environment (only HOME and LANG), so nothing comes from a shell
PATH, Homebrew or a system Python, from a copy of the runtime in a Unicode folder with a
Unicode library:

1. start: token on stdin, ready line on stdout, as the host does;
2. system doctor: packaged, ready, every bundled tool with version, hash, origin,
   license and this Mac's architecture;
3. a synthetic clip made by the bundled FFmpeg: import, playback copy, session,
   project, privacy review and a CPU (libx264) render, checked with the bundled FFprobe;
   the source clip is unchanged;
4. cancellation of a running job;
5. a missing tool and a corrupt tool each stop the worker quickly with
   `worker.bundle_corrupt` instead of hanging.

Writes output/packaging/macos-runtime-smoke.json. Uses only synthetic media.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "packaging"
ARCH = {"arm64": "arm64", "x86_64": "x86_64"}[platform.machine()]
ENV = {"HOME": os.environ.get("HOME", "/"), "LANG": "C"}


class Worker:
    def __init__(self, runtime: Path, library: Path) -> None:
        self.token = secrets.token_hex(32)
        self.proc = subprocess.Popen(  # noqa: S603 - the frozen worker, fixed arguments
            [
                str(runtime / "owm-worker"),
                "-m",
                "openworld_moments.worker",
                "--library",
                str(library),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=ENV,
        )
        self.stderr: list[str] = []
        threading.Thread(
            target=lambda: self.stderr.extend(iter(self.proc.stderr.readline, "")),  # type: ignore[union-attr]
            daemon=True,
        ).start()
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(self.token + "\n")
        self.proc.stdin.flush()
        self.ready = json.loads(self.proc.stdout.readline() or "{}")
        self.port = int(self.ready.get("port", 0))

    def api(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - loopback
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path}: {error.code} {error.read()[:300]!r}") from error

    def finish(self, job: dict[str, Any], seconds: float = 300) -> dict[str, Any]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result: dict[str, Any] = self.api("GET", f"/v1/jobs/{job['id']}")
            if result["state"] in {"ready", "failed", "cancelled"}:
                return result
            time.sleep(0.1)
        raise RuntimeError(f"job {job['id']} timed out")

    def stop(self) -> int:
        if self.proc.poll() is None:
            assert self.proc.stdin
            self.proc.stdin.close()  # the host's shutdown signal
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        return self.proc.returncode


def broken_start(runtime: Path, library: Path, seconds: float = 30) -> dict[str, Any]:
    """Start a damaged runtime; it must report and exit, not hang."""
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 - the frozen worker, fixed arguments
        [str(runtime / "owm-worker"), "-m", "openworld_moments.worker", "--library", str(library)],
        input="0" * 64 + "\n",
        capture_output=True,
        text=True,
        timeout=seconds,
        env=ENV,
        check=False,
    )
    line = json.loads(proc.stdout.splitlines()[0]) if proc.stdout.strip() else {}
    return {
        "exit_code": proc.returncode,
        "code": line.get("code"),
        "seconds": round(time.monotonic() - started, 2),
    }


def run(source: Path) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="owm-mac-smoke-"))
    runtime = scratch / "Runtime ✓ 日本語"
    shutil.copytree(source, runtime, symlinks=True)
    library = scratch / "Library ✓ 日本語" / "library"
    report: dict[str, Any] = {"architecture": ARCH, "macos": platform.mac_ver()[0]}

    worker = Worker(runtime, library)
    try:
        assert worker.ready.get("event") == "ready", worker.ready
        doctor = worker.api("GET", "/v1/system-doctor")
        assert doctor["packaged"] and doctor["ready"], doctor["checks"]
        bundled = {t["name"]: t for t in doctor["tools"] if t.get("origin") == "bundle"}
        for name in ("ffmpeg", "ffprobe"):
            tool = bundled[name]
            assert tool["architecture"] == ARCH and len(tool["sha256"]) == 64, tool
            assert tool["license"] == "GPL-2.0-or-later" and "9.0.2" in tool["version"], tool
        report["doctor"] = {
            "ready": doctor["ready"],
            "architecture": doctor["architecture"],
            "tools": [
                {
                    k: t.get(k)
                    for k in ("name", "version", "origin", "license", "architecture", "sha256")
                }
                for t in doctor["tools"]
            ],
        }

        clip = scratch / "Synthetic capture ✓ 日本語.mp4"
        subprocess.run(  # noqa: S603 - the bundled FFmpeg, fixed arguments
            [
                str(runtime / "tools/ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=30:duration=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(clip),
            ],
            check=True,
            env=ENV,
        )
        before = hashlib.sha256(clip.read_bytes()).hexdigest()
        imported = worker.finish(
            worker.api(
                "POST",
                "/v1/imports",
                {"paths": [str(clip)], "mode": "reference", "recursive": False},
            )
        )
        assert imported["state"] == "ready", imported
        asset = imported["result"]["items"][0]["asset_id"]
        derived = worker.finish(
            worker.api("POST", f"/v1/assets/{asset}/derived", {"proxy_policy": "always"})
        )
        assert derived["state"] == "ready", derived
        worker.finish(worker.api("POST", "/v1/sessions/recompute", {}))
        session = worker.api("GET", "/v1/sessions?limit=200")[0]["id"]
        selection = worker.api("GET", f"/v1/sessions/{session}/project-selection")
        project = worker.api(
            "POST",
            f"/v1/sessions/{session}/projects",
            {
                "title": "macOS runtime smoke",
                "layout_key": selection["layout_key"],
                "start_ms": 0,
                "end_ms": 3000,
            },
        )
        pid = project["document"]["project"]["id"]
        review = worker.api("GET", f"/v1/projects/{pid}/privacy-review")
        worker.api(
            "POST",
            f"/v1/projects/{pid}/privacy-review",
            {
                "token": review["token"],
                "decisions": [{"id": f["id"], "state": "acknowledge"} for f in review["flags"]],
                "acknowledged": True,
            },
        )
        rendered = worker.finish(
            worker.api(
                "POST",
                f"/v1/projects/{pid}/render",
                {
                    "preset_id": "horizontal-1080p30",
                    "encoder": "libx264",
                    "expected_revision": project["revision"],
                },
            )
        )
        assert rendered["state"] == "ready", rendered
        renders = worker.api("GET", f"/v1/projects/{pid}/renders")
        output = library / renders[0]["output"]["relative_path"]
        probe = json.loads(
            subprocess.check_output(  # noqa: S603 - the bundled FFprobe, fixed arguments
                [
                    str(runtime / "tools/ffprobe"),
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(output),
                ],
                env=ENV,
            )
        )
        codecs = sorted(s["codec_name"] for s in probe["streams"])
        assert codecs == ["aac", "h264"], codecs
        assert hashlib.sha256(clip.read_bytes()).hexdigest() == before, "source changed"
        report["render"] = {
            "codecs": codecs,
            "duration_s": float(probe["format"]["duration"]),
            "source_unchanged": True,
        }

        job = worker.api(
            "POST", "/v1/jobs", {"kind": "diagnostic", "params": {"steps": 200, "step_ms": 50}}
        )
        worker.api("POST", f"/v1/jobs/{job['id']}/cancel")
        cancelled = worker.finish(job, 30)
        assert cancelled["state"] == "cancelled", cancelled
        report["cancellation"] = cancelled["state"]
    finally:
        report["clean_exit"] = worker.stop() == 0
        report["stderr_tail"] = "".join(worker.stderr)[-2000:].replace(worker.token, "<token>")

    missing = scratch / "Missing tool"
    shutil.copytree(source, missing, symlinks=True)
    (missing / "tools/ffprobe").unlink()
    corrupt = scratch / "Corrupt tool"
    shutil.copytree(source, corrupt, symlinks=True)
    with (corrupt / "tools/ffmpeg").open("r+b") as stream:
        stream.seek(4096)
        stream.write(b"corrupt")
    report["missing_tool"] = broken_start(missing, scratch / "lib-missing")
    report["corrupt_tool"] = broken_start(corrupt, scratch / "lib-corrupt")
    for case in ("missing_tool", "corrupt_tool"):
        result = report[case]
        assert result["code"] == "worker.bundle_corrupt" and result["exit_code"] == 3, result
        assert result["seconds"] < 30, result
    shutil.rmtree(scratch, ignore_errors=True)
    return report


def main() -> int:
    if len(sys.argv) != 2 or sys.platform != "darwin":
        print(__doc__, file=sys.stderr)
        return 2
    report = run(Path(sys.argv[1]).resolve())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "macos-runtime-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "stderr_tail"}, indent=2))
    print(f"macOS {ARCH} runtime smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
