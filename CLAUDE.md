# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhoDB documentation QA agent — uses LLM computer-use APIs (Anthropic Claude or OpenAI CUA) to automatically test every page of the WhoDB documentation by following instructions as a real user would. It spins up Docker containers (desktop with Firefox, PostgreSQL, WhoDB, optionally Ollama), navigates the UI via screenshots + xdotool, and produces Markdown reports with pass/fail results and screen recordings.

## Commands

```bash
# Install dependencies
uv sync

# Run full QA suite (all sessions, all ~80 pages)
uv run docs-agent

# Run a single session by name
uv run docs-agent --session "Data Management"

# Run a single page by slug
uv run docs-agent --page installation

# List all parsed pages from llms.txt
uv run docs-agent --list-pages

# List all session definitions with infrastructure requirements
uv run docs-agent --list-sessions

# Verbose/debug logging
uv run docs-agent -v

# Launch on GCP spot VM (requires .env with GCP_PROJECT, GCS_BUCKET)
uv run docs-agent-gcp
uv run docs-agent-gcp --wait      # launch + poll + download results
uv run docs-agent-gcp --cleanup   # delete VM

# Launch on AWS EC2 spot instance (requires .env with AWS_REGION, S3_BUCKET)
uv run docs-agent-aws
uv run docs-agent-aws --wait      # launch + poll + download results
uv run docs-agent-aws --cleanup   # terminate instance
```

## Architecture

The agent follows a pipeline: **parse docs → orchestrate sessions → run computer-use agent per page → generate reports**.

### Key modules (all in `src/docs_agent/`)

- **`parser.py`** — Parses `assets/llms.txt` (a single file containing all ~80 WhoDB doc pages concatenated, delimited by `# filename.mdx` headers) into `Page` objects.
- **`config.py`** — All constants (container names, ports, credentials, Claude API settings) and the `SESSIONS` list that groups page slugs into logical sessions with infrastructure flags (`needs_desktop`, `needs_postgres`, `needs_ollama`, etc.).
- **`orchestrator.py`** — Top-level runner. Sets up Docker infrastructure per session, iterates pages, calls the agent, collects recordings, generates reports. Handles the `run_all`/`run_session`/`run_page` entry points.
- **`agent.py`** — The computer-use agent loop. Builds a system prompt with the page content, uses the provider abstraction to communicate with the LLM, dispatches tool calls to Docker exec commands (screenshots via `scrot`, mouse/keyboard via `xdotool`). Parses the structured `STATUS/STEPS/FAILURE_TYPE/FAILURE_REASON` output into `PageResult`.
- **`providers/`** — Provider abstraction for interchangeable LLM backends. `__init__.py` defines the `Provider` ABC, normalized types (`ToolCall`, `ToolResult`, `ProviderResponse`), and a `get_provider()` factory. `anthropic_provider.py` wraps the Claude computer-use API. `openai_provider.py` wraps the OpenAI CUA (Responses API), normalizing actions to the Anthropic-style format that `_dispatch_tool()` expects.
- **`docker_manager.py`** — All Docker operations via subprocess (no docker-py). Manages 4 containers on a shared network: desktop (custom Dockerfile with Xvfb+Firefox+Docker-in-Docker), postgres (with `assets/sample-data.sql` auto-loaded), whodb, ollama. Also handles screenshots, xdotool exec, and ffmpeg screen recording.
- **`report.py`** — Generates timestamped report directories under `reports/` with `summary.md` and per-page Markdown files organized into `passed/`, `failed/`, `skipped/` subdirectories, plus `.mp4` recordings.
- **`runner_utils.py`** — Shared utilities for cloud runners: `.env` parsing, required-var checks, and tarball packaging.
- **`gcp.py`** — Standalone GCP launcher that packages the repo, uploads to GCS, creates a spot VM with a startup script, and optionally polls for completion.
- **`aws.py`** — Standalone AWS launcher using boto3. Packages the repo, uploads to S3, creates an EC2 spot instance, and optionally polls for results. Supports IAM instance profiles or env var credentials.
- **`models.py`** — Dataclasses: `Page`, `PageResult`, `StepResult`, `SessionState` (cascading-failure tracker), `SessionConfig`.

### Agent loop details

The agent loop in `agent.py:test_page()` runs up to `MAX_AGENT_ITERATIONS` (40) turns. At turn 30 (`WRAPUP_THRESHOLD`), it injects a wrap-up nudge message telling Claude to stop testing and produce its assessment. The agent's final text output is parsed via regex for the structured assessment format.

### Infrastructure lifecycle

Each session gets fresh containers. `_setup_infra()` calls `stop_all()` first (cleanup from previous runs), then selectively starts containers based on `SessionConfig` flags. The "Informational & Reference" session skips Docker entirely (`needs_desktop=False`).

## Environment

Requires `.env` file (copy from `.env.example`). Key variables:
- `AGENT_PROVIDER` — `anthropic` (default) or `openai`
- `ANTHROPIC_API_KEY` — required for Anthropic provider
- `OPENAI_API_KEY` — required for OpenAI provider
- `GCP_PROJECT`, `GCS_BUCKET` — required only for GCP runner
- `AWS_REGION`, `S3_BUCKET` — required only for AWS runner
- `DOCS_AGENT_ARGS` — optional CLI args passed through on GCP/AWS

## Key Conventions

- Python 3.10+, dependencies (`anthropic`, `openai`, `boto3`), managed with `uv` and `hatchling`
- All Docker operations use raw `subprocess` calls, no docker-py
- Page slugs match the `.mdx` filename without extension (e.g., `features/schema-explorer`)
- Session names are case-insensitive for lookup
- Reports go to `reports/` (gitignored)
- The desktop container runs privileged (Docker-in-Docker support)
