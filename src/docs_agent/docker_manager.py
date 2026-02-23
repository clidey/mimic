"""Manage Docker containers for docs-agent sessions.

All Docker operations use subprocess (no docker-py dependency).
"""

from __future__ import annotations

import base64
import logging
import subprocess
import time
from pathlib import Path

from docs_agent.config import (
    DESKTOP_CONTAINER,
    DISPLAY,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    NETWORK_NAME,
    OLLAMA_CONTAINER,
    POSTGRES_CONTAINER,
    POSTGRES_DB,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    WHODB_CONTAINER,
    WHODB_PORT,
)

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
DOCKERFILE_DIR = ASSETS_DIR.parent  # tools/docs-agent/
SAMPLE_SQL = ASSETS_DIR / "sample-data.sql"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, check: bool = True, capture: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    log.debug("$ %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=capture, text=True, check=check, timeout=timeout)


def _container_running(name: str) -> bool:
    r = _run(["docker", "inspect", "-f", "{{.State.Running}}", name], check=False)
    return r.returncode == 0 and "true" in r.stdout.lower()


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def create_network() -> None:
    if _run(["docker", "network", "inspect", NETWORK_NAME], check=False).returncode != 0:
        _run(["docker", "network", "create", NETWORK_NAME], check=False)
    log.info("Network %s ready", NETWORK_NAME)


def remove_network() -> None:
    _run(["docker", "network", "rm", NETWORK_NAME], check=False)


# ---------------------------------------------------------------------------
# Desktop container
# ---------------------------------------------------------------------------

def start_desktop() -> None:
    _run(["docker", "rm", "-f", DESKTOP_CONTAINER], check=False)
    log.info("Building desktop image...")
    _run(["docker", "build", "-t", "docsagent-desktop", str(DOCKERFILE_DIR)], timeout=300)
    _run([
        "docker", "run", "-d",
        "--privileged",
        "--name", DESKTOP_CONTAINER,
        "--network", NETWORK_NAME,
        "docsagent-desktop",
    ])
    _wait_for_desktop()


def _wait_for_desktop(timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = _run(
            ["docker", "exec", DESKTOP_CONTAINER, "xdpyinfo", "-display", DISPLAY],
            check=False,
        )
        if r.returncode == 0:
            log.info("Desktop container ready")
            return
        time.sleep(1)
    raise RuntimeError("Desktop container did not become ready")


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------

def start_postgres() -> None:
    _run(["docker", "rm", "-f", POSTGRES_CONTAINER], check=False)
    # Mount sample-data.sql into /docker-entrypoint-initdb.d/ so Postgres
    # executes it during init, before the port opens. This eliminates the
    # race condition of seeding after pg_isready.
    _run([
        "docker", "run", "-d",
        "--name", POSTGRES_CONTAINER,
        "--network", NETWORK_NAME,
        "-e", f"POSTGRES_USER={POSTGRES_USER}",
        "-e", f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
        "-e", f"POSTGRES_DB={POSTGRES_DB}",
        "-v", f"{SAMPLE_SQL}:/docker-entrypoint-initdb.d/init.sql:ro",
        "postgres:15",
    ])
    _wait_for_postgres()


def _wait_for_postgres(timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = _run(
            ["docker", "exec", POSTGRES_CONTAINER, "pg_isready", "-U", POSTGRES_USER],
            check=False,
        )
        if r.returncode == 0:
            log.info("Postgres ready (with sample data)")
            return
        time.sleep(1)
    raise RuntimeError("Postgres did not become ready")


# ---------------------------------------------------------------------------
# WhoDB
# ---------------------------------------------------------------------------

def start_whodb() -> None:
    _run(["docker", "rm", "-f", WHODB_CONTAINER], check=False)
    _run([
        "docker", "run", "-d",
        "--name", WHODB_CONTAINER,
        "--network", NETWORK_NAME,
        "clidey/whodb:latest",
    ])
    _wait_for_whodb()


def _wait_for_whodb(timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = _run(
            ["docker", "exec", DESKTOP_CONTAINER, "curl", "-sf", f"http://{WHODB_CONTAINER}:{WHODB_PORT}"],
            check=False,
        )
        if r.returncode == 0:
            log.info("WhoDB ready")
            return
        time.sleep(1)
    raise RuntimeError("WhoDB did not become ready")


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def start_ollama() -> None:
    _run(["docker", "rm", "-f", OLLAMA_CONTAINER], check=False)
    log.info("Pulling Ollama image (this may take a while on first run)...")
    _run(["docker", "pull", "ollama/ollama:latest"], timeout=600)
    _run([
        "docker", "run", "-d",
        "--name", OLLAMA_CONTAINER,
        "--network", NETWORK_NAME,
        "ollama/ollama:latest",
    ])
    _wait_for_ollama()
    log.info("Pulling llama3.2:1b model (this may take a while)...")
    _run(
        ["docker", "exec", OLLAMA_CONTAINER, "ollama", "pull", "llama3.2:1b"],
        timeout=600,
    )
    log.info("Ollama model ready")


def _wait_for_ollama(timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = _run(
            ["docker", "exec", DESKTOP_CONTAINER, "curl", "-sf", f"http://{OLLAMA_CONTAINER}:11434"],
            check=False,
        )
        if r.returncode == 0:
            log.info("Ollama ready")
            return
        time.sleep(1)
    raise RuntimeError("Ollama did not become ready")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def stop_all() -> None:
    for name in (DESKTOP_CONTAINER, POSTGRES_CONTAINER, WHODB_CONTAINER, OLLAMA_CONTAINER):
        _run(["docker", "rm", "-f", name], check=False)
    remove_network()
    log.info("All containers stopped and removed")


# ---------------------------------------------------------------------------
# Exec helpers (used by agent)
# ---------------------------------------------------------------------------

def exec_in_desktop(command: str, *, timeout: int = 30) -> str:
    """Run a shell command inside the desktop container and return stdout."""
    r = _run(
        ["docker", "exec", DESKTOP_CONTAINER, "bash", "-c", command],
        check=False,
        timeout=timeout,
    )
    output = r.stdout
    if r.stderr:
        output += "\n" + r.stderr
    return output.strip()


def take_screenshot() -> str | None:
    """Capture the desktop and return base64-encoded PNG, or None on failure."""
    exec_in_desktop(f"DISPLAY={DISPLAY} scrot -o /tmp/screenshot.png")
    raw = _run(
        ["docker", "exec", DESKTOP_CONTAINER, "base64", "-w0", "/tmp/screenshot.png"],
        check=False,
    )
    if raw.returncode != 0:
        log.warning("Screenshot failed: %s", raw.stderr.strip() or "unknown error")
        return None
    return raw.stdout.strip()


def xdotool(args: str) -> str:
    """Run an xdotool command on the desktop display."""
    return exec_in_desktop(f"DISPLAY={DISPLAY} xdotool {args}")


# ---------------------------------------------------------------------------
# Screen recording
# ---------------------------------------------------------------------------

def start_recording() -> None:
    """Start recording the desktop display to /tmp/recording.mp4 inside the container."""
    exec_in_desktop(
        f"DISPLAY={DISPLAY} ffmpeg -video_size {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} -framerate 5 "
        f"-f x11grab -i {DISPLAY} -c:v libx264 -preset ultrafast "
        "-pix_fmt yuv420p -y /tmp/recording.mp4 </dev/null &>/dev/null &"
    )
    log.info("Screen recording started")


def stop_recording() -> None:
    """Stop the ffmpeg recording gracefully."""
    # Send SIGINT to ffmpeg so it finalizes the mp4 properly
    exec_in_desktop("pkill -INT ffmpeg || true")
    # Wait for ffmpeg to flush and exit
    time.sleep(2)
    log.info("Screen recording stopped")


def copy_recording(dest: Path) -> bool:
    """Copy the recording from the container to a local path. Returns True on success."""
    r = _run(
        ["docker", "cp", f"{DESKTOP_CONTAINER}:/tmp/recording.mp4", str(dest)],
        check=False,
    )
    if r.returncode != 0:
        log.warning("Failed to copy recording: %s", r.stderr.strip() or "unknown error")
        return False
    log.info("Recording saved to %s", dest)
    return True
