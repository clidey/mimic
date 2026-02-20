#!/usr/bin/env python3
"""Launch docs-agent on a GCP spot VM.

Usage:
    python run_on_gcp.py              # launch and exit
    python run_on_gcp.py --wait       # launch, poll, download results when done
    python run_on_gcp.py --cleanup    # delete the VM if it's still running
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path

# docs-agent root: two levels up from src/docs_agent/gcp.py
AGENT_ROOT = Path(__file__).resolve().parent.parent.parent
VM_NAME = "docsagent-runner"


# ---------------------------------------------------------------------------
# .env parser
# ---------------------------------------------------------------------------

def load_env(path: Path = AGENT_ROOT / ".env") -> dict[str, str]:
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
    val = env.get(key, "")
    if not val:
        print(f"Error: {key} is required in .env")
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# gcloud helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def gcloud_ok() -> bool:
    r = run(["gcloud", "version"], check=False, capture=True)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Startup script (runs on the VM)
# ---------------------------------------------------------------------------

def build_startup_script(env: dict[str, str]) -> str:
    api_key = require(env, "ANTHROPIC_API_KEY")
    bucket = require(env, "GCS_BUCKET")
    agent_args = env.get("DOCS_AGENT_ARGS", "")

    return f"""\
#!/bin/bash
exec > /var/log/docsagent.log 2>&1
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

# Always upload logs and shut down, even on failure
cleanup() {{
    echo "=== Uploading logs $(date) ==="
    gsutil cp /var/log/docsagent.log gs://{bucket}/results/$TIMESTAMP/runner.log || true
    echo "=== Shutting down VM ==="
    shutdown -h now
}}
trap cleanup EXIT

echo "=== docs-agent startup $(date) ==="

# Install Docker
apt-get update -qq
apt-get install -y -qq docker.io containerd curl
systemctl start docker
systemctl enable docker

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source /root/.local/bin/env

# Download the agent code from GCS
mkdir -p /opt/docsagent
gsutil cp gs://{bucket}/docsagent-code.tar.gz /opt/docsagent/code.tar.gz
cd /opt/docsagent
tar xzf code.tar.gz

# Install dependencies
cd /opt/docsagent/docs-agent
uv sync

# Run the agent
export ANTHROPIC_API_KEY="{api_key}"
echo "=== Starting docs-agent $(date) ==="
uv run docs-agent {agent_args} || true
echo "=== docs-agent finished $(date) ==="

# Upload results to GCS
if [ -d reports ]; then
    gsutil -m cp -r reports/ gs://{bucket}/results/$TIMESTAMP/
    echo "Results uploaded to gs://{bucket}/results/$TIMESTAMP/"
