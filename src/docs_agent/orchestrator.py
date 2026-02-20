"""Orchestrate documentation QA sessions."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from docs_agent import docker_manager
from docs_agent.agent import test_page
from docs_agent.config import SESSIONS, find_session
from docs_agent.models import Page, PageResult, PageStatus, SessionConfig, SessionState
from docs_agent.parser import find_page_by_slug, parse_pages
from docs_agent.report import generate_report, slug_to_filename, status_subdir

log = logging.getLogger(__name__)


def run_all() -> list[PageResult]:
    """Run all sessions and generate a report."""
    pages = parse_pages()
    all_results: list[PageResult] = []
    all_recordings: dict[str, Path] = {}

    for session in SESSIONS:
        results, recordings = _run_session(session, pages)
        all_results.extend(results)
        all_recordings.update(recordings)

    run_dir = generate_report(all_results, run_name="full-run")
    _place_recordings(all_results, all_recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return all_results


def run_session(name: str) -> list[PageResult]:
    """Run a single session by name."""
    session = find_session(name)
    if session is None:
        raise ValueError(f"Unknown session: {name}")
    pages = parse_pages()
    results, recordings = _run_session(session, pages)
    run_dir = generate_report(results, run_name=session.name.lower().replace(" ", "-"))
    _place_recordings(results, recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return results


def run_page(slug: str) -> list[PageResult]:
    """Run a single page by slug."""
    pages = parse_pages()
    page = find_page_by_slug(pages, slug)
    if page is None:
        raise ValueError(f"Unknown page slug: {slug}")

    # Find which session this page belongs to, to set up correct infrastructure
    session = _find_session_for_slug(slug)
    if session is None or not session.needs_desktop:
        log.info("Page %s is informational — marking NOT_APPLICABLE", slug)
        result = PageResult(page=page, status=PageStatus.NOT_APPLICABLE, failure_reason="Informational page")
        run_dir = generate_report([result], run_name=slug.replace("/", "-"))
        log.info("Report written to %s", run_dir)
        return [result]

    state = SessionState()
    recordings: dict[str, Path] = {}
    try:
        _setup_infra(session)
        result = test_page(page, state)
        _save_recording(slug, recordings)
    except Exception as e:
        log.exception("Setup or test failed for %s", slug)
        result = PageResult(page=page, status=PageStatus.FAILED, failure_reason=f"Error: {type(e).__name__}: {e}")
    finally:
        docker_manager.stop_all()

    run_dir = generate_report([result], run_name=slug.replace("/", "-"))
    _place_recordings([result], recordings, run_dir)
    log.info("Report written to %s", run_dir)
    return [result]


def list_pages() -> None:
    """Print all parsed pages."""
    pages = parse_pages()
    print(f"Found {len(pages)} pages:\n")
    for i, p in enumerate(pages, 1):
        print(f"  {i:3d}. {p.slug}")


def list_sessions() -> None:
    """Print all session definitions."""
    print(f"Found {len(SESSIONS)} sessions:\n")
    for s in SESSIONS:
        flags = []
        if s.needs_desktop:
            flags.append("desktop")
        if s.needs_whodb:
            flags.append("whodb")
        if s.needs_postgres:
            flags.append("postgres")
        if s.needs_ollama:
            flags.append("ollama")
        flag_str = ", ".join(flags) if flags else "none"
        print(f"  {s.name} ({len(s.page_slugs)} pages) — infra: {flag_str}")
        for slug in s.page_slugs:
            print(f"    - {slug}")
        print()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _run_session(session: SessionConfig, pages: list[Page]) -> tuple[list[PageResult], dict[str, Path]]:
    """Run all pages in a session with shared infrastructure."""
    log.info("=== Session: %s (%d pages) ===", session.name, len(session.page_slugs))
    results: list[PageResult] = []
    recordings: dict[str, Path] = {}

    # Informational sessions need no Docker
    if not session.needs_desktop:
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page:
                results.append(PageResult(page=page, status=PageStatus.NOT_APPLICABLE, failure_reason="Informational page"))
        return results, recordings

    # Setup infrastructure
    try:
        _setup_infra(session)
    except Exception as e:
        log.error("Infrastructure setup failed for session %s: %s", session.name, e)
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page:
                results.append(PageResult(
                    page=page,
                    status=PageStatus.FAILED,
                    failure_reason=f"Session setup failed: {e}",
                ))
        return results, recordings

    # Test each page
    state = SessionState()
    try:
        for slug in session.page_slugs:
            page = find_page_by_slug(pages, slug)
            if page is None:
                log.warning("Page %s not found in llms.txt — skipping", slug)
                continue

            try:
                result = test_page(page, state)
                _save_recording(slug, recordings)
            except Exception as e:
                log.exception("Page %s failed with exception", slug)
                result = PageResult(page=page, status=PageStatus.FAILED, failure_reason=f"{type(e).__name__}: {e}")

            results.append(result)
            if result.status == PageStatus.FAILED and result.failure_reason:
                state.record_failure(slug, result.failure_reason)
    finally:
        docker_manager.stop_all()

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


def _setup_infra(session: SessionConfig) -> None:
    """Start the Docker containers needed for a session."""
    # Clean up any stale resources from a previous interrupted run
    docker_manager.stop_all()
    docker_manager.create_network()
    if session.needs_desktop:
        docker_manager.start_desktop()
    if session.needs_postgres:
        docker_manager.start_postgres()
    if session.needs_whodb:
        docker_manager.start_whodb()
    if session.needs_ollama:
        docker_manager.start_ollama()


def _find_session_for_slug(slug: str) -> SessionConfig | None:
    """Find which session contains a given page slug."""
    for s in SESSIONS:
        if slug in s.page_slugs:
            return s
    return None
