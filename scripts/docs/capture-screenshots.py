# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capture the user-guide screenshots (M31) from the real UI with synthetic data.

The desktop host is replaced by ``fake-host.js`` (synthetic clips, system check and
diagnostics only), so no worker, library, footage or personal path is involved and the
images are safe to publish. Re-run after UI changes:

    uv run --directory services/media-worker --group packaging \\
        python ../../scripts/docs/capture-screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ROOT, context, launch, preferences, scene, serve

OUT = ROOT / "docs" / "guides" / "images"


def shot(page: Page, name: str, *, element: str | None = None) -> None:
    page.wait_for_timeout(300)
    target = page.locator(element) if element else page
    target.screenshot(path=str(OUT / f"{name}.png"), animations="disabled")
    print(f"saved {name}.png")


def capture(page: Page) -> None:
    scene(page, preferences(onboarding="pending"))
    shot(page, "setup-welcome")
    page.get_by_role("button", name="Start setup").click()
    page.get_by_text("Core checks passed", exact=True).wait_for()
    page.mouse.click(5, 5)  # drop the heading's keyboard focus ring for the picture
    shot(page, "setup-system-check")
    page.get_by_role("button", name="Continue").click()
    page.mouse.click(5, 5)
    shot(page, "setup-import-methods")
    page.get_by_role("button", name="Continue").click()
    page.mouse.click(5, 5)
    shot(page, "setup-privacy")

    scene(page, preferences())
    page.get_by_text("Synthetic capture - night drive.mp4").first.wait_for()
    shot(page, "library")
    page.get_by_role("button", name="Import", exact=True).click()
    page.get_by_role("dialog", name="Import media").wait_for()
    shot(page, "import-dialog")

    scene(page, preferences(), "#/phone")
    page.get_by_role("heading", name="Phone transfer is off").wait_for()
    shot(page, "phone-consent")

    scene(page, preferences(), "#/settings")
    page.get_by_role("button", name="Preview report").click()
    page.get_by_role("region", name="Report preview").wait_for()
    shot(page, "settings-diagnostics", element="section.diagnostics")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with serve(), sync_playwright() as playwright:
        browser = launch(playwright)
        page = context(browser).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        capture(page)
        browser.close()
        if errors:
            raise RuntimeError(f"page errors: {errors}")


if __name__ == "__main__":
    main()
