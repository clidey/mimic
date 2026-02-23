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


def package_agent_code() -> Path:
    """Package the docs-agent repo into a temporary .tar.gz and return its path.

    Caller is responsible for deleting the file after use.
    """
    fd, tmp = tempfile.mkstemp(suffix=".tar.gz")
    # mkstemp opens an fd we don't need — close it, tarfile will reopen by path
    import os
    os.close(fd)
    tar_path = Path(tmp)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(str(AGENT_ROOT), arcname="docs-agent")
    print(f"   Archive: {tar_path} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return tar_path
