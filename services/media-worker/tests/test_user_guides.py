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
    r"^> \*\*Applies to:\*\* OpenWorld Moments \d+\.\d+\.\d+ alpha for Windows 11 \(x64\)\.\n"
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
