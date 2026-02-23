# Documentation QA Agent

Automated QA agent that tests documentation by following instructions as a real user would — spinning up a sandboxed desktop in Docker, navigating via screenshots and mouse/keyboard, and producing Markdown reports with pass/fail results and screen recordings.

Configured via `qa-project.yaml`. Supports **Anthropic Claude** and **OpenAI CUA**. [How it works &darr;](#how-it-works)

## Setup

**Requirements:** Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker

```bash
git clone <repo-url> && cd qa-agent
uv sync
cp .env.example .env   # set ANTHROPIC_API_KEY or OPENAI_API_KEY
```

## Quick start

```bash
uv run docs-agent --project examples/whodb --list-pages
uv run docs-agent --project examples/whodb --page installation
uv run docs-agent --project examples/whodb --session "Data Management"
uv run docs-agent --project examples/whodb   # run everything
```

## Adding your own project

Create a directory with a `qa-project.yaml` and (optionally) a `docker-compose.yml`:

### `qa-project.yaml`

```yaml
name: my-project
docs: docs/llms.txt       # see "Docs sources" below

environment: |
  - My app is running at http://myapp:3000
  - PostgreSQL at db:5432 (user=admin, password=secret, db=mydb)

sessions:                  # optional — omit to auto-group by directory prefix
  - name: Getting Started
    pages: [installation, quickstart, guides/*]   # globs work

  - name: Premium Features
    pages: [features/billing, features/teams]
    compose_profiles: [stripe]    # activates compose profile

  - name: Reference
    needs_desktop: false          # skips Docker, marks pages NOT_APPLICABLE
    pages: [changelog, glossary]
```

### Docs sources

The `docs` field auto-detects the source type:

| Value | Mode | What happens |
|---|---|---|
| `assets/llms.txt` | **File** | Concatenated file with `# filename.mdx` headers |
| `docs/` | **Directory** | Reads each `.mdx` file; slug = relative path minus extension |
| `https://.../llms.txt` | **URL** | Fetches remote file, same format as File |

A fourth **Browse** mode uses `docs_url` — the LLM navigates to `{docs_url}/{slug}` in Firefox instead of reading content from the prompt:

```yaml
docs_url: https://docs.example.com
sessions:   # required — no content to auto-group from
  - name: Getting Started
    pages: [installation, quickstart]
```

You can combine both — `docs` for prompt content, `docs_url` so the LLM also opens the live page:

```yaml
docs: assets/llms.txt
docs_url: https://docs.example.com
```

### Concatenated file format

For File and URL modes, the docs file uses `# filename.mdx` headers to delimit pages:

```
# installation.mdx
## Installation
Download the package and run:
    docker run -p 3000:3000 myorg/myapp
---
# features/billing.mdx
## Billing
Navigate to Settings > Billing ...
```

- Slugs = filename minus extension (`features/billing.mdx` → `features/billing`)
- `---` separators are optional
- Generate from a directory: `find docs/ -name "*.mdx" | sort | while read f; do echo "# ${f#docs/}"; cat "$f"; echo -e "\n---"; done > llms.txt`
- Or just use **Directory mode** and skip concatenation entirely

### `docker-compose.yml`

Standard compose file for your app services. The agent manages the network and its own desktop container:

```yaml
services:
  myapp:
    image: myorg/myapp:latest
    networks: [docsagent-net]
  db:
    image: postgres:15
    environment: { POSTGRES_PASSWORD: secret }
    networks: [docsagent-net]

networks:
  docsagent-net:
    name: docsagent-net
    external: true   # agent creates this network; compose joins it
```

### Tips

- Use **Docker network hostnames** (`http://myapp:3000`), not `localhost` — the LLM runs Firefox inside a container.
- **`compose_profiles`** map to `docker compose --profile`. Use for optional services.
- **Globs** in page lists (e.g. `guides/*`) expand against parsed slugs.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic |
| `OPENAI_API_KEY` | — | Required for OpenAI |
| `GCP_PROJECT` / `GCS_BUCKET` | — | For GCP cloud runner |
| `AWS_REGION` / `S3_BUCKET` | — | For AWS cloud runner |

## Cloud runners

```bash
uv run docs-agent-gcp [--wait] [--cleanup]
uv run docs-agent-aws [--wait] [--cleanup]
```

## Reports

```
reports/2025-01-15_14-30-00_full-run/
  summary.md
  passed/installation.md
  failed/features--schema-explorer.md
  *.mp4
```

## How it works

```
qa-project.yaml ──► parse docs ──► orchestrate sessions ──► agent loop ──► reports/
       │                │                  │                      │
  project config    Page objects      Docker infra            LLM + tools
  + compose.yml                       per session      (screenshot, click, type)
```

1. **Parse** — The docs source (file, directory, URL, or live site) is split into `Page` objects.
2. **Orchestrate** — Pages are grouped into sessions. Each session gets fresh containers via `docker compose up` plus the desktop sandbox.
3. **Agent loop** — For each page, the LLM receives the docs content (or a URL to navigate to), then enters a tool-use loop: it sees screenshots, issues mouse/keyboard actions, and verifies each step.
4. **Report** — Results are collected into timestamped Markdown reports with per-page pass/fail details and `.mp4` screen recordings.

### Architecture

```
src/docs_agent/
  __main__.py          CLI entry point
  project.py           Load qa-project.yaml → ProjectConfig
  parser.py            Parse docs into Page objects
  orchestrator.py      Session lifecycle, compose up/down, reports
  agent.py             Computer-use agent loop + tool dispatch
  docker_manager.py    Docker subprocess ops (compose + desktop sandbox)
  models.py            Page, PageResult, SessionConfig dataclasses
  config.py            Runtime constants
  report.py            Markdown report generation
  providers/           LLM provider abstraction (Anthropic, OpenAI)
  gcp.py / aws.py      Cloud spot-instance launchers
```
