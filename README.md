# Documentation QA Agent

Automated QA agent that tests documentation pages by following instructions as a real user would. It spins up a sandboxed desktop environment with Docker, navigates the UI via screenshots and mouse/keyboard actions, and produces Markdown reports with pass/fail results and screen recordings.

Works with **any project** — configured via a `qa-project.yaml` file. Supports both **Anthropic Claude** and **OpenAI CUA** as the underlying computer-use model.

## How it works

```
qa-project.yaml ──► parser ──► orchestrator ──► agent loop ──► reports/
       │               │              │              │
   project config   Page objects  Docker infra    LLM + tools
   + compose.yml                  per session    (screenshot, click,
                                                  type, scroll, ...)
```

1. **Configure** — A `qa-project.yaml` defines the docs source, environment description, and session groupings. A `docker-compose.yml` beside it defines app infrastructure.
2. **Parse** — The docs file (e.g. `llms.txt`) is split into individual `Page` objects by header delimiters.
3. **Orchestrate** — Pages are grouped into sessions. Each session gets fresh Docker containers via `docker compose up`, plus the desktop sandbox.
4. **Agent loop** — For each page, the agent sends the documentation content to the LLM, then enters a tool-use loop: the model sees screenshots, issues mouse/keyboard actions, and verifies each step.
5. **Report** — Results are collected into timestamped Markdown reports with a summary, per-page details, and `.mp4` screen recordings.

## Setup

**Requirements:** Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker

```bash
git clone <repo-url> && cd qa-agent
uv sync

cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (or OPENAI_API_KEY if using OpenAI)
```

## Quick start (WhoDB example)

```bash
# List all pages
uv run docs-agent --project examples/whodb --list-pages

# List sessions
uv run docs-agent --project examples/whodb --list-sessions

# Test a single page
uv run docs-agent --project examples/whodb --page installation

# Run a single session
uv run docs-agent --project examples/whodb --session "Data Management"

# Run everything
uv run docs-agent --project examples/whodb
```

## Adding your own project

Create a directory with these files:

### 1. `qa-project.yaml`

```yaml
name: my-project
docs: docs/llms.txt       # path to your docs file, relative to this yaml

# Free-text injected into the LLM system prompt.
# Describe what's running and how to reach it (use Docker network hostnames).
environment: |
  - My app is running at http://myapp:3000
  - PostgreSQL at db:5432 (user=admin, password=secret, db=mydb)

# Group pages into sessions (optional — omit for auto-grouping by directory)
sessions:
  - name: Getting Started
    pages: [installation, quickstart, guides/*]    # globs expand against parsed slugs

  - name: Premium Features
    pages: [features/billing, features/teams]
    compose_profiles: [stripe]     # activates the "stripe" compose profile

  - name: Reference
    needs_desktop: false           # text-only pages, no browser needed
    pages: [changelog, glossary, api-reference]
```

### 2. `docker-compose.yml`

Standard compose file for your app infrastructure. The agent manages the network (`docsagent-net`) and its own desktop container — you just define your services:

```yaml
services:
  myapp:
    image: myorg/myapp:latest
    networks: [docsagent-net]

  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: secret
    networks: [docsagent-net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready"]
      interval: 2s
      retries: 30

  stripe-mock:
    image: stripe/stripe-mock
    profiles: [stripe]             # only starts for sessions that need it
    networks: [docsagent-net]

networks:
  docsagent-net:
    name: docsagent-net
    external: true     # the agent creates this network — compose just joins it
```

> **Why `external: true`?** The agent creates the `docsagent-net` network before running compose, so that both your app services *and* the agent's desktop sandbox (which lives outside compose) share the same network.

### 3. Docs file (e.g. `llms.txt`)

A single file containing all your documentation pages concatenated together. Each page starts with a header line in the format `# filename.mdx`, followed by the page content. Pages are separated by `---`:

```
# installation.mdx
## Installation

Download the package from ...

To install via Docker:

    docker run -p 3000:3000 myorg/myapp

After installation, navigate to http://localhost:3000.

---
# quickstart.mdx
## Quick Start

1. Open your browser to the app URL
2. Click "New Project"
3. ...

---
# features/billing.mdx
## Billing

Navigate to Settings > Billing to configure ...
```

