# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Generic documentation QA agent — uses LLM computer-use APIs (Anthropic Claude or OpenAI CUA) to automatically test documentation pages by following instructions as a real user would. It reads a `qa-project.yaml` config, brings up infrastructure via Docker Compose, spins up a desktop sandbox container, navigates the UI via screenshots + xdotool, and produces Markdown reports with pass/fail results and screen recordings.

Projects provide a `qa-project.yaml` that defines the docs source, environment description (injected into the LLM system prompt), and session groupings. App infrastructure is managed by a `docker-compose.yml` alongside the project file; the agent only manages its own desktop sandbox container. See `examples/whodb/` for a complete example.

## Commands

```bash
# Install dependencies
uv sync

# Run full QA suite against a project
uv run docs-agent --project examples/whodb

# Run a single session by name
uv run docs-agent --project examples/whodb --session "Data Management"

# Run a single page by slug
uv run docs-agent --project examples/whodb --page installation

# List all parsed pages
uv run docs-agent --project examples/whodb --list-pages

# List all session definitions with infrastructure requirements
uv run docs-agent --project examples/whodb --list-sessions

# Verbose/debug logging
uv run docs-agent --project examples/whodb -v

# JSON-formatted logs (for cloud/structured log capture)
uv run docs-agent --project examples/whodb --json-log

# Launch on cloud spot instance (requires .env with cloud config)
uv run docs-agent-cloud --cloud gcp --provider anthropic
uv run docs-agent-cloud --cloud aws --provider openai
uv run docs-agent-cloud --cloud gcp --wait      # launch + poll + download results
uv run docs-agent-cloud --cloud aws --cleanup   # terminate instance
```

## Architecture

The agent follows a pipeline: **load project → parse docs → orchestrate sessions → run computer-use agent per page → generate reports**.

### Key modules (all in `src/docs_agent/`)

- **`project.py`** — Loads `qa-project.yaml` into a `ProjectConfig` dataclass. Resolves relative paths, detects compose files, expands page glob patterns (e.g. `ai/*`), and supports auto-grouping pages by directory prefix when no sessions are defined.
- **`parser.py`** — Parses a concatenated docs file (e.g. `llms.txt`) delimited by `# filename.mdx` headers into `Page` objects. Used for FILE/URL docs modes (see `project.py` `DocsMode`).
- **`config.py`** — Runtime constants: desktop container name, network name, display settings, provider config (model names, API settings), agent loop parameters, and `ASSESSMENT_FORMAT` (the assessment template shared by prompts and providers). No project-specific config.
- **`orchestrator.py`** — Top-level runner. Takes `ProjectConfig`, sets up infrastructure per session via Docker Compose + desktop sandbox, iterates pages, calls the agent, collects recordings, generates reports.
- **`agent.py`** — The computer-use agent loop (`test_page()`). Wires together the prompt, provider, tool dispatch, and assessment parsing; runs the iteration loop and screen recording. Prompt building, tool execution, and assessment parsing now live in separate modules (below).
- **`prompts.py`** — System-prompt builders. `build_system_prompt` dispatches on provider: `_build_anthropic_prompt` (full assessment format) vs `_build_cua_prompt` (action-oriented, explicit desktop guidance, no assessment format). Also `build_initial_message`.
- **`tools.py`** — `dispatch_tool` routes `computer`/`bash`/`str_replace_based_edit_tool` calls to Docker exec handlers (screenshots via `scrot`, mouse/keyboard via `xdotool`).
- **`assessment.py`** — Parses the structured assessment (`STATUS`/`STEPS`/`FAILURE_TYPE`/`FAILURE_REASON`) from model output into a `PageResult` via regex. `STATUS_RE` also gates whether OpenAI's `gpt-5.2` follow-up assessment is triggered.
- **`providers/`** — Provider abstraction for interchangeable LLM backends. `__init__.py` defines the `Provider` ABC, normalized types (`ToolCall`, `ToolResult`, `ProviderResponse`), and a `get_provider()` factory. `anthropic_provider.py` wraps the Claude computer-use API. `openai_provider.py` wraps the OpenAI CUA (Responses API) with `reasoning` summaries, safety check acknowledgment, and a `generate_assessment()` method that calls `gpt-5.2` to produce structured results.
- **`docker_manager.py`** — All Docker operations via subprocess (no docker-py). Manages the desktop sandbox container (built from the bundled `sandbox/Dockerfile`) and delegates app services to Docker Compose (`compose_up`/`compose_down`). `prepare_desktop()` pre-launches Firefox and a terminal for CUA models. Also handles screenshots, xdotool exec, and ffmpeg screen recording.
- **`report.py`** — Generates timestamped report directories under `reports/` with `summary.md` and per-page Markdown files organized into `passed/`, `failed/`, `skipped/` subdirectories, plus `.mp4` recordings.
- **`runner_utils.py`** — Shared utilities for cloud runners: `.env` parsing, required-var checks, and tarball packaging.
- **`cloud.py`** — Unified CLI entry point for cloud runners (`docs-agent-cloud --cloud gcp|aws --provider anthropic|openai`).
- **`gcp.py`** — GCP launcher: packages repo, uploads to GCS, creates a spot VM with a startup script, polls for completion.
- **`aws.py`** — AWS launcher using boto3: packages repo, uploads to S3, creates an EC2 spot instance, polls for results.
- **`models.py`** — Dataclasses: `Page`, `PageResult`, `StepResult`, `SessionState` (cascading-failure tracker), `SessionConfig`.

