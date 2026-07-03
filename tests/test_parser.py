"""Tests for docs_agent.parser — doc file parsing into Page objects."""

from __future__ import annotations

import textwrap
from pathlib import Path

from docs_agent.parser import (
    find_page_by_slug,
    make_url_pages,
    parse_pages,
    parse_pages_from_dir,
)

# ---------------------------------------------------------------------------
# Concatenated file parsing
# ---------------------------------------------------------------------------


class TestParseConcatenated:
    def test_basic_two_pages(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            # intro.mdx
            Welcome to the app.
            This is the intro page.
            ---
            # setup.mdx
            ## Setup
            Run `docker compose up`.
        """)
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)

        assert len(pages) == 2
        assert pages[0].slug == "intro"
        assert pages[0].filename == "intro.mdx"
        assert "Welcome to the app" in pages[0].content
        assert pages[1].slug == "setup"
        assert "docker compose up" in pages[1].content

    def test_nested_slug(self, tmp_path: Path) -> None:
        content = "# features/schema-explorer.mdx\nExplore schemas here.\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)

        assert len(pages) == 1
        assert pages[0].slug == "features/schema-explorer"

    def test_strips_trailing_separators(self, tmp_path: Path) -> None:
        content = "# page.mdx\nContent here.\n---\n\n---\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)

        assert len(pages) == 1
        assert pages[0].content.strip() == "Content here."

    def test_empty_file_returns_no_pages(self, tmp_path: Path) -> None:
        doc_file = tmp_path / "empty.txt"
        doc_file.write_text("")

        pages = parse_pages(doc_file)

        assert pages == []

    def test_no_headers_returns_no_pages(self, tmp_path: Path) -> None:
        doc_file = tmp_path / "noheaders.txt"
        doc_file.write_text("Just some text without any page headers.\n")

        pages = parse_pages(doc_file)

        assert pages == []

    def test_custom_page_format(self, tmp_path: Path) -> None:
        content = "# readme.md\n# Hello\nWorld\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file, page_format="md")

        assert len(pages) == 1
        assert pages[0].slug == "readme"
        assert pages[0].filename == "readme.md"

    def test_line_numbers_tracked(self, tmp_path: Path) -> None:
        content = "# first.mdx\nLine A\n# second.mdx\nLine B\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)

        assert pages[0].line_start == 0
        assert pages[1].line_start == 2


# ---------------------------------------------------------------------------
# Directory parsing
# ---------------------------------------------------------------------------


class TestParseFromDir:
    def test_reads_mdx_files(self, tmp_path: Path) -> None:
        (tmp_path / "getting-started.mdx").write_text("Step 1: install.\n")
        (tmp_path / "advanced.mdx").write_text("Step 2: configure.\n")
        (tmp_path / "notes.txt").write_text("Ignored.\n")

        pages = parse_pages_from_dir(tmp_path)

        slugs = [p.slug for p in pages]
        assert "getting-started" in slugs
        assert "advanced" in slugs
        assert all("notes" not in s for s in slugs)

    def test_nested_directory_slugs(self, tmp_path: Path) -> None:
        sub = tmp_path / "features"
        sub.mkdir()
        (sub / "billing.mdx").write_text("Billing page.\n")

        pages = parse_pages_from_dir(tmp_path)

        assert len(pages) == 1
        assert pages[0].slug == "features/billing"

    def test_reads_md_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("Hello.\n")

        pages = parse_pages_from_dir(tmp_path)

        assert len(pages) == 1
        assert pages[0].slug == "readme"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestFindPageBySlug:
    def test_finds_existing(self, tmp_path: Path) -> None:
        content = "# target.mdx\nFound me.\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)
        result = find_page_by_slug(pages, "target")

        assert result is not None
        assert result.slug == "target"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        content = "# existing.mdx\nHere.\n"
        doc_file = tmp_path / "docs.txt"
        doc_file.write_text(content)

        pages = parse_pages(doc_file)
        result = find_page_by_slug(pages, "nonexistent")

        assert result is None


class TestMakeUrlPages:
    def test_creates_pages_with_empty_content(self) -> None:
        pages = make_url_pages("https://docs.example.com", ["install", "config"])

        assert len(pages) == 2
        assert pages[0].slug == "install"
        assert pages[0].content == ""
        assert pages[1].slug == "config"