**Format rules:**
- Each page starts with `# filename.ext` on its own line (e.g. `# installation.mdx`)
- The extension (default `mdx`) must be consistent — the parser uses it to detect headers
- Directory prefixes in the filename create nested slugs (`features/billing.mdx` → slug `features/billing`)
- `---` between pages is optional (stripped automatically)
- The content is what the LLM reads — write it as if instructing a human to follow steps

**How slugs work:**
The slug is the filename minus the extension. These slugs are what you reference in `qa-project.yaml` sessions:

| Header | Slug |
|--------|------|
| `# installation.mdx` | `installation` |
| `# features/billing.mdx` | `features/billing` |
| `# guides/tutorials/first-steps.mdx` | `guides/tutorials/first-steps` |

**Where to get this file:**
Many documentation frameworks can export a single concatenated file. For example, if your docs are MDX files in a directory tree, you could generate it with:

```bash
find docs/ -name "*.mdx" | sort | while read f; do
  echo "# ${f#docs/}"
  cat "$f"
  echo -e "\n---"
done > llms.txt
```

### Then run:

```bash
uv run docs-agent --project path/to/your-project --list-pages   # verify parsing
uv run docs-agent --project path/to/your-project                 # run everything
```

### Key things to know

- **Use Docker network hostnames**, not `localhost`. The LLM drives Firefox inside a container on the `docsagent-net` network, so `http://myapp:3000` works, `http://localhost:3000` does not.
- **`compose_profiles`** map to `docker compose --profile <name>`. Use them for optional services that only some sessions need.
- **`needs_desktop: false`** marks text-only sessions (API reference, changelogs) — they skip all Docker and are marked NOT_APPLICABLE.
- **Globs in page lists** (e.g. `guides/*`) expand against the parsed slugs from your docs file.
- If you **omit `sessions`** entirely, pages are auto-grouped by their top-level directory prefix.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_PROVIDER` | No | `anthropic` | LLM provider: `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | For Anthropic | — | Claude API key |
| `OPENAI_API_KEY` | For OpenAI | — | OpenAI API key |
| `DOCS_AGENT_ARGS` | No | — | Extra CLI args for cloud runners |
| `GCP_PROJECT` | For GCP | — | GCP project ID |
| `GCS_BUCKET` | For GCP | — | GCS bucket for artifacts |
| `AWS_REGION` | For AWS | — | AWS region |
| `S3_BUCKET` | For AWS | — | S3 bucket for artifacts |

### Using OpenAI instead of Anthropic

```bash
AGENT_PROVIDER=openai uv run docs-agent --project examples/whodb --page installation
```

Or set `AGENT_PROVIDER=openai` in your `.env`.

## Cloud runners

Launch on a GCP spot VM or AWS EC2 spot instance:

```bash
# GCP
uv run docs-agent-gcp              # launch VM
uv run docs-agent-gcp --wait       # launch + poll + download results
uv run docs-agent-gcp --cleanup    # delete VM

# AWS
uv run docs-agent-aws
uv run docs-agent-aws --wait
uv run docs-agent-aws --cleanup
```

## Reports

```
reports/2025-01-15_14-30-00_full-run/
  summary.md              # pass/fail counts, token usage, duration
  passed/
    installation.md       # per-page step details
  failed/
    features--schema-explorer.md
  skipped/
    introduction.md
  *.mp4                   # screen recordings
```

## Architecture

```
src/docs_agent/
  __main__.py          # CLI entry point (--project flag)
  project.py           # Load qa-project.yaml into ProjectConfig
  config.py            # Runtime constants (display, provider, agent loop)
  parser.py            # Parse docs file into Page objects
  orchestrator.py      # Session lifecycle, compose up/down, report generation
  agent.py             # Computer-use agent loop + tool dispatch
  models.py            # Page, PageResult, SessionConfig dataclasses
  docker_manager.py    # Docker subprocess operations (compose + desktop)
  sandbox/
    Dockerfile         # Desktop sandbox (bundled, shared by all projects)
    entrypoint.sh
  report.py            # Markdown report generation
  providers/
    __init__.py        # Provider ABC, normalized types, factory
    anthropic_provider.py
    openai_provider.py
  runner_utils.py      # Shared cloud runner utilities
  gcp.py               # GCP spot VM launcher
  aws.py               # AWS EC2 spot launcher

examples/
  whodb/               # Complete example project
    qa-project.yaml
    docker-compose.yml
    assets/
      llms.txt         # WhoDB documentation (80 pages)
      sample-data.sql  # PostgreSQL seed data
```
