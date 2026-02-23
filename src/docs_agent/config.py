"""Configuration constants for the docs-agent runtime."""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Desktop container
# ---------------------------------------------------------------------------
DESKTOP_CONTAINER = "docsagent-desktop"
NETWORK_NAME = "docsagent-net"

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 800
DISPLAY = ":1"

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
AGENT_PROVIDER = os.environ.get("AGENT_PROVIDER", "anthropic")

# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_BETA = "computer-use-2025-11-24"
ANTHROPIC_MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# OpenAI API
# ---------------------------------------------------------------------------
OPENAI_MODEL = "computer-use-preview"
OPENAI_MAX_TOKENS = 4096

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
MAX_AGENT_ITERATIONS = 40
WRAPUP_THRESHOLD = 30  # inject wrap-up nudge at this iteration
