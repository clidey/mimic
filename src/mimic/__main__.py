"""CLI entry point: uv run mimic [options]."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Template strings for `mimic init`
# ---------------------------------------------------------------------------

_TEMPLATE_QA_PROJECT = """\
name: {name}

# Where to find documentation pages.
# Can be a directory of .mdx files, a single concatenated file, or a URL.
docs: docs/

# Free-text injected into the LLM system prompt.
# Describe what's running and how to reach it (use Docker hostnames, not localhost).
environment: |
  - My app is running at http://myapp:3000

# Sessions group pages and control infrastructure.
# Omit to auto-group pages by directory prefix.
# sessions:
#   - name: Getting Started
#     pages: [getting-started, quickstart]
#   - name: Advanced
#     pages: [features/*]
#     compose_profiles: [extras]
"""

_TEMPLATE_COMPOSE = """\
services:
  # Add your app services here. Example:
  # myapp:
  #   image: myorg/myapp:latest
  #   networks: [mimic-net]
  {}

networks:
  mimic-net:
    name: mimic-net
    external: true   # agent creates this network; compose joins it
"""

_TEMPLATE_DOCS_PAGE = """\
## Getting Started

1. Open Firefox and navigate to http://myapp:3000
2. Verify the home page loads successfully.
3. Check that the page title is displayed.
"""


def _init_project(target: Path) -> None:
    """Scaffold a new mimic project directory."""
    if target.exists() and any(target.iterdir()):
        print(f"Error: '{target}' already exists and is not empty.", file=sys.stderr)
        sys.exit(1)

    docs_dir = target / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    (target / "qa-project.yaml").write_text(_TEMPLATE_QA_PROJECT.format(name=target.name))
    (target / "docker-compose.yml").write_text(_TEMPLATE_COMPOSE)
    (docs_dir / "getting-started.mdx").write_text(_TEMPLATE_DOCS_PAGE)

    print(f"Created project at {target}/\n")
    print("Next steps:")
    print("  1. Edit qa-project.yaml  — set your app's name and environment")
    print("  2. Edit docker-compose.yml — add your app's services")
    print("  3. Add your docs to docs/ (one .mdx file per page)")
    print(f"  4. uv run mimic --project {target} --list-pages")


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Load .env into os.environ (no-op if file missing or vars already set)."""
    from mimic.runner_utils import AGENT_ROOT

    env_path = AGENT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key not in os.environ:  # don't override explicit env vars
            os.environ[key] = value


def main() -> None:
    _load_dotenv()

    # Handle `mimic init <name>` before argparse
    args_raw = sys.argv[1:]
    if args_raw and args_raw[0] == "init":
        if len(args_raw) < 2:
            print("Usage: mimic init <project-name>", file=sys.stderr)
            sys.exit(1)
        _init_project(Path(args_raw[1]))
        return

    parser = argparse.ArgumentParser(
        prog="mimic",
        description="Documentation QA agent — tests doc pages via computer-use",
    )
    parser.add_argument("--project", metavar="PATH", help="Path to qa-project.yaml or directory containing it")
    parser.add_argument("--page", metavar="SLUG", help="Test a single page by slug (e.g. 'installation')")
    parser.add_argument("--session", metavar="NAME", help="Run a single session by name")
    parser.add_argument("--list-pages", action="store_true", help="List all parsed pages")
    parser.add_argument("--list-sessions", action="store_true", help="List all session definitions")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--json-log", action="store_true", help="Output logs in JSON format")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    if args.json_log:
        import json as _json

        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return _json.dumps(
                    {
                        "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                )

        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.root.addHandler(handler)
        logging.root.setLevel(level)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )

    # Load project config
    from mimic.project import load_project

    project_path = Path(args.project) if args.project else None
    try:
        project = load_project(project_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    logging.getLogger(__name__).info("Loaded project '%s' from %s", project.name, project.project_dir)

    # Lazy imports so --list-pages/--list-sessions don't need anthropic key
    from mimic.orchestrator import list_pages, list_sessions, run_all, run_page, run_session

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
