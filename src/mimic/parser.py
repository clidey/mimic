"""Parse documentation sources into individual Page objects."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from mimic.models import Page

# Matches lines like: # introduction.mdx  or  # features/schema-explorer.mdx
_PAGE_HEADER_TEMPLATE = r"^# (.+\.{ext})$"


def parse_pages(source: Path, page_format: str = "mdx") -> list[Page]:
    """Split a docs file into Page objects, one per header.

    The file is expected to have ``# filename.{page_format}`` headers
    separating individual pages.
    """
    return _parse_concatenated(source.read_text(), page_format)


def _parse_concatenated(text: str, page_format: str) -> list[Page]:
    """Parse text in concatenated format (``# filename.ext`` headers) into Pages."""
    header_re = re.compile(_PAGE_HEADER_TEMPLATE.format(ext=re.escape(page_format)))
    lines = text.splitlines()
    pages: list[Page] = []
    current_filename: str | None = None
    current_start: int = 0
    content_lines: list[str] = []

    for i, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            if current_filename is not None:
                pages.append(_make_page(current_filename, content_lines, current_start, i - 1, page_format))
            current_filename = m.group(1)
            current_start = i
            content_lines = []
        elif current_filename is not None:
            content_lines.append(line)

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


_DOC_EXTENSIONS = (".mdx", ".md")


def parse_pages_from_dir(source_dir: Path, page_format: str = "mdx") -> list[Page]:
    """Walk a directory tree and read individual doc files into Pages.

    Finds ``.mdx`` and ``.md`` files.  Each file becomes one Page with
    slug derived from its relative path minus the extension
    (e.g. ``features/schema-explorer``).
    """
    pages: list[Page] = []
    for filepath in sorted(source_dir.rglob("*")):
        if filepath.suffix not in _DOC_EXTENSIONS:
            continue
        rel = filepath.relative_to(source_dir)
        slug = str(rel)
        for ext in _DOC_EXTENSIONS:
            slug = slug.removesuffix(ext)
        content = filepath.read_text()
        lines = content.splitlines()
        pages.append(
            Page(
                slug=slug,
                filename=str(rel),
                content=content,
                line_start=0,
                line_end=max(len(lines) - 1, 0),
            )
        )
    return pages


def parse_pages_from_url(url: str, page_format: str = "mdx") -> list[Page]:
    """Fetch a remote concatenated file and parse it.

    The remote file uses the same ``# filename.{ext}`` header format
    as a local concatenated file.
    """
    with urllib.request.urlopen(url) as resp:  # noqa: S310
        text = resp.read().decode("utf-8")
    return _parse_concatenated(text, page_format)


def make_url_pages(docs_url: str, slugs: list[str]) -> list[Page]:
    """Create lightweight Page objects for URL-browse mode.

    Each page has no content — the LLM navigates to ``{docs_url}/{slug}``
    in the browser instead.
    """
    pages: list[Page] = []
    for slug in slugs:
        pages.append(
            Page(
                slug=slug,
                filename=slug,
                content="",
                line_start=0,
                line_end=0,
            )
        )
    return pages


def find_page_by_slug(pages: list[Page], slug: str) -> Page | None:
    """Find a page by its slug (e.g. 'features/schema-explorer')."""
    for p in pages:
        if p.slug == slug:
            return p
    return None
