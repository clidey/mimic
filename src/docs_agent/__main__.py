"""CLI entry point: uv run docs-agent [options]."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="docs-agent",
        description="WhoDB documentation QA agent — tests doc pages via computer-use",
    )
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

    # Lazy imports so --list-pages/--list-sessions don't need anthropic key
    from docs_agent.orchestrator import list_pages, list_sessions, run_all, run_page, run_session

    if args.list_pages:
        list_pages()
    elif args.list_sessions:
        list_sessions()
    elif args.page:
        run_page(args.page)
    elif args.session:
        run_session(args.session)
    else:
        run_all()


if __name__ == "__main__":
    main()
