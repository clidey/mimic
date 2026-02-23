"""CLI entry point: uv run docs-agent [options]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="docs-agent",
        description="Documentation QA agent — tests doc pages via computer-use",
    )
    parser.add_argument("--project", metavar="PATH", help="Path to qa-project.yaml or directory containing it")
    parser.add_argument("--page", metavar="SLUG", help="Test a single page by slug (e.g. 'installation')")
    parser.add_argument("--session", metavar="NAME", help="Run a single session by name")
    parser.add_argument("--list-pages", action="store_true", help="List all parsed pages")
    parser.add_argument("--list-sessions", action="store_true", help="List all session definitions")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load project config
    from docs_agent.project import load_project

    project_path = Path(args.project) if args.project else None
    try:
        project = load_project(project_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    logging.getLogger(__name__).info("Loaded project '%s' from %s", project.name, project.project_dir)

    # Lazy imports so --list-pages/--list-sessions don't need anthropic key
    from docs_agent.orchestrator import list_pages, list_sessions, run_all, run_page, run_session

    if args.list_pages:
        list_pages(project)
    elif args.list_sessions:
        list_sessions(project)
    elif args.page:
        run_page(args.page, project)
    elif args.session:
        run_session(args.session, project)
    else:
        run_all(project)


if __name__ == "__main__":
    main()
