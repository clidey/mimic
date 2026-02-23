"""Load and validate qa-project.yaml project configuration."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from docs_agent.models import SessionConfig

log = logging.getLogger(__name__)

PROJECT_FILENAMES = ("qa-project.yaml", "qa-project.yml")


@dataclass
class ProjectConfig:
    name: str
    docs_source: Path
    environment: str
    sessions: list[SessionConfig] | None  # None = auto-group by directory prefix
    project_dir: Path
    compose_file: Path | None


def load_project(path: Path | None = None) -> ProjectConfig:
    """Load qa-project.yaml.

    If *path* points to a file, load it directly.
    If *path* points to a directory, look for qa-project.yaml inside it.
    If *path* is None, search cwd then parent directories.
    """
    yaml_path = _resolve_yaml_path(path)
    project_dir = yaml_path.parent

    raw = yaml.safe_load(yaml_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{yaml_path} must contain a YAML mapping")

    name = raw.get("name", project_dir.name)
    docs_rel = raw.get("docs")
    if not docs_rel:
        raise ValueError(f"{yaml_path}: 'docs' field is required")

    docs_source = (project_dir / docs_rel).resolve()
    if not docs_source.exists():
        raise FileNotFoundError(f"Docs file not found: {docs_source}")

    environment = raw.get("environment", "")

    # Detect compose file
    compose_file = _find_compose_file(project_dir)

    # Parse sessions (may be None for auto-grouping)
    raw_sessions = raw.get("sessions")
    sessions: list[SessionConfig] | None = None
    if raw_sessions is not None:
        sessions = [_parse_session(s) for s in raw_sessions]

    return ProjectConfig(
        name=name,
        docs_source=docs_source,
        environment=environment,
        sessions=sessions,
        project_dir=project_dir,
        compose_file=compose_file,
    )


def resolve_session_globs(
    sessions: list[SessionConfig], all_slugs: list[str]
) -> list[SessionConfig]:
    """Expand glob patterns (e.g. 'ai/*') in session page_slugs against parsed page slugs."""
    resolved = []
    for session in sessions:
        expanded: list[str] = []
        for pattern in session.page_slugs:
            if "*" in pattern or "?" in pattern:
                matches = [s for s in all_slugs if fnmatch.fnmatch(s, pattern)]
                if not matches:
                    log.warning("Session '%s': glob '%s' matched no pages", session.name, pattern)
                expanded.extend(matches)
            else:
                expanded.append(pattern)
        resolved.append(SessionConfig(
            name=session.name,
            page_slugs=expanded,
            needs_desktop=session.needs_desktop,
            compose_profiles=session.compose_profiles,
        ))
    return resolved


def auto_group_sessions(slugs: list[str]) -> list[SessionConfig]:
    """Group page slugs by top-level directory prefix into sessions."""
    groups: dict[str, list[str]] = {}
    for slug in slugs:
        prefix = slug.split("/")[0] if "/" in slug else "_root"
        groups.setdefault(prefix, []).append(slug)

    sessions = []
    for prefix, page_slugs in groups.items():
        name = prefix.replace("-", " ").replace("_", " ").title()
        if prefix == "_root":
            name = "General"
        sessions.append(SessionConfig(name=name, page_slugs=page_slugs))
    return sessions


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _resolve_yaml_path(path: Path | None) -> Path:
    if path is not None:
        p = Path(path).resolve()
        if p.is_file():
            return p
        if p.is_dir():
            for name in PROJECT_FILENAMES:
                candidate = p / name
                if candidate.exists():
                    return candidate
            raise FileNotFoundError(
                f"No project file found in {p}. "
                f"Expected one of: {', '.join(PROJECT_FILENAMES)}"
            )
        raise FileNotFoundError(f"Path does not exist: {p}")

    # Search cwd then parents
    cwd = Path.cwd().resolve()
    for d in [cwd, *cwd.parents]:
        for name in PROJECT_FILENAMES:
            candidate = d / name
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        f"No project file found in {cwd} or any parent directory. "
        f"Expected one of: {', '.join(PROJECT_FILENAMES)}. "
        "Use --project to specify the path explicitly."
    )


def _find_compose_file(project_dir: Path) -> Path | None:
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        candidate = project_dir / name
        if candidate.exists():
            return candidate
    return None


def _parse_session(raw: dict) -> SessionConfig:
    name = raw.get("name", "Unnamed")
    pages = raw.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError(f"Session '{name}': 'pages' must be a list")
    needs_desktop = raw.get("needs_desktop", True)
    compose_profiles = raw.get("compose_profiles", [])
    if not isinstance(compose_profiles, list):
        compose_profiles = [compose_profiles]
    return SessionConfig(
        name=name,
        page_slugs=pages,
        needs_desktop=needs_desktop,
        compose_profiles=compose_profiles,
    )
