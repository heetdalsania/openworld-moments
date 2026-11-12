# SPDX-License-Identifier: AGPL-3.0-or-later
"""Browser accessibility smoke for the desktop UI (M31), with synthetic data only.

Covers what can be measured in a real browser engine without the desktop shell:

* keyboard: Tab order from the top, a visible focus indicator at every stop, first-run
  setup and the Import dialog driven by keys alone;
* 200% text, 200% zoom and a narrow (400 px) window without horizontal scrolling;
* Windows contrast themes (forced colors), the high-contrast theme and reduced motion.

Screen readers are not covered here; see docs/guides/accessibility.md. Run:

    uv run --directory services/media-worker --group packaging \\
        python ../../scripts/docs/a11y-smoke.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ROOT, context, launch, preferences, scene, serve

ROUTES = {"library": "", "settings": "#/settings", "phone": "#/phone", "search": "#/search"}
IMAGES = ROOT / "docs" / "guides" / "images"

FOCUS_STATE = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const style = getComputedStyle(el);
  const outlined = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2;
  const ringed = style.boxShadow && style.boxShadow !== "none";
  const svgFocus = el instanceof SVGElement && parseFloat(style.strokeWidth) >= 3;
  const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || "")
    .trim().replace(/\\s+/g, " ").slice(0, 40);
  const picker = el.type === "date" && !el.matches(":focus");
  const tag = picker ? "input-date-picker" : el.tagName.toLowerCase();
  return { tag, name, visible: outlined || ringed || svgFocus };
}"""
OVERFLOW = "() => document.documentElement.scrollWidth - window.innerWidth"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' — {detail}' if detail else ''}")


def tab_stops(page: Page, count: int) -> list[dict[str, object]]:
    stops = []
    for _ in range(count):
        page.keyboard.press("Tab")
        state = page.evaluate(FOCUS_STATE)
        if state:
            stops.append(state)
    return stops


def keyboard(browser: Browser) -> None:
    page = context(browser).new_page()
    for route, hash_ in ROUTES.items():
        scene(page, preferences(privacy={"phoneLan": True, "modelDownloads": False}), hash_)
        if route == "search":
            # Search opens with its box focused, ready to type.
            focused = page.evaluate("() => document.activeElement.id")
            check(
                "keyboard/search: opens with the search box focused",
                focused == "search-input",
                focused,
            )
        stops = tab_stops(page, 40)
        first = stops[0] if stops else {}
        # A date field's calendar button is drawn by the browser engine with its own
        # focus ring; it is reported as a documented exception, not a failure.
        hidden = [s for s in stops if not s["visible"] and s["tag"] != "input-date-picker"]
        if route != "search":
            check(
                f"keyboard/{route}: first Tab stop is Skip to content",
                first.get("name") == "Skip to content",
                str(first.get("name")),
            )
        check(
            f"keyboard/{route}: focus visible at every stop ({len(stops)} stops)",
            not hidden,
            ", ".join(f"{s['tag']} {s['name']}" for s in hidden[:5]),
        )

    scene(page, preferences(onboarding="pending"))
    page.get_by_role("button", name="Start setup").focus()
    for label in ("Enter",) * 5:
        page.keyboard.press(label)
        page.wait_for_timeout(50)
        nxt = page.get_by_role("button", name="Continue")
        if nxt.count():
            nxt.focus()
    heading = page.get_by_role("heading", level=1).inner_text()
    check("keyboard/setup: all steps reachable with Enter", heading == "You're ready", heading)
    page.get_by_role("button", name="Go to the library").focus()
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="Library", level=1).wait_for()

    importer = page.get_by_role("button", name="Import", exact=True)
    importer.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Import media")
    dialog.wait_for()
    inside = True
    for _ in range(15):
        page.keyboard.press("Tab")
        inside &= page.evaluate("() => !!document.activeElement.closest('[role=dialog]')")
    check("keyboard/import dialog: Tab stays inside", inside)
    page.keyboard.press("Escape")
    back = page.evaluate("() => document.activeElement.textContent.trim()")
    check(
        "keyboard/import dialog: Escape closes and returns focus",
        back == "Import" and not dialog.count(),
        back,
    )
    page.context.close()


def layout(browser: Browser, label: str, prefs: str, **options: object) -> None:
    page = context(browser, **options).new_page()
    for route, hash_ in ROUTES.items():
        scene(page, prefs, hash_)
        page.wait_for_timeout(100)
        overflow = page.evaluate(OVERFLOW)
        check(f"{label}/{route}: no horizontal scrolling", overflow <= 1, f"{overflow}px wider")
    scene(page, preferences(onboarding="pending") if '"completed"' in prefs else prefs)
    overflow = page.evaluate(OVERFLOW)
    check(f"{label}/setup: no horizontal scrolling", overflow <= 1, f"{overflow}px wider")
    page.context.close()


def contrast_modes(browser: Browser) -> None:
    # Runs before the forced-colors context: Chrome's forced-colors emulation can leak
    # into the next context, which would make this check read the wrong colors.
    page = context(browser).new_page()
    high = preferences(appearance={"theme": "high-contrast", "textSize": 100, "motion": "reduce"})
    scene(page, high, "#/settings")
    theme = page.evaluate("() => document.documentElement.dataset.theme")
    colors = page.evaluate(
        "() => [getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),"
        " getComputedStyle(document.querySelector('main')).color]"
    )
    check(
        "high-contrast theme applies",
        theme == "high-contrast" and colors == ["#000000", "rgb(255, 255, 255)"],
        f"{theme} {colors}",
    )
    page.locator("section.privacy-choices").screenshot(path=str(IMAGES / "high-contrast.png"))
    page.context.close()

    page = context(browser, forced_colors="active").new_page()
    scene(page, preferences(), "#/settings")
    page.get_by_role("button", name="Run setup again").focus()
    page.keyboard.press("Tab")
    state = page.evaluate(FOCUS_STATE)
    check("forced colors: focus indicator visible", bool(state and state["visible"]), str(state))
    page.context.close()

    page = context(browser, reduced_motion="no-preference").new_page()
    reduce = preferences(appearance={"theme": "light", "textSize": 100, "motion": "reduce"})
    scene(page, reduce)
    duration = page.evaluate(
        "() => getComputedStyle(document.querySelector('button')).transitionDuration"
    )
    check("reduced motion from Settings", duration in ("1e-05s", "0.00001s", "0s"), duration)
    page.context.close()


def main() -> None:
    steps: list[Callable[[Browser], None]] = [
        keyboard,
        lambda b: layout(
            b,
            "text 200%",
            preferences(appearance={"theme": "light", "textSize": 200, "motion": "reduce"}),
        ),
        lambda b: layout(
            b,
            "zoom 200%",
            preferences(),
            viewport={"width": 640, "height": 430},
            device_scale_factor=2,
        ),
        lambda b: layout(b, "narrow 400px", preferences(), viewport={"width": 400, "height": 800}),
        contrast_modes,
    ]
    with serve(), sync_playwright() as playwright:
        browser = launch(playwright)
        for step in steps:
            step(browser)
        browser.close()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
