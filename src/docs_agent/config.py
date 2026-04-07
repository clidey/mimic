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
ANTHROPIC_MAX_TOKENS = 16384

# ---------------------------------------------------------------------------
# OpenAI API
# ---------------------------------------------------------------------------
OPENAI_MODEL = "computer-use-preview"
OPENAI_ASSESSMENT_MODEL = "gpt-5.2"
OPENAI_MAX_TOKENS = 16384

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
MAX_AGENT_ITERATIONS = 40
WRAPUP_THRESHOLD = 30  # inject wrap-up nudge at this iteration

# ---------------------------------------------------------------------------
# Assessment format — single source of truth used by prompts and providers
# ---------------------------------------------------------------------------
ASSESSMENT_FORMAT = """\
STATUS: PASSED | FAILED | SKIPPED
STEPS:
- [step description] : PASS | FAIL ([error if failed])
- [step description] : PASS | FAIL ([error if failed])
FAILURE_TYPE: independent | likely_cascading | unknown
FAILURE_REASON: [explanation if failed]"""
