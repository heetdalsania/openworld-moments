# SPDX-License-Identifier: AGPL-3.0-or-later
"""Own synthetic library only: real installed WebView2 -> Tauri IPC -> frozen worker.

The caller enables CDP only in the CI child process, not in application defaults.
This is a hosted Windows Server smoke test, not clean Windows 11 qualification.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/packaging"


def main() -> None:
    installed, mode = Path(sys.argv[1]), sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        deadline = time.monotonic() + 60
        while True:
            try:
                browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9223")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        context = browser.contexts[0]
        # The CDP browser endpoint can be ready before Tauri creates its first
        # WebView target. Wait for the real installed page, never create a tab.
        page = context.pages[0] if context.pages else context.wait_for_event("page", timeout=60000)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            exercise(page, installed, mode)
        except Exception:
            diagnostic: dict[str, object] = {"mode": mode, "page_errors": errors[-20:]}
            try:
                diagnostic["ui"] = page.evaluate(
                    "() => ({url: location.href, text: document.body.innerText.slice(0,20000), "
                    "acknowledgement: localStorage.getItem('owm-system-check-0.1')})"
                )
                diagnostic["worker"] = page.evaluate(
                    "() => window.__TAURI_INTERNALS__.invoke('worker_status')"
                )
                # Record every status change for 20 s: a restart's reason carries the
                # worker's exit status, and a crash loop ends in a stderr tail.
                timeline: list[object] = []
                watch_until = time.monotonic() + 20
                while time.monotonic() < watch_until:
                    status = page.evaluate(
                        "() => window.__TAURI_INTERNALS__.invoke('worker_status')"
                    )
                    if not timeline or timeline[-1] != status:
                        timeline.append(status)
                    time.sleep(0.1)
                diagnostic["worker_timeline"] = timeline
            except Exception as error:
                diagnostic["capture_error"] = str(error)[:2000]
            (OUT / f"native-{mode}-diagnostics.json").write_text(
                json.dumps(diagnostic, indent=2), encoding="utf-8"
            )
            raise
        finally:
            # Disconnect CDP; PowerShell closes the owned native window gracefully.
            browser.close()


def exercise(page, installed: Path, mode: str) -> None:
    page.wait_for_function("typeof window.__TAURI_INTERNALS__?.invoke === 'function'")

    def api(method: str, path: str, body: object = None) -> object:
        return page.evaluate(
            "async args => { try { return await "
            "window.__TAURI_INTERNALS__.invoke('worker_api', args); } "
            "catch (error) { throw new Error(JSON.stringify(error)); } }",
            {"method": method, "path": path, "body": body},
        )

    def finish(job: dict) -> dict:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = api("GET", f"/v1/jobs/{job['id']}")
            if result["state"] == "ready":
                return result
            if result["state"] in {"failed", "cancelled"}:
                raise RuntimeError(f"Packaged job failed: {result.get('error', {}).get('code')}")
            time.sleep(0.1)
        raise RuntimeError("Packaged job timed out")

    # Poll from Python: an async predicate passed to wait_for_function returns a Promise,
    # which is truthy, so that wait passed while the worker was still starting.
    deadline = time.monotonic() + 90
    while True:
        status = page.evaluate("() => window.__TAURI_INTERNALS__.invoke('worker_status')")
        if status.get("status") == "ready":
            break
        if status.get("status") == "failed" or time.monotonic() >= deadline:
            raise RuntimeError(f"Packaged worker did not become ready: {status}")
        time.sleep(0.25)
    identity = page.evaluate("() => window.__TAURI_INTERNALS__.invoke('app_info')")
    expected = "0.1.0-alpha.29.1" if mode == "upgrade" else "0.1.0-alpha.29"
    assert identity["version"] == expected, identity
    doctor = api("GET", "/v1/system-doctor")
    assert doctor["packaged"] and doctor["ready"], doctor["checks"]
    if mode == "import-render":
        page.get_by_role("heading", name="Welcome — check this computer", exact=True).wait_for(
            timeout=90000
        )
        page.get_by_role("button", name="Continue", exact=True).click(timeout=90000)
    # Scope to the primary navigation: an empty library also links to Settings.
    page.get_by_role("navigation", name="Primary").get_by_role(
        "link", name="Settings", exact=True
    ).click()
    page.get_by_role("heading", name="Optional speech models", exact=True).wait_for()
    page.get_by_text("Core checks passed", exact=True).wait_for()
    models = api("GET", "/v1/model-manager")
    assert len(models["models"]) == 2
    assert all(m["active_sha256"] is None and m["downloaded_bytes"] == 0 for m in models["models"])
    if mode == "import-render":
        clip = OUT / "Synthetic capture ✓ 日本語.mp4"
        subprocess.run(
            [
                str(installed / "runtime/tools/ffmpeg.exe"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=30:duration=3",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(clip),
            ],
            check=True,
        )
        digest = hashlib.sha256(clip.read_bytes()).hexdigest()
        imported = finish(
            api(
                "POST",
                "/v1/imports",
                {"paths": [str(clip)], "mode": "managed", "recursive": False},
            )
        )
        asset = imported["result"]["items"][0]["asset_id"]
        finish(api("POST", f"/v1/assets/{asset}/derived", {"proxy_policy": "always"}))
        finish(api("POST", "/v1/sessions/recompute", {}))
        session = api("GET", "/v1/sessions?limit=200")[0]["id"]
        selection = api("GET", f"/v1/sessions/{session}/project-selection")
        project = api(
            "POST",
            f"/v1/sessions/{session}/projects",
            {
                "title": "Packaged synthetic smoke",
                "layout_key": selection["layout_key"],
                "start_ms": 0,
                "end_ms": 3000,
            },
        )
        pid = project["document"]["project"]["id"]
        review = api("GET", f"/v1/projects/{pid}/privacy-review")
        api(
            "POST",
            f"/v1/projects/{pid}/privacy-review",
            {
                "token": review["token"],
                "decisions": [{"id": f["id"], "state": "acknowledge"} for f in review["flags"]],
                "acknowledged": True,
            },
        )
        rendered = finish(
            api(
                "POST",
                f"/v1/projects/{pid}/render",
                {
                    "preset_id": "horizontal-1080p30",
                    "encoder": "libx264",
                    "expected_revision": project["revision"],
                },
            )
        )
        assert rendered["state"] == "ready"
        assert hashlib.sha256(clip.read_bytes()).hexdigest() == digest
        (OUT / "saved-project-id.txt").write_text(pid)
    else:
        pid = (OUT / "saved-project-id.txt").read_text()
        project = api("GET", f"/v1/projects/{pid}")
        assert project["document"]["project"]["title"] == "Packaged synthetic smoke"
        assert api("GET", f"/v1/projects/{pid}/renders")[0]["status"] == "ready"
    report = {
        "mode": mode,
        "application": identity,
        "scope": "Hosted Windows Server; clean Windows 11 client qualification pending",
        "doctor": doctor,
        "webview_user_agent": page.evaluate("navigator.userAgent"),
        "models_downloaded": False,
        "native_ipc": True,
        "project_preserved": True,
    }
    (OUT / f"native-{mode}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
