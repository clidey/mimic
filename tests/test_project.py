"""Tests for docs_agent.project — YAML config loading and session resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_agent.models import SessionConfig
from docs_agent.project import (
    DocsMode,
    auto_group_sessions,
    load_project,
    resolve_session_globs,
)

# ---------------------------------------------------------------------------
# load_project
# ---------------------------------------------------------------------------

class TestLoadProject:
    def test_loads_minimal_config(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "getting-started.mdx").write_text("Hello.\n")

        (tmp_path / "qa-project.yaml").write_text(
            "name: test-project\n"
            "docs: docs/\n"
            "environment: |\n"
            "  - App at http://app:3000\n"
        )

        project = load_project(tmp_path)

        assert project.name == "test-project"
        assert project.docs_mode == DocsMode.DIRECTORY
        assert project.environment.strip() == "- App at http://app:3000"
        assert project.sessions is None  # auto-grouped

    def test_loads_file_mode(self, tmp_path: Path) -> None:
        (tmp_path / "llms.txt").write_text("# page.mdx\nContent.\n")
        (tmp_path / "qa-project.yaml").write_text(
            "name: file-test\ndocs: llms.txt\n"
        )

        project = load_project(tmp_path)

        assert project.docs_mode == DocsMode.FILE
        assert project.docs_source is not None
        assert project.docs_source.name == "llms.txt"

    def test_loads_url_mode(self, tmp_path: Path) -> None:
        (tmp_path / "qa-project.yaml").write_text(
            "name: url-test\ndocs: https://example.com/llms.txt\n"
        )

        project = load_project(tmp_path)

        assert project.docs_mode == DocsMode.URL
        assert project.docs_url == "https://example.com/llms.txt"

    def test_loads_browse_mode_with_sessions(self, tmp_path: Path) -> None:
        (tmp_path / "qa-project.yaml").write_text(
            "name: browse-test\n"
            "docs_url: https://docs.example.com\n"
            "sessions:\n"
            "  - name: Basics\n"
            "    pages: [install, quickstart]\n"
        )

        project = load_project(tmp_path)

        assert project.docs_mode == DocsMode.BROWSE
        assert project.docs_url == "https://docs.example.com"
        assert project.sessions is not None
        assert len(project.sessions) == 1

    def test_browse_mode_without_sessions_raises(self, tmp_path: Path) -> None:
        (tmp_path / "qa-project.yaml").write_text(
            "name: bad\ndocs_url: https://docs.example.com\n"
        )

        with pytest.raises(ValueError, match="sessions.*required"):
            load_project(tmp_path)

    def test_missing_docs_raises(self, tmp_path: Path) -> None:
        (tmp_path / "qa-project.yaml").write_text("name: bad\n")

        with pytest.raises(ValueError, match="at least one"):
            load_project(tmp_path)

    def test_detects_compose_file(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "page.mdx").write_text("Hi.\n")
        (tmp_path / "qa-project.yaml").write_text("name: test\ndocs: docs/\n")
        (tmp_path / "docker-compose.yml").write_text("services: {}\n")

        project = load_project(tmp_path)

        assert project.compose_file is not None
        assert project.compose_file.name == "docker-compose.yml"

    def test_parses_session_compose_profiles(self, tmp_path: Path) -> None:
        (tmp_path / "llms.txt").write_text("# a.mdx\nA\n# b.mdx\nB\n")
        (tmp_path / "qa-project.yaml").write_text(
            "name: profiles-test\n"
            "docs: llms.txt\n"
            "sessions:\n"
            "  - name: WithProfile\n"
            "    pages: [a, b]\n"
            "    compose_profiles: [extras, debug]\n"
        )

        project = load_project(tmp_path)

        assert project.sessions is not None
        assert project.sessions[0].compose_profiles == ["extras", "debug"]

    def test_nonexistent_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_project(Path("/nonexistent/path"))


# ---------------------------------------------------------------------------
# resolve_session_globs
# ---------------------------------------------------------------------------

class TestResolveSessionGlobs:
    def test_expands_glob(self) -> None:
        sessions = [SessionConfig(name="Features", page_slugs=["features/*"])]
        all_slugs = ["features/billing", "features/teams", "guides/setup"]

        resolved = resolve_session_globs(sessions, all_slugs)

        assert resolved[0].page_slugs == ["features/billing", "features/teams"]

    def test_literal_slugs_pass_through(self) -> None:
        sessions = [SessionConfig(name="Specific", page_slugs=["install", "config"])]
        all_slugs = ["install", "config", "other"]

        resolved = resolve_session_globs(sessions, all_slugs)

        assert resolved[0].page_slugs == ["install", "config"]

    def test_unmatched_glob_produces_empty(self) -> None:
        sessions = [SessionConfig(name="Empty", page_slugs=["nonexistent/*"])]

        resolved = resolve_session_globs(sessions, ["a", "b"])

        assert resolved[0].page_slugs == []

    def test_mixed_literal_and_glob(self) -> None:
        sessions = [SessionConfig(name="Mix", page_slugs=["install", "features/*"])]
        all_slugs = ["install", "features/a", "features/b"]

        resolved = resolve_session_globs(sessions, all_slugs)

        assert resolved[0].page_slugs == ["install", "features/a", "features/b"]


# ---------------------------------------------------------------------------
# auto_group_sessions
# ---------------------------------------------------------------------------

class TestAutoGroupSessions:
    def test_groups_by_prefix(self) -> None:
        slugs = ["features/a", "features/b", "guides/setup", "install"]

        sessions = auto_group_sessions(slugs)

        names = {s.name for s in sessions}
        assert "Features" in names
        assert "Guides" in names
        assert "General" in names  # root-level pages

    def test_root_pages_go_to_general(self) -> None:
        slugs = ["install", "quickstart"]

        sessions = auto_group_sessions(slugs)

        assert len(sessions) == 1
        assert sessions[0].name == "General"
        assert set(sessions[0].page_slugs) == {"install", "quickstart"}
