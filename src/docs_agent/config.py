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
# Backend: "api" (first-party Anthropic API) or "bedrock" (Amazon Bedrock).
ANTHROPIC_BACKEND = os.environ.get("ANTHROPIC_BACKEND", "api").lower()
# Model ID. Defaults differ per backend: Bedrock uses `anthropic.`-prefixed IDs
# and only some support computer use (claude-opus-4-7 works; sonnet-5/opus-4-8
# reject the computer tool as of this writing). Override via ANTHROPIC_MODEL.
_ANTHROPIC_MODEL_DEFAULTS = {"api": "claude-sonnet-5", "bedrock": "anthropic.claude-opus-4-7"}
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", _ANTHROPIC_MODEL_DEFAULTS.get(ANTHROPIC_BACKEND, "claude-sonnet-5"))
ANTHROPIC_BETA = "computer-use-2025-11-24"
ANTHROPIC_MAX_TOKENS = 16384
# Reasoning effort (output_config). One of: low, medium, high, xhigh, max.
ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")

# ---------------------------------------------------------------------------
# OpenAI API
# ---------------------------------------------------------------------------
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")  # native computer-use `computer` tool
OPENAI_ASSESSMENT_MODEL = os.environ.get("OPENAI_ASSESSMENT_MODEL", "gpt-5.2")
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
