# SPDX-License-Identifier: AGPL-3.0-or-later
"""M31 user guides: versioned, linked, illustrated with safe screenshots only."""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ROOT / "docs" / "guides"
IMAGES = GUIDES / "images"
PAGES = sorted(GUIDES.glob("*.md"))
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
HEADER = re.compile(
    r"^> \*\*Applies to:\*\* OpenWorld Moments \d+\.\d+\.\d+ "
    # M38: Windows-only guides, guides that cover both, and the macOS preview guide.
    r"(?:alpha for Windows 11 \(x64\)(?:, and the macOS 14\+ preview)?"
    r"|preview for macOS 14 or later \(Apple Silicon and Intel\))\.\n"
    r"> \*\*Last checked:\*\* (\d{4}-\d{2}-\d{2}) \(M\d+\)",
    re.MULTILINE,
)


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(page: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", page.read_text("utf-8"), flags=re.DOTALL)
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, re.MULTILINE)}


def links(page: Path) -> list[tuple[bool, str, str]]:
    text = re.sub(r"```.*?```", "", page.read_text("utf-8"), flags=re.DOTALL)
    return [(m.group(1) == "!", m.group(2), m.group(3)) for m in LINK.finditer(text)]


def test_there_are_guides_for_every_required_topic() -> None:
    names = {p.stem for p in PAGES}
    assert {
        "README",
        "getting-started",
        "xbox-onedrive",
        "phone-upload",
        "watched-folders",
        "capture-card",
        "troubleshooting",
        "diagnostics",
        "terminology",
        "known-limitations",
        "accessibility",
        "compatibility",
        "macos",
    } <= names


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_every_guide_states_its_version_and_check_date(page: Path) -> None:
    match = HEADER.search(page.read_text("utf-8"))
    assert match, f"{page.name} needs the Applies to / Last checked lines"
    assert match.group(1) >= "2026-11-11"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_every_relative_link_and_image_resolves(page: Path) -> None:
    for image, label, target in links(page):
        if re.match(r"^[a-z]+:", target):
            assert target.startswith("https://"), f"{page.name}: {target} must use https"
            continue
        path, _, anchor = target.partition("#")
        resolved = (page.parent / path).resolve() if path else page
        assert resolved.exists(), f"{page.name}: broken link {target}"
        assert resolved.is_relative_to(ROOT), f"{page.name}: {target} leaves the repository"
        if anchor and resolved.suffix == ".md":
            assert anchor in anchors(resolved), f"{page.name}: missing anchor {target}"
        if image:
            assert label.strip(), f"{page.name}: image {target} needs alt text"
            assert resolved.parent == IMAGES, f"{page.name}: keep guide images in images/"


def test_the_index_lists_every_guide() -> None:
    index = {target.partition("#")[0] for _, _, target in links(GUIDES / "README.md")}
    for page in PAGES:
        if page.name != "README.md":
            assert f"./{page.name}" in index, f"README.md does not link {page.name}"


def png_chunks(path: Path) -> list[bytes]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    chunks, offset = [], 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunks.append(data[offset + 4 : offset + 8])
        offset += 12 + length
    return chunks


def test_screenshots_are_referenced_small_and_carry_no_text_metadata() -> None:
    images = sorted(IMAGES.glob("*"))
    assert images, "guide screenshots are missing"
    used = {
        (page.parent / target).resolve()
        for page in PAGES
        for image, _, target in links(page)
        if image
    }
    for image in images:
        assert image.suffix == ".png", f"{image.name}: only PNG screenshots"
        assert image.resolve() in used, f"{image.name} is not used by any guide"
        assert image.stat().st_size < 400_000, f"{image.name} is too large"
        # Text chunks could carry a capture path or tool details; screenshots have none.
        assert not {b"tEXt", b"iTXt", b"zTXt", b"eXIf"} & set(png_chunks(image)), image.name


def test_guides_do_not_point_at_personal_or_build_paths() -> None:
    for page in PAGES:
        text = page.read_text("utf-8")
        assert not re.search(r"(?i)c:\\users\\[a-z]|/users/[a-z]|runneradmin", text), page.name


# -- M38: macOS guidance -----------------------------------------------------------------

#: Advice that would weaken a system protection. A line may mention these only to say
#: never to do it.
RISKY = re.compile(
    r"(?i)xattr|quarantine|spctl|master-disable|(?:disable|bypass|turn off|around)\s+gatekeeper"
    r"|gatekeeper\s+off|open anyway|right-click.*\bopen\b|control-click|turn off the firewall"
    r"|disable the firewall|firewall off|csrutil|\bsip\b|sudo|full disk access"
    r"|security settings?|bypass|work around|get around"
)
NEGATION = re.compile(r"(?i)\bnever\b|\bdon['\u2019]t\b|\bdo not\b|\bnot\b|\bnone\b|\bno\b")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_guides_never_suggest_bypassing_macos_protections(page: Path) -> None:
    text = re.sub(r"```.*?```", "", page.read_text("utf-8"), flags=re.DOTALL)
    for number, line in enumerate(text.splitlines(), 1):
        if RISKY.search(line):
            assert NEGATION.search(line), f"{page.name}:{number}: {line.strip()}"


def test_macos_guide_says_builds_are_previews_until_notarized() -> None:
    text = (GUIDES / "macos.md").read_text("utf-8")
    assert "macOS builds are previews" in text
    assert "not for general" in text and "download" in text
    assert "notarized" in text
    for name in ("macos.md", "README.md", "known-limitations.md", "troubleshooting.md"):
        assert re.search(r"(?i)preview", (GUIDES / name).read_text("utf-8")), name


def test_macos_guide_covers_every_required_topic() -> None:
    headings = anchors(GUIDES / "macos.md")
    for required in (
        "which-download",
        "install",
        "first-run-setup",
        "permissions-and-recovery",
        "getting-clips-onto-your-mac",
        "menus-and-keyboard-shortcuts",
        "update",
        "uninstall",
        "privacy-on-a-mac",
        "diagnostics",
        "validation",
    ):
        assert required in headings, required


def test_architecture_selection_names_both_native_dmgs() -> None:
    text = (GUIDES / "macos.md").read_text("utf-8")
    assert "`OpenWorld-Moments_<version>_macOS_arm64.dmg`" in text
    assert "`OpenWorld-Moments_<version>_macOS_x86_64.dmg`" in text
    # The same naming as ADR-0008 and the signing script.
    adr = (ROOT / "docs/architecture/adr/0008-macos-distribution.md").read_text("utf-8")
    assert "_macOS_arm64.dmg" in adr and "_macOS_x86_64.dmg" in adr
    assert re.search(r"Apple (Silicon|M1)", text) and "Intel" in text


def test_macos_guide_links_the_signing_install_section() -> None:
    targets = {target for _, _, target in links(GUIDES / "macos.md")}
    assert "../platforms/macos-signing.md#install-upgrade-replace-and-uninstall" in targets