fi
"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_launch(env: dict[str, str]) -> None:
    project = require(env, "GCP_PROJECT")
    zone = env.get("GCP_ZONE", "us-central1-a")
    machine = env.get("GCP_MACHINE_TYPE", "e2-standard-4")
    disk_size = env.get("GCP_DISK_SIZE", "50")
    bucket = require(env, "GCS_BUCKET")
    spot = env.get("GCP_SPOT", "true").lower() == "true"

    if not gcloud_ok():
        print("Error: gcloud CLI not found. Install it: https://cloud.google.com/sdk/docs/install")
        sys.exit(1)

    # Clean up any existing VM from a previous run
    run(["gcloud", "compute", "instances", "delete", VM_NAME,
         "--project", project, "--zone", zone, "--quiet"], check=False)

    # Package the docs-agent code
    print("\n1. Packaging docs-agent code...")
    tar_path = Path(tempfile.mktemp(suffix=".tar.gz"))
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(str(AGENT_ROOT), arcname="docs-agent")
    print(f"   Archive: {tar_path} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Upload to GCS
    print(f"\n2. Uploading to gs://{bucket}/docsagent-code.tar.gz...")
    run(["gsutil", "cp", str(tar_path), f"gs://{bucket}/docsagent-code.tar.gz"])
    tar_path.unlink()

    # Write startup script to temp file
    print("\n3. Creating startup script...")
    startup = build_startup_script(env)
    startup_path = Path(tempfile.mktemp(suffix=".sh"))
    startup_path.write_text(startup)

    # Create the VM
    print(f"\n4. Creating VM '{VM_NAME}' ({machine}, zone={zone})...")
    cmd = [
        "gcloud", "compute", "instances", "create", VM_NAME,
        "--project", project,
        "--zone", zone,
        "--machine-type", machine,
        "--boot-disk-size", f"{disk_size}GB",
        "--image-family", "ubuntu-2204-lts",
        "--image-project", "ubuntu-os-cloud",
        "--metadata-from-file", f"startup-script={startup_path}",
        "--scopes", "storage-full",
        "--no-restart-on-failure",
    ]
    if spot:
        cmd.append("--provisioning-model=SPOT")
        cmd.append("--instance-termination-action=DELETE")

    run(cmd)
    startup_path.unlink()

    print(f"""
Done! The VM is booting and will:
  1. Install Docker + uv
  2. Run docs-agent
  3. Upload results to gs://{bucket}/results/<timestamp>/
  4. Shut itself down

Monitor:
  gcloud compute ssh {VM_NAME} --zone {zone} --project {project} -- tail -f /var/log/docsagent.log
  gsutil ls gs://{bucket}/results/

Download results when done:
  gsutil -m cp -r gs://{bucket}/results/<timestamp>/ ./results/
""")


def cmd_wait(env: dict[str, str]) -> None:
    project = require(env, "GCP_PROJECT")
    zone = env.get("GCP_ZONE", "us-central1-a")
    bucket = require(env, "GCS_BUCKET")

    print(f"Waiting for VM '{VM_NAME}' to finish...")
    while True:
        # Check if VM still exists
        r = run(
            ["gcloud", "compute", "instances", "describe", VM_NAME,
             "--project", project, "--zone", zone, "--format", "value(status)"],
            check=False, capture=True,
        )
        if r.returncode != 0:
            print("VM no longer exists — it shut itself down. Checking results...")
            break
        status = r.stdout.strip()
        if status == "TERMINATED":
            print("VM terminated. Checking results...")
            break
        print(f"  VM status: {status} — waiting 30s...")
        time.sleep(30)

    # Find latest results
    r = run(["gsutil", "ls", f"gs://{bucket}/results/"], check=False, capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        print("No results found in GCS bucket.")
        return

    dirs = sorted(r.stdout.strip().splitlines())
    latest = dirs[-1]
    print(f"\nLatest results: {latest}")

    # Download
    local_dir = AGENT_ROOT / "reports" / "gcp-latest"
    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to {local_dir}...")
    run(["gsutil", "-m", "cp", "-r", f"{latest}*", str(local_dir)])
    print(f"\nResults downloaded to {local_dir}")


def cmd_cleanup(env: dict[str, str]) -> None:
    project = require(env, "GCP_PROJECT")
    zone = env.get("GCP_ZONE", "us-central1-a")
    print(f"Deleting VM '{VM_NAME}'...")
    run(["gcloud", "compute", "instances", "delete", VM_NAME,
         "--project", project, "--zone", zone, "--quiet"], check=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run docs-agent on a GCP spot VM")
    parser.add_argument("--wait", action="store_true", help="Poll until done, then download results")
    parser.add_argument("--cleanup", action="store_true", help="Delete the VM if still running")
    parser.add_argument("--env", default=str(AGENT_ROOT / ".env"), help="Path to .env file")
    args = parser.parse_args()

    env = load_env(Path(args.env))

    if args.cleanup:
        cmd_cleanup(env)
    elif args.wait:
        cmd_launch(env)
        cmd_wait(env)
    else:
        cmd_launch(env)


if __name__ == "__main__":
    main()
