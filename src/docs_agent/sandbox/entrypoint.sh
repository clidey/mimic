#!/usr/bin/env bash
set -euo pipefail

# Start virtual framebuffer first (so health checks pass immediately)
Xvfb :1 -screen 0 1280x800x24 &
sleep 1

# Start lightweight window manager (suppress wallpaper warning)
DISPLAY=:1 fluxbox >/dev/null 2>&1 &
sleep 0.5

echo "Desktop ready — display :1 @ 1280x800"

# Start Docker daemon in background (Docker-in-Docker)
dockerd --storage-driver=vfs &>/var/log/dockerd.log &

# Wait for Docker daemon to be ready (non-blocking to the display)
for i in $(seq 1 30); do
    if docker info &>/dev/null; then
        echo "Docker daemon ready"
        break
    fi
    sleep 1
done

# Keep container alive
exec tail -f /dev/null
