#!/usr/bin/env python3
"""Launch mimic on a GCP spot VM.

Usage:
    mimic-gcp              # launch and exit
    mimic-gcp --wait       # launch, poll, download results when done
    mimic-gcp --cleanup    # delete the VM if it's still running
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mimic.runner_utils import AGENT_ROOT, build_startup_script, package_agent_code, require

VM_NAME = "mimic-runner"


# ---------------------------------------------------------------------------
# gcloud helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def gcloud_ok() -> bool:
    r = run(["gcloud", "version"], check=False, capture=True)
    return r.returncode == 0


def vm_exists(project: str, zone: str) -> bool:
    """Check whether our VM currently exists (any state)."""
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            VM_NAME,
            "--project",
            project,
            "--zone",
            zone,
            "--format",
            "value(status)",
        ],
        check=False,
        capture=True,
    )
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Startup script (runs on the VM)
# ---------------------------------------------------------------------------


def _build_startup_script(env: dict[str, str]) -> str:
    provider = env.get("AGENT_PROVIDER", "anthropic")
    bucket = require(env, "GCS_BUCKET")
    agent_args = env.get("MIMIC_ARGS", "")

    if provider == "openai":
        api_key = require(env, "OPENAI_API_KEY")
        key_export = f'export OPENAI_API_KEY="{api_key}"'
    else:
        api_key = require(env, "ANTHROPIC_API_KEY")
        key_export = f'export ANTHROPIC_API_KEY="{api_key}"'

    return build_startup_script(
        provider=provider,
        key_export=key_export,
        agent_args=agent_args,
        upload_logs_cmd=f"gsutil cp /var/log/mimic.log gs://{bucket}/results/$TIMESTAMP/runner.log || true",
        download_code_cmd=f"gsutil cp gs://{bucket}/mimic-code.tar.gz /opt/mimic/code.tar.gz",
        upload_results_cmd=(
            f"gsutil -m cp -r reports/ gs://{bucket}/results/$TIMESTAMP/\n"
            f'    echo "$TIMESTAMP" | gsutil cp - gs://{bucket}/latest.txt\n'
            f'    echo "Results uploaded to gs://{bucket}/results/$TIMESTAMP/"'
        ),
    )


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
    if vm_exists(project, zone):
        print(f"Deleting existing VM '{VM_NAME}'...")
        run(
            ["gcloud", "compute", "instances", "delete", VM_NAME, "--project", project, "--zone", zone, "--quiet"],
            check=False,
        )

    # Package the mimic code
    print("\n1. Packaging mimic code...")
    tar_path = package_agent_code()

    # Upload to GCS
    print(f"\n2. Uploading to gs://{bucket}/mimic-code.tar.gz...")
    run(["gsutil", "cp", str(tar_path), f"gs://{bucket}/mimic-code.tar.gz"])
    tar_path.unlink()

    # Write startup script to temp file
    print("\n3. Creating startup script...")
    startup = _build_startup_script(env)
    fd, tmp = tempfile.mkstemp(suffix=".sh")
    import os

    os.close(fd)
    startup_path = Path(tmp)
    startup_path.write_text(startup)

    # Create the VM
    print(f"\n4. Creating VM '{VM_NAME}' ({machine}, zone={zone})...")
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "create",
        VM_NAME,
        "--project",
        project,
        "--zone",
        zone,
        "--machine-type",
        machine,
        "--boot-disk-size",
        f"{disk_size}GB",
        "--image-family",
        "ubuntu-2204-lts",
        "--image-project",
        "ubuntu-os-cloud",
        "--metadata-from-file",
        f"startup-script={startup_path}",
        "--scopes",
        "storage-full",
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
  2. Run mimic
  3. Upload results to gs://{bucket}/results/<timestamp>/
  4. Shut itself down

Monitor:
  gcloud compute ssh {VM_NAME} --zone {zone} --project {project} -- tail -f /var/log/mimic.log
  gsutil ls gs://{bucket}/results/

Download results when done:
  gsutil -m cp -r gs://{bucket}/results/<timestamp>/ ./results/
""")


def cmd_wait(env: dict[str, str]) -> None:
    project = require(env, "GCP_PROJECT")
    zone = env.get("GCP_ZONE", "us-central1-a")
    bucket = require(env, "GCS_BUCKET")

    if not vm_exists(project, zone):
        print(f"VM '{VM_NAME}' not found — it may have already shut down.")
    else:
        print(f"Waiting for VM '{VM_NAME}' to finish...")
        while True:
            r = run(
                [
                    "gcloud",
                    "compute",
                    "instances",
                    "describe",
                    VM_NAME,
                    "--project",
                    project,
                    "--zone",
                    zone,
                    "--format",
                    "value(status)",
                ],
                check=False,
                capture=True,
            )
            if r.returncode != 0:
                print("VM no longer exists — it shut itself down.")
                break
            status = r.stdout.strip()
            if status in ("TERMINATED", "STOPPED"):
                print(f"VM {status.lower()}.")
                break
            print(f"  VM status: {status} — waiting 30s...")
            time.sleep(30)

    # Find latest results via latest.txt pointer, fall back to listing
    print("\nChecking results...")
    r = run(["gsutil", "cat", f"gs://{bucket}/latest.txt"], check=False, capture=True)
    if r.returncode == 0 and r.stdout.strip():
        ts = r.stdout.strip()
        latest = f"gs://{bucket}/results/{ts}/"
    else:
        r = run(["gsutil", "ls", f"gs://{bucket}/results/"], check=False, capture=True)
        if r.returncode != 0 or not r.stdout.strip():
            print("No results found in GCS bucket.")
            return
        dirs = sorted(r.stdout.strip().splitlines())
        latest = dirs[-1]

    print(f"Latest results: {latest}")

    # Download reports + runner log
    local_dir = AGENT_ROOT / "reports" / "gcp-latest"
    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to {local_dir}...")
    run(["gsutil", "-m", "cp", "-r", f"{latest}reports/", str(local_dir)], check=False)
    run(["gsutil", "cp", f"{latest}runner.log", str(local_dir / "runner.log")], check=False)
    print(f"\nResults downloaded to {local_dir}")


def cmd_cleanup(env: dict[str, str]) -> None:
    project = require(env, "GCP_PROJECT")
    zone = env.get("GCP_ZONE", "us-central1-a")

    if not vm_exists(project, zone):
        print(f"No VM '{VM_NAME}' found.")
        return

    print(f"Deleting VM '{VM_NAME}'...")
    run(
        ["gcloud", "compute", "instances", "delete", VM_NAME, "--project", project, "--zone", zone, "--quiet"],
        check=False,
    )


# Entry points are cmd_launch, cmd_wait, cmd_cleanup — called from cloud.py
