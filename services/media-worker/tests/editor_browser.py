# SPDX-License-Identifier: AGPL-3.0-or-later
"""M22 manual Chromium fixture bridge. Never used by the production app.

Run with the worker's locked environment, then use the printed IPC script with
Playwright CLI and the normal Vite frontend. All sources/library data are temporary
and synthetic. Closing this process removes them. No user library is opened.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MEDIA = re.compile(
    r"^/asset/(ast_[0-9A-HJKMNP-TV-Z]{26})/(original|proxy|waveform|thumbnail/[0-9]+)$"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument(
        "--captions",
        action="store_true",
        help="M23: seed a transcript with the M18 test double; no real recognition",
    )
    args = parser.parse_args()
    prefix = "m23" if args.captions else "m22"
    args.artifacts.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required for the synthetic browser fixture.")
    with tempfile.TemporaryDirectory(prefix="owm-editor-smoke-") as temporary:
        root = Path(temporary).resolve()
        clips = []
        for i, pattern in enumerate(["testsrc2", "smptebars"]):
            target = root / f"Synthetic capture {i + 1}.mp4"
            subprocess.run(  # noqa: S603 - fixed synthetic filter arguments
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"{pattern}=size=640x360:rate=30:duration=6",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={440 + i * 220}:duration=6",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-metadata",
                    f"creation_time=2026-11-01T20:00:0{i * 6}Z",
                    str(target),
                ],
                check=True,
            )
            clips.append(str(target))
        token = secrets.token_hex(32)
        with (root / "worker.log").open("wb") as log:
            worker = subprocess.Popen(  # noqa: S603 - fixed local worker module
                [
                    sys.executable,
                    "-m",
                    "openworld_moments.worker",
                    "--library",
                    str(root / "library"),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
            )
            try:
                if worker.stdin is None or worker.stdout is None:
                    raise RuntimeError("worker pipes unavailable")
                worker.stdin.write(token + "\n")
                worker.stdin.flush()
                ready = json.loads(worker.stdout.readline())
                if ready.get("event") != "ready":
                    raise RuntimeError("Synthetic fixture worker could not start")
                base = f"http://127.0.0.1:{ready['port']}"

                def api(method: str, path: str, body: Any = None) -> Any:
                    data = None if body is None else json.dumps(body).encode()
                    request = Request(  # noqa: S310 - fixed loopback worker base
                        base + path,
                        data=data,
                        method=method,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                    )
                    with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed loopback worker
                        return json.load(response)

                def finish(job: Any) -> Any:
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        result = api("GET", f"/v1/jobs/{job['id']}")
                        if result["state"] == "ready":
                            return result
                        if result["state"] in {"failed", "cancelled"}:
                            raise RuntimeError("Synthetic fixture job failed")
                        time.sleep(0.1)
                    raise RuntimeError("Synthetic fixture job timed out")

                imported = finish(
                    api(
                        "POST",
                        "/v1/imports",
                        {"paths": clips, "mode": "reference", "recursive": False},
                    )
                )
                ids = [item["asset_id"] for item in imported["result"]["items"]]
                finish(api("POST", "/v1/sessions/recompute", {}))
                sid = api("GET", "/v1/sessions?limit=200")[0]["id"]
                for aid in ids:
                    finish(api("POST", f"/v1/assets/{aid}/derived", {"proxy_policy": "always"}))
                if args.captions:
                    from openworld_moments.derived.service import DerivedMedia
                    from openworld_moments.ids import new_id
                    from openworld_moments.media.tools import MediaTools
                    from openworld_moments.storage import Database
                    from openworld_moments.transcripts.service import Transcriber
                    from openworld_moments.transcripts.whisper import Engine, sha256_file

                    tests = Path(__file__).parent
                    fake = tests / "transcripts" / "fake_whisper.py"
                    database = Database.open(root / "library" / "database.sqlite3")
                    tools = MediaTools()
                    transcriber = Transcriber(
                        database,
                        tools,
                        DerivedMedia(database, tools),
                        engine=lambda cancel: Engine(
                            (sys.executable, str(fake)), fake, "1.7.6", sha256_file(fake)
                        ),
                    )
                    model = root / "synthetic-model.bin"
                    model.write_bytes(b"lmgg" + b"\0" * 8192)
                    transcriber.models.install(model, "base.en", "MIT")
                    control = root / "whisper-control.json"
                    control.write_text(
                        json.dumps(
                            {
                                "calls": str(root / "fake-calls.log"),
                                "heartbeat": str(root / "fake-heartbeat"),
                                "output": str(tests / "transcripts" / "whisper-full.json"),
                            }
                        )
                    )
                    previous = os.environ.get("OWM_FAKE_WHISPER")
                    os.environ["OWM_FAKE_WHISPER"] = str(control)
                    try:
                        transcriber.run(
                            {"session_id": sid, "model": "base.en"}, job_id=new_id("job")
                        )
                    finally:
                        if previous is None:
                            os.environ.pop("OWM_FAKE_WHISPER", None)
                        else:
                            os.environ["OWM_FAKE_WHISPER"] = previous
                selection = api("GET", f"/v1/sessions/{sid}/project-selection")
                api(
                    "POST",
                    f"/v1/sessions/{sid}/review",
                    {
                        "layout_key": selection["layout_key"],
                        "type": "openworld.manual",
                        "start_ms": 2500,
                        "end_ms": 3500,
                    },
                )

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, format: str, *values: Any) -> None:
                        pass

                    def headers_for(self, content_type: str, size: int) -> None:
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(size))
                        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:1420")
                        self.send_header("Access-Control-Allow-Headers", "Content-Type,Range")
                        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
                        self.end_headers()

                    def do_OPTIONS(self) -> None:
                        self.send_response(204)
                        self.headers_for("text/plain", 0)

                    def forward(self) -> None:
                        path = self.path.partition("?")[0]
                        identity = r"[0-9A-HJKMNP-TV-Z]{26}"
                        read = self.command == "GET" and (
                            path
                            in {
                                "/v1/projects",
                                "/v1/sessions",
                                "/v1/assets",
                                "/v1/jobs",
                                "/v1/profiles",
                                "/v1/transcription/models",
                                "/v1/render/presets",
                                "/v1/render/encoders",
                            }
                            or re.fullmatch(r"/v1/profiles/[a-z0-9][a-z0-9-]*/calibration", path)
                            or re.fullmatch(
                                rf"/v1/projects/prj_{identity}(?:/(?:portable|renders))?", path
                            )
                            or re.fullmatch(
                                rf"/v1/sessions/ses_{identity}(?:/(?:project-selection|review|overlaps|transcript))?",
                                path,
                            )
                            or re.fullmatch(rf"/v1/assets/ast_{identity}(?:/derived)?", path)
                            or re.fullmatch(rf"/v1/jobs/job_{identity}", path)
                        )
                        write = (
                            self.command == "PUT"
                            and re.fullmatch(rf"/v1/projects/prj_{identity}", path)
                        ) or (
                            self.command == "POST"
                            and (
                                re.fullmatch(rf"/v1/sessions/ses_{identity}/projects", path)
                                or re.fullmatch(rf"/v1/assets/ast_{identity}/derived", path)
                                or re.fullmatch(rf"/v1/projects/prj_{identity}/render", path)
                            )
                        )
                        if not (read or write) or self.headers.get("Origin") not in {
                            None,
                            "http://127.0.0.1:1420",
                        }:
                            self.send_error(403)
                            return
                        size = int(self.headers.get("Content-Length", "0"))
                        if not 0 <= size <= 5 * 1024 * 1024:
                            self.send_error(413)
                            return
                        data = self.rfile.read(size) if size else None
                        request = Request(  # noqa: S310 - fixed loopback worker base
                            base + self.path,
                            data=data,
                            method=self.command,
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                            },
                        )
                        try:
                            response = urlopen(request, timeout=120)  # noqa: S310 - fixed loopback worker
                        except HTTPError as error:
                            response = error
                        with response:
                            payload = response.read()
                            self.send_response(response.status)
                            self.headers_for("application/json", len(payload))
                            self.wfile.write(payload)

                    def do_POST(self) -> None:
                        self.forward()

                    def do_PUT(self) -> None:
                        self.forward()

                    def do_GET(self) -> None:
                        match = MEDIA.fullmatch(self.path)
                        if not match:
                            self.forward()
                            return
                        aid, variant = match.groups()
                        if variant.startswith("thumbnail/"):
                            lookup = (
                                f"/v1/assets/{aid}/media/thumbnail?index={variant.split('/')[1]}"
                            )
                        else:
                            lookup = f"/v1/assets/{aid}/media/{variant}"
                        try:
                            item = api("GET", lookup)
                            path = Path(item["path"]).resolve()
                            if not path.is_relative_to(root):
                                self.send_error(403)
                                return
                            data = path.read_bytes()
                        except (HTTPError, OSError):
                            self.send_error(404)
                            return
                        total = len(data)
                        requested = self.headers.get("Range")
                        status, start, end = 200, 0, total - 1
                        if requested:
                            parsed = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                            if not parsed or int(parsed[1]) >= total:
                                self.send_response(416)
                                self.send_header("Content-Range", f"bytes */{total}")
                                self.headers_for(item["content_type"], 0)
                                return
                            start = int(parsed[1])
                            end = min(total - 1, int(parsed[2]) if parsed[2] else total - 1)
                            status = 206
                        payload = data[start : end + 1]
                        self.send_response(status)
                        self.send_header("Accept-Ranges", "bytes")
                        if status == 206:
                            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                        self.headers_for(item["content_type"], len(payload))
                        self.wfile.write(payload)

                with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
                    bridge = f"http://127.0.0.1:{server.server_port}"
                    script = f"""
