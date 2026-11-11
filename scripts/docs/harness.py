# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared harness for documentation screenshots and the browser accessibility smoke.

Starts the desktop frontend with Vite and replaces the desktop host with ``fake-host.js``,
so the real UI runs in Chrome with synthetic data only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

ROOT = Path(__file__).resolve().parents[2]
PORT = 1437
URL = f"http://localhost:{PORT}/"
STUB = (Path(__file__).resolve().parent / "fake-host.js").read_text("utf-8")


def preferences(**changes: Any) -> str:
    prefs: dict[str, Any] = {
        "onboarding": "completed",
        "privacy": {"phoneLan": False, "modelDownloads": False},
        "appearance": {"theme": "light", "textSize": 100, "motion": "reduce"},
    }
    prefs.update(changes)
    return json.dumps(prefs)


@contextmanager
def serve() -> Iterator[str]:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm is required")
    server = subprocess.Popen(  # noqa: S603 - fixed arguments
        [pnpm, "--dir", "apps/desktop", "exec", "vite", "--port", str(PORT), "--strictPort"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(URL, timeout=1):
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Vite did not start") from None
                time.sleep(0.25)
        yield URL
    finally:
        server.terminate()
        server.wait(timeout=10)


def launch(playwright: Playwright) -> Browser:
    try:
        return playwright.chromium.launch()
    except Exception:  # fall back to an installed Chrome
        return playwright.chromium.launch(channel="chrome")


def context(browser: Browser, **options: Any) -> BrowserContext:
    settings: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 860},
        "device_scale_factor": 1,
        "color_scheme": "light",
        "reduced_motion": "reduce",
        "locale": "en-US",
    }
    settings.update(options)
    ctx = browser.new_context(**settings)
    ctx.add_init_script(STUB)
    return ctx


def scene(page: Page, prefs: str, hash_: str = "") -> None:
    """Open the app at ``hash_`` with the given stored preferences."""
    page.goto(URL + hash_)
    page.evaluate("p => localStorage.setItem('owm.preferences.v1', p)", prefs)
    page.reload()
    page.get_by_role("heading", level=1).first.wait_for()
