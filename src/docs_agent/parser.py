"""Parse llms.txt into individual Page objects."""

from __future__ import annotations

import re
from pathlib import Path

from docs_agent.models import Page

# Matches lines like: # introduction.mdx  or  # features/schema-explorer.mdx
_PAGE_HEADER_TEMPLATE = r"^# (.+\.{ext})$"


def parse_pages(source: Path, page_format: str = "mdx") -> list[Page]:
    """Split a docs file into Page objects, one per header.

    The file is expected to have ``# filename.{page_format}`` headers
    separating individual pages.
    """
    header_re = re.compile(_PAGE_HEADER_TEMPLATE.format(ext=re.escape(page_format)))
    lines = source.read_text().splitlines()
    pages: list[Page] = []
    current_filename: str | None = None
    current_start: int = 0
    content_lines: list[str] = []

    for i, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            # Flush previous page
            if current_filename is not None:
                pages.append(_make_page(current_filename, content_lines, current_start, i - 1, page_format))
            current_filename = m.group(1)
            current_start = i
            content_lines = []
        elif current_filename is not None:
            content_lines.append(line)

    # Flush last page
    if current_filename is not None:
        pages.append(_make_page(current_filename, content_lines, current_start, len(lines) - 1, page_format))

    return pages


def _make_page(filename: str, content_lines: list[str], start: int, end: int, page_format: str) -> Page:
    # Strip trailing --- separators
    while content_lines and content_lines[-1].strip() in ("---", ""):
        content_lines.pop()
    slug = filename.removesuffix(f".{page_format}")
    content = "\n".join(content_lines)
    return Page(slug=slug, filename=filename, content=content, line_start=start, line_end=end)


def find_page_by_slug(pages: list[Page], slug: str) -> Page | None:
    """Find a page by its slug (e.g. 'features/schema-explorer')."""
    for p in pages:
        if p.slug == slug:
            return p
    return None