// M22 synthetic fixture IPC only. Not shipped with the application.
Object.defineProperty(navigator, 'userAgent', {{value:'Windows Chromium editor smoke'}});
let callbackId=0;
window.__TAURI_EVENT_PLUGIN_INTERNALS__={{unregisterListener:()=>{{}},registerListener:()=>{{}}}};
window.__TAURI_INTERNALS__={{
 metadata:{{currentWindow:{{label:'main'}},currentWebview:{{label:'main'}}}},
 transformCallback:()=>++callbackId,unregisterCallback:()=>{{}},
 invoke:async(command,args)=>{{
  if(command==='worker_status')return {{status:'ready',port:1,pid:1,restarts:0}};
  if(command==='app_info')return {{name:'OpenWorld Moments',version:'0.0.0',stage:'editor smoke'}};
  if(command==='worker_api'){{
   const options={{method:args.method,headers:{{'Content-Type':'application/json'}}}};
   if(args.method!=='GET')options.body=JSON.stringify(args.body);
   const response=await fetch({json.dumps(bridge)}+args.path,options);
   const result=await response.json();if(!response.ok)throw result;return result;
  }}
  if(command==='watched_folders_list')return {{folders:[],status:[]}};
  if(command.startsWith('plugin:event|'))return 1;
  return null;
 }}
}};
"""
                    ipc = args.artifacts / f"{prefix}-ipc.js"
                    ipc.write_text(script)
                    manifest = {
                        "bridge": bridge,
                        "session_id": sid,
                        "ipc": str(ipc.resolve()),
                        "assets": ids,
                    }
                    (args.artifacts / f"{prefix}-fixture.json").write_text(
                        json.dumps(manifest, indent=2)
                    )
                    print(json.dumps(manifest), flush=True)
                    with contextlib.suppress(KeyboardInterrupt):
                        server.serve_forever()
            finally:
                worker.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    worker.wait(timeout=5)
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()


if __name__ == "__main__":
    main()
