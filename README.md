# WhoDB Documentation QA Agent

Automated QA agent that tests every page of the [WhoDB](https://github.com/clidey/whodb) documentation by following instructions as a real user would. It spins up a sandboxed desktop environment with Docker, navigates the UI via screenshots and mouse/keyboard actions, and produces Markdown reports with pass/fail results and screen recordings.

Supports both **Anthropic Claude** and **OpenAI CUA** as the underlying computer-use model.

## How it works

```
llms.txt ──► parser ──► orchestrator ──► agent loop ──► reports/
               │              │              │
           80 pages     Docker infra    LLM + tools
           11 sessions   per session    (screenshot, click,
                                         type, scroll, ...)
```

1. **Parse** — `assets/llms.txt` contains all ~80 WhoDB doc pages concatenated into a single file. The parser splits them into individual `Page` objects.
2. **Orchestrate** — Pages are grouped into 11 sessions (Installation, Core Features, Data Management, etc.). Each session gets fresh Docker containers with the infrastructure it needs.
3. **Agent loop** — For each page, the agent sends the documentation content to the LLM as a system prompt, then enters a tool-use loop: the model sees screenshots, issues mouse/keyboard actions, and verifies each step. After testing, it produces a structured PASS/FAIL assessment.
4. **Report** — Results are collected into timestamped Markdown reports with a summary, per-page details, step-by-step results, and `.mp4` screen recordings.

## Setup

**Requirements:** Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker

```bash
# Clone and install
git clone <repo-url> && cd qa-agent
uv sync

# Configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (or OPENAI_API_KEY if using OpenAI)
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_PROVIDER` | No | `anthropic` | LLM provider: `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | For Anthropic | — | Claude API key |
| `OPENAI_API_KEY` | For OpenAI | — | OpenAI API key |
| `DOCS_AGENT_ARGS` | No | — | Extra CLI args passed through on cloud runners |
| `GCP_PROJECT` | For GCP | — | GCP project ID |
| `GCS_BUCKET` | For GCP | — | GCS bucket for artifacts |
| `AWS_REGION` | For AWS | — | AWS region |
| `S3_BUCKET` | For AWS | — | S3 bucket for artifacts |

## Usage

```bash
# Run the full QA suite (all 11 sessions, all 80 pages)
uv run docs-agent

# Run a single session
uv run docs-agent --session "Data Management"

# Run a single page
uv run docs-agent --page installation

# List all pages / sessions
uv run docs-agent --list-pages
uv run docs-agent --list-sessions

# Debug logging
uv run docs-agent -v
```

### Using OpenAI instead of Anthropic

```bash
AGENT_PROVIDER=openai uv run docs-agent --page installation
```

Or set `AGENT_PROVIDER=openai` in your `.env` file.

### Cloud runners

Launch on a GCP spot VM or AWS EC2 spot instance to avoid tying up your local machine:

```bash
# GCP
uv run docs-agent-gcp              # launch VM
uv run docs-agent-gcp --wait       # launch + poll + download results
uv run docs-agent-gcp --cleanup    # delete VM

# AWS
uv run docs-agent-aws              # launch instance
uv run docs-agent-aws --wait       # launch + poll + download results
uv run docs-agent-aws --cleanup    # terminate instance
```

## Infrastructure

The agent manages four Docker containers on a shared network:

| Container | Image | Purpose |
|-----------|-------|---------|
| `docsagent-desktop` | Custom (see `Dockerfile`) | Ubuntu desktop with Xvfb, Firefox, xdotool, ffmpeg, Docker-in-Docker |
| `docsagent-postgres` | `postgres` | PostgreSQL with sample data (users, products, orders, reviews) |
| `docsagent-whodb` | `clidey/whodb` | WhoDB instance under test |
| `docsagent-ollama` | `ollama/ollama` | Ollama with `llama3.2:1b` (only for AI-related sessions) |

Each session starts fresh containers based on its requirements. The "Informational & Reference" session (pure text pages with no UI steps) skips Docker entirely.

## Reports

Reports are written to `reports/<timestamp>/` with:

```
reports/2025-01-15_14-30-00_full-run/
  summary.md              # pass/fail counts, token usage, duration
  passed/
    installation.md       # per-page step details
    quick-start.md
  failed/
    features--schema-explorer.md
  skipped/
    introduction.md
  *.mp4                   # screen recordings per page
```

## Architecture

```
src/docs_agent/
  __main__.py          # CLI entry point
  config.py            # Constants, session definitions
  parser.py            # Parses llms.txt into Page objects
  orchestrator.py      # Session lifecycle, Docker setup, report generation
  agent.py             # Computer-use agent loop + tool dispatch
  models.py            # Page, PageResult, SessionConfig dataclasses
  docker_manager.py    # Docker subprocess operations
  report.py            # Markdown report generation
  providers/
    __init__.py        # Provider ABC, normalized types, factory
    anthropic_provider.py  # Claude computer-use API
    openai_provider.py     # OpenAI CUA (Responses API)
  runner_utils.py      # Shared cloud runner utilities
  gcp.py               # GCP spot VM launcher
  aws.py               # AWS EC2 spot launcher
```

### Provider abstraction

The agent loop in `agent.py` is provider-agnostic. It communicates with the LLM through a `Provider` interface:

- **`setup(system_prompt, width, height)`** — configure the provider
- **`send_initial(message)`** — send the first user message
- **`send_tool_results(results, nudge)`** — send tool execution results
- **`close()`** — clean up

Both providers normalize their responses into `ProviderResponse(tool_calls, text_parts, tokens_used, done)`, and the agent dispatches `ToolCall` objects to the same xdotool/Docker execution layer regardless of which LLM is driving.

The OpenAI provider normalizes CUA actions (e.g. `click`, `keypress`, `scroll`) into Anthropic-style action dicts so the existing tool dispatch code works unchanged.
