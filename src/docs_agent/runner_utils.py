"""Shared utilities for cloud runner modules (gcp.py, aws.py)."""

from __future__ import annotations

import sys
import tarfile
import tempfile
from pathlib import Path

# docs-agent root: two levels up from src/docs_agent/
AGENT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_env(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file into a dict, ignoring comments and blank lines."""
    if path is None:
        path = AGENT_ROOT / ".env"
    if not path.exists():
        print(f"Error: {path} not found. Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def require(env: dict[str, str], key: str) -> str:
    """Get a required env var, exiting with an error if missing."""
    val = env.get(key, "")
    if not val:
        print(f"Error: {key} is required in .env")
        sys.exit(1)
    return val


_EXCLUDE_DIRS = {"reports", ".venv", "__pycache__", ".git", "node_modules"}


def package_agent_code() -> Path:
    """Package the docs-agent repo into a temporary .tar.gz and return its path.

    Excludes reports/, .venv/, .git/, and other non-essential directories
    to keep the archive small. Caller is responsible for deleting the file.
    """
    fd, tmp = tempfile.mkstemp(suffix=".tar.gz")
    import os
    os.close(fd)
    tar_path = Path(tmp)

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        # parts[0] is the arcname "docs-agent", skip it for matching
        if len(parts) > 1 and parts[1] in _EXCLUDE_DIRS:
            return None
        return info

    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(str(AGENT_ROOT), arcname="docs-agent", filter=_filter)
    print(f"   Archive: {tar_path} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return tar_path
