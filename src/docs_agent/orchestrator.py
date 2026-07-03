"""Orchestrate documentation QA sessions."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from docs_agent import docker_manager
from docs_agent.agent import test_page
from docs_agent.models import Page, PageResult, PageStatus, SessionConfig, SessionState
from docs_agent.parser import find_page_by_slug, make_url_pages, parse_pages, parse_pages_from_dir, parse_pages_from_url
from docs_agent.project import DocsMode, ProjectConfig, auto_group_sessions, resolve_session_globs
from docs_agent.report import generate_report, slug_to_filename, status_subdir

log = logging.getLogger(__name__)


def run_all(project: ProjectConfig) -> list[PageResult]:
    """Run all sessions and generate a report."""
    pages = _load_pages(project)
    sessions = _get_sessions(project, pages)
    all_results: list[PageResult] = []
    all_recordings: dict[str, Path] = {}

    for session in sessions:
        results, recordings = _run_session(session, pages, project)
        all_results.extend(results)
        all_recordings.update(recordings)

    run_dir = generate_report(all_results, run_name="full-run")
    _place_recordings(all_results, all_recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return all_results


def run_session(name: str, project: ProjectConfig) -> list[PageResult]:
    """Run a single session by name."""
    pages = _load_pages(project)
    sessions = _get_sessions(project, pages)
    session = _find_session(sessions, name)
    if session is None:
        raise ValueError(f"Unknown session: {name}")
    results, recordings = _run_session(session, pages, project)
    run_dir = generate_report(results, run_name=session.name.lower().replace(" ", "-"))
    _place_recordings(results, recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return results


def run_page(slug: str, project: ProjectConfig) -> list[PageResult]:
    """Run a single page by slug."""
    pages = _load_pages(project)
    page = find_page_by_slug(pages, slug)
    if page is None:
        raise ValueError(f"Unknown page slug: {slug}")

    # Find which session this page belongs to, to determine compose profiles
    sessions = _get_sessions(project, pages)
    session = _find_session_for_slug(sessions, slug)
    if session is None or not session.needs_desktop:
        log.info("Page %s is informational — marking NOT_APPLICABLE", slug)
        result = PageResult(page=page, status=PageStatus.NOT_APPLICABLE, failure_reason="Informational page")
        run_dir = generate_report([result], run_name=slug.replace("/", "-"))
        log.info("Report written to %s", run_dir)
        return [result]

    state = SessionState()
    recordings: dict[str, Path] = {}
    try:
        _setup_infra(session, project)
        result = test_page(page, state, project.environment, docs_url=project.docs_url)
        _save_recording(slug, recordings)
    except Exception as e:
        log.exception("Setup or test failed for %s", slug)
        result = PageResult(page=page, status=PageStatus.FAILED, failure_reason=f"Error: {type(e).__name__}: {e}")
    finally:
        docker_manager.stop_all(project.compose_file)

    run_dir = generate_report([result], run_name=slug.replace("/", "-"))
    _place_recordings([result], recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return [result]


def list_pages(project: ProjectConfig) -> None:
    """Print all parsed pages."""
    pages = _load_pages(project)
    print(f"Found {len(pages)} pages:\n")
    for i, p in enumerate(pages, 1):
        print(f"  {i:3d}. {p.slug}")


def list_sessions(project: ProjectConfig) -> None:
    """Print all session definitions."""
    pages = _load_pages(project)
    sessions = _get_sessions(project, pages)
    print(f"Found {len(sessions)} sessions:\n")
    for s in sessions:
        flags = []
        if s.needs_desktop:
            flags.append("desktop")
        if s.compose_profiles:
            flags.append(f"profiles: {','.join(s.compose_profiles)}")
        flag_str = ", ".join(flags) if flags else "none"
        print(f"  {s.name} ({len(s.page_slugs)} pages) — infra: {flag_str}")
        for slug in s.page_slugs:
            print(f"    - {slug}")
        print()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _load_pages(project: ProjectConfig) -> list[Page]:
    """Load pages from the project's docs source based on its mode.

    Each branch is guarded by docs_mode, which guarantees the corresponding
    field is non-None (enforced by load_project validation).
    """
    mode = project.docs_mode
    if mode == DocsMode.FILE:
        assert project.docs_source is not None
        return parse_pages(project.docs_source)
    if mode == DocsMode.DIRECTORY:
        assert project.docs_source is not None
        return parse_pages_from_dir(project.docs_source)
    if mode == DocsMode.URL:
        assert project.docs_url is not None
        return parse_pages_from_url(project.docs_url)
    if mode == DocsMode.BROWSE:
        assert project.sessions is not None and project.docs_url is not None
        all_slugs: list[str] = []
        for s in project.sessions:
            all_slugs.extend(s.page_slugs)
        return make_url_pages(project.docs_url, all_slugs)
    raise ValueError(f"Unknown docs mode: {mode}")


def _get_sessions(project: ProjectConfig, pages: list[Page]) -> list[SessionConfig]:
    """Return resolved sessions — from YAML config or auto-grouped."""
    if project.sessions is not None:
        all_slugs = [p.slug for p in pages]
        return resolve_session_globs(project.sessions, all_slugs)
    return auto_group_sessions([p.slug for p in pages])


def _find_session(sessions: list[SessionConfig], name: str) -> SessionConfig | None:
    """Find a session by name (case-insensitive)."""
    lower = name.lower()
    for s in sessions:
        if s.name.lower() == lower:
            return s
    return None


def _find_session_for_slug(sessions: list[SessionConfig], slug: str) -> SessionConfig | None:
    """Find which session contains a given page slug."""
    for s in sessions:
        if slug in s.page_slugs:
            return s
    return None


def _run_session(
    session: SessionConfig, pages: list[Page], project: ProjectConfig
) -> tuple[list[PageResult], dict[str, Path]]:
    """Run all pages in a session with shared infrastructure."""
    log.info("=== Session: %s (%d pages) ===", session.name, len(session.page_slugs))
    results: list[PageResult] = []
    recordings: dict[str, Path] = {}

    # Informational sessions need no Docker
    if not session.needs_desktop:
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page:
                results.append(
                    PageResult(page=page, status=PageStatus.NOT_APPLICABLE, failure_reason="Informational page")
                )
        return results, recordings

    # Setup infrastructure
    try:
        _setup_infra(session, project)
    except Exception as e:
        log.error("Infrastructure setup failed for session %s: %s", session.name, e)
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page:
                results.append(
                    PageResult(
                        page=page,
                        status=PageStatus.FAILED,
                        failure_reason=f"Session setup failed: {e}",
                    )
                )
        return results, recordings

    # Test each page
    state = SessionState()
    try:
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page is None:
                log.warning("Page %s not found in docs — skipping", slug)
                continue

            try:
                result = test_page(page, state, project.environment, docs_url=project.docs_url)
                _save_recording(slug, recordings)
            except Exception as e:
                log.exception("Page %s failed with exception", slug)
                result = PageResult(page=page, status=PageStatus.FAILED, failure_reason=f"{type(e).__name__}: {e}")

            results.append(result)
            if result.status == PageStatus.FAILED and result.failure_reason:
                state.record_failure(slug, result.failure_reason)
    finally:
        docker_manager.stop_all(project.compose_file)

    return results, recordings


def _save_recording(slug: str, recordings: dict[str, Path]) -> None:
    """Copy the current recording from the container to a temp file."""
    tmp = Path(tempfile.mktemp(suffix=".mp4"))
    if docker_manager.copy_recording(tmp):
        recordings[slug] = tmp


def _place_recordings(results: list[PageResult], recordings: dict[str, Path], run_dir: Path) -> None:
    """Move recordings from temp files into the report directory."""
    for r in results:
        slug = r.page.slug
        if slug not in recordings:
            continue
        tmp_path = recordings[slug]
        if not tmp_path.exists():
            continue
        dest_dir = run_dir / status_subdir(r)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{slug_to_filename(slug)}.mp4"
        tmp_path.rename(dest)
        log.info("Recording placed at %s", dest)


def _setup_infra(session: SessionConfig, project: ProjectConfig) -> None:
    """Start infrastructure for a session: compose services + desktop sandbox."""
    # Clean up any stale resources from a previous interrupted run
    docker_manager.stop_all(project.compose_file)
    docker_manager.create_network()

    # Bring up app services via docker compose (if a compose file exists)
    if project.compose_file is not None:
        docker_manager.compose_up(project.compose_file, session.compose_profiles)

    # Always start the desktop sandbox
    if session.needs_desktop:
        docker_manager.start_desktop()
        # Pre-launch Firefox + terminal for CUA models that struggle with app discovery
        import os

        if os.environ.get("AGENT_PROVIDER", "anthropic").lower() == "openai":
            docker_manager.prepare_desktop()
