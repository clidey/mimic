"""Shared utilities for cloud runner modules (gcp.py, aws.py)."""

from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# Shared startup script template for cloud VMs
# ---------------------------------------------------------------------------


def build_startup_script(
    *,
    provider: str,
    key_export: str,
    agent_args: str,
    upload_logs_cmd: str,
    download_code_cmd: str,
    upload_results_cmd: str,
    extra_packages: str = "",
    pre_env_lines: str = "",
) -> str:
    """Build the bash startup script that runs on cloud VMs.

    Cloud-specific parts (storage commands, credentials) are injected via
    parameters.  Everything else — Docker install, uv install, agent run —
    is shared.
    """
    return f"""\
#!/bin/bash
exec > /var/log/docsagent.log 2>&1
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

{pre_env_lines}

# Always upload logs and shut down, even on failure
cleanup() {{
    echo "=== Uploading logs $(date) ==="
    {upload_logs_cmd}
    echo "=== Shutting down ==="
    shutdown -h now
}}
trap cleanup EXIT

echo "=== docs-agent startup $(date) ==="

# Install Docker
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 containerd curl{" " + extra_packages if extra_packages else ""}
systemctl start docker
systemctl enable docker

# Wait for Docker daemon to be fully ready
echo "Waiting for Docker daemon..."
for i in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
        echo "Docker is ready."
        break
    fi
    echo "  attempt $i/30 — not ready, waiting 2s..."
    sleep 2
done

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source /root/.local/bin/env

# Download the agent code
mkdir -p /opt/docsagent
{download_code_cmd}
cd /opt/docsagent
tar xzf code.tar.gz

# Install dependencies
cd /opt/docsagent/docs-agent
uv sync

# Run the agent
export AGENT_PROVIDER="{provider}"
{key_export}
echo "=== Starting docs-agent $(date) ==="
uv run docs-agent {agent_args} || true
echo "=== docs-agent finished $(date) ==="

# Upload results
if [ -d reports ]; then
    {upload_results_cmd}
fi
"""
