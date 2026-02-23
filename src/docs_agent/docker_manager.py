"""Manage Docker containers for docs-agent sessions.

All Docker operations use subprocess (no docker-py dependency).
"""

from __future__ import annotations

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
)

log = logging.getLogger(__name__)

SANDBOX_DIR = Path(__file__).resolve().parent / "sandbox"


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
# Docker Compose — manages app infrastructure
# ---------------------------------------------------------------------------

def compose_up(compose_file: Path, profiles: list[str] | None = None) -> None:
    """Bring up services defined in a docker-compose file."""
    cmd = ["docker", "compose", "-f", str(compose_file)]
    for p in (profiles or []):
        cmd += ["--profile", p]
    cmd += ["up", "-d", "--wait"]
    _run(cmd, timeout=300)
    log.info("Compose services up (profiles=%s)", profiles or [])


def compose_down(compose_file: Path) -> None:
    """Tear down all compose services."""
    _run(["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans"], check=False)
    log.info("Compose services down")


# ---------------------------------------------------------------------------
# Desktop container — always managed by the agent
# ---------------------------------------------------------------------------

def start_desktop() -> None:
    """Build and start the desktop sandbox container.

    Uses the bundled Dockerfile in ``src/docs_agent/sandbox/``.
    Attaches to the shared network so the desktop can reach compose-managed services.
    """
    _run(["docker", "rm", "-f", DESKTOP_CONTAINER], check=False)
    log.info("Building desktop image...")
    _run(["docker", "build", "-t", "docsagent-desktop", str(SANDBOX_DIR)], timeout=300)
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
# Cleanup
# ---------------------------------------------------------------------------

def stop_all(compose_file: Path | None = None) -> None:
    """Remove the desktop container and optionally tear down compose services."""
    _run(["docker", "rm", "-f", DESKTOP_CONTAINER], check=False)
    if compose_file is not None:
        compose_down(compose_file)
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
    exec_in_desktop("pkill -INT ffmpeg || true")
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