### Project config (`qa-project.yaml`)

Each project provides: `name`, `environment` (free-text for system prompt), and optional `sessions` with page slug lists/globs and `compose_profiles`. Docs are sourced one of four ways (`project.py` `DocsMode`): `docs` pointing at a concatenated file (FILE) or a directory (DIRECTORY); or `docs_url` pointing at a remote file (URL) or a live docs base URL the agent browses (BROWSE). BROWSE mode requires explicit `sessions`. A `docker-compose.yml` beside the project file defines the app services.

### Agent loop details

The agent loop in `agent.py:test_page()` runs up to `MAX_AGENT_ITERATIONS` (40) turns. At turn 30 (`WRAPUP_THRESHOLD`), it injects a wrap-up nudge message telling the LLM to stop testing and produce its assessment. The agent's final text output is parsed via regex for the structured assessment format. For OpenAI, the CUA model rarely produces structured text, so a follow-up call to `gpt-5.2` (configured via `OPENAI_ASSESSMENT_MODEL` in `config.py`) analyzes the action log + final screenshot to generate the assessment.

### Infrastructure lifecycle

Each session gets fresh infrastructure. `_setup_infra()` calls `stop_all()` first (cleanup from previous runs), then runs `docker compose up` with the session's compose profiles, then starts the desktop sandbox. For OpenAI, `prepare_desktop()` pre-launches Firefox and a terminal (the CUA model struggles to find and open apps on its own). Sessions with `needs_desktop: false` skip all Docker entirely.

## Environment

Requires `.env` file (copy from `.env.example`). Key variables:
- `AGENT_PROVIDER` — `anthropic` (default) or `openai`
- `ANTHROPIC_API_KEY` — required for Anthropic provider
- `OPENAI_API_KEY` — required for OpenAI provider
- `GCP_PROJECT`, `GCS_BUCKET` — required only for GCP runner
- `AWS_REGION`, `S3_BUCKET` — required only for AWS runner
- `DOCS_AGENT_ARGS` — optional CLI args passed through on GCP/AWS

## Key Conventions

- Python 3.10+, dependencies (`anthropic`, `openai`, `boto3`, `pyyaml`), managed with `uv` and `hatchling`
- All Docker operations use raw `subprocess` calls, no docker-py
- App infrastructure via `docker-compose.yml`; agent only manages the desktop sandbox
- Page slugs match the `.mdx` filename without extension (e.g., `features/schema-explorer`)
- Session names are case-insensitive for lookup
- Reports go to `reports/` (gitignored)
- The desktop container runs privileged (Docker-in-Docker support)
