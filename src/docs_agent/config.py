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
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_BETA = "computer-use-2025-11-24"
ANTHROPIC_MAX_TOKENS = 16384
# Reasoning effort (output_config). One of: low, medium, high, xhigh, max.
ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")

# ---------------------------------------------------------------------------
# OpenAI API
# ---------------------------------------------------------------------------
OPENAI_MODEL = "gpt-5.5"  # native computer-use via the `computer` tool (Responses API)
OPENAI_ASSESSMENT_MODEL = "gpt-5.2"
OPENAI_MAX_TOKENS = 16384
# Reasoning effort (reasoning.effort). One of: low, medium, high, xhigh.
OPENAI_EFFORT = os.environ.get("OPENAI_EFFORT", "medium")

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
