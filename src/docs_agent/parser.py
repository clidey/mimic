"""Parse llms.txt into individual Page objects."""

from __future__ import annotations

import re
from pathlib import Path

from docs_agent.models import Page

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
LLMS_TXT = ASSETS_DIR / "llms.txt"

# Matches lines like: # introduction.mdx  or  # features/schema-explorer.mdx
_PAGE_HEADER = re.compile(r"^# (.+\.mdx)$")


def parse_pages(path: Path = LLMS_TXT) -> list[Page]:
    """Split llms.txt into Page objects, one per .mdx header."""
    lines = path.read_text().splitlines()
    pages: list[Page] = []
    current_filename: str | None = None
    current_start: int = 0
    content_lines: list[str] = []

    for i, line in enumerate(lines):
        m = _PAGE_HEADER.match(line)
        if m:
            # Flush previous page
            if current_filename is not None:
                pages.append(_make_page(current_filename, content_lines, current_start, i - 1))
            current_filename = m.group(1)
            current_start = i
            content_lines = []
        elif current_filename is not None:
            content_lines.append(line)

    # Flush last page
    if current_filename is not None:
        pages.append(_make_page(current_filename, content_lines, current_start, len(lines) - 1))

    return pages


def _make_page(filename: str, content_lines: list[str], start: int, end: int) -> Page:
    # Strip trailing --- separators
    while content_lines and content_lines[-1].strip() in ("---", ""):
        content_lines.pop()
    slug = filename.removesuffix(".mdx")
    content = "\n".join(content_lines)
    return Page(slug=slug, filename=filename, content=content, line_start=start, line_end=end)


def find_page_by_slug(pages: list[Page], slug: str) -> Page | None:
    """Find a page by its slug (e.g. 'features/schema-explorer')."""
    for p in pages:
        if p.slug == slug:
            return p
    return None
