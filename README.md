# Mimic - a documentation QA agent
<img src="octopus.png">

Mimic is an automated QA agent that tests documentation by following instructions as a real user would — spinning up a sandboxed desktop in Docker, navigating via screenshots and mouse/keyboard, and producing Markdown reports with pass/fail results and screen recordings.

Supports **Anthropic Claude** and **OpenAI CUA**. [How it works &darr;](#how-it-works)

## Quick start

**Requirements:** Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker

```bash
# 1. Clone and install
git clone <repo-url> && cd qa-agent
uv sync

# 2. Add your API key
cp .env.example .env
# edit .env → set ANTHROPIC_API_KEY or OPENAI_API_KEY

# 3. Run the example
uv run docs-agent --project examples/minimal --list-pages
uv run docs-agent --project examples/minimal --page getting-started
```

Results appear in `reports/` — a `summary.md`, per-page pass/fail details, and `.mp4` screen recordings.

## Create your own project

```bash
uv run docs-agent init my-project
```

This scaffolds:

```
my-project/
  qa-project.yaml       # project config — edit name, environment, sessions
  docker-compose.yml    # add your app's services here
  docs/
    getting-started.mdx # sample doc page
```

**Edit the three files:**

1. **`qa-project.yaml`** — set your app's name and describe the running environment (Docker hostnames, ports, credentials the LLM needs to know about).
2. **`docker-compose.yml`** — add your app's services. They must join the `docsagent-net` network.
3. **`docs/`** — add one `.md`/`.mdx` file per page you want tested. Or point `docs:` in the yaml at your existing docs folder (e.g. `docs: ../my-app/docs/`) — no need to copy files.

Then run it:

```bash
uv run docs-agent --project my-project --list-pages   # verify docs parse correctly
uv run docs-agent --project my-project                 # run full QA suite
```

See the [reference](#reference) below for all config options, docs source modes, and cloud runners.

## Walkthrough: the minimal example

The repo includes `examples/minimal/` — an nginx server with two doc pages:

```
examples/minimal/
  qa-project.yaml       # points at docs/, describes environment
  docker-compose.yml    # nginx on docsagent-net
  docs/
    getting-started.mdx # "open Firefox, go to http://web:80, verify welcome page"
    server-status.mdx   # "run curl, check for 200 OK"
```

```bash
# List what the agent will test
uv run docs-agent --project examples/minimal --list-pages
uv run docs-agent --project examples/minimal --list-sessions

# Test a single page (starts Docker, launches sandbox, runs the agent)
uv run docs-agent --project examples/minimal --page getting-started

# Check results
cat reports/*/summary.md
```

## Reference

### `qa-project.yaml`

```yaml
name: my-project
docs: docs/llms.txt       # see "Docs sources" below

# Free-text injected into the LLM system prompt.
# Tell it what's running and how to reach it (use Docker network hostnames, not localhost).
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
| `docs/` | **Directory** | Reads each `.md`/`.mdx` file; slug = relative path minus extension. Point this at your existing docs folder — no need to copy files. |
| `assets/llms.txt` | **File** | Concatenated file with `# filename.mdx` headers (see [format below](#concatenated-file-format)) |
| `https://.../llms.txt` | **URL** | Fetches remote concatenated file, same format as File |

**Directory mode** is the simplest — just point `docs:` at any folder of markdown files:

```yaml
docs: docs/                     # local folder in the project
docs: ../my-app/docs/           # or an existing docs folder elsewhere
docs: /absolute/path/to/docs/   # absolute paths work too
```

A fourth **Browse** mode uses `docs_url` instead — the LLM navigates to `{docs_url}/{slug}` in Firefox and reads the page on screen:

```yaml
docs_url: https://docs.example.com
sessions:   # required — no content to auto-discover from
  - name: Getting Started
    pages: [installation, quickstart]
```

You can combine both — `docs` for prompt content, `docs_url` so the LLM also opens the live page:

```yaml
docs: assets/llms.txt
docs_url: https://docs.example.com
```

### Works with most doc generators

The agent doesn't care how your docs were built — it just needs markdown files or a live URL. Most generators already keep source as `.md`/`.mdx` files in a directory, so **directory mode** works out of the box:

| Generator | Setup |
|-----------|-------|
| **Docusaurus** | `docs: docs/` — point at the `docs/` source directory |
| **MkDocs / Material** | `docs: docs/` — same, markdown source files |
| **VitePress** | `docs: docs/` — same |
| **Mintlify** | `docs: docs/` — `.mdx` files work directly |
| **GitBook** | `docs_url: https://your-site.gitbook.io` — browse mode (list pages in sessions) |
| **Notion** | Export as markdown → `docs: exported/` |
| **Any live site** | `docs_url: https://docs.example.com` — browse mode |

For sites without markdown source access, use **browse mode** — the agent opens each page in Firefox and follows the instructions it reads on screen.

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

Standard compose file for your app services. The agent manages the network and its own desktop container — you just define your services and join `docsagent-net`:

```yaml
services:
  myapp:
    image: myorg/myapp:latest
    networks: [docsagent-net]

networks:
  docsagent-net:
    name: docsagent-net
    external: true   # agent creates this network; compose joins it
```

> **Important:** The `external: true` network is required. The agent creates `docsagent-net` before running compose so that your services and the agent's desktop sandbox share the same network. Without it, the LLM can't reach your app.

### Tips

- Use **Docker network hostnames** (`http://myapp:3000`), not `localhost` — the LLM runs Firefox inside a container on the Docker network.
- **`compose_profiles`** map to `docker compose --profile`. Use for optional services that only some sessions need.
- **Globs** in page lists (e.g. `guides/*`) expand against parsed slugs.
- Always run `--list-pages` first to verify your docs parse correctly before spending API credits.

### Cloud runners

Launch on a GCP spot VM or AWS EC2 spot instance. Both package the repo, upload to a storage bucket, launch a VM, run the agent, upload results, and shut down.

```bash
uv run docs-agent-gcp [--wait] [--cleanup]
uv run docs-agent-aws [--wait] [--cleanup]
```

`--wait` polls until the VM finishes and downloads results. `--cleanup` terminates a stuck instance.

Results upload to `{bucket}/results/<timestamp>/`.

#### Cloud configuration

Set cloud variables in `.env` alongside your API key:

**GCP** — requires `gcloud` CLI authenticated locally:

```bash
GCP_PROJECT=my-gcp-project
GCS_BUCKET=my-bucket
# optional: GCP_ZONE, GCP_MACHINE_TYPE, GCP_SPOT (defaults: us-central1-a, e2-standard-4, true)
```

**AWS** — requires `aws` CLI configured locally:

```bash
AWS_REGION=us-east-1
S3_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=AKIA...        # for S3 access on the instance
AWS_SECRET_ACCESS_KEY=...        # (or use AWS_IAM_INSTANCE_PROFILE instead)
# optional: AWS_INSTANCE_TYPE, AWS_SPOT (defaults: m5.xlarge, true)
```

**Common:**

```bash
DOCS_AGENT_ARGS=--project examples/whodb --session "Core Features"
```

`DOCS_AGENT_ARGS` is passed to `docs-agent` on the VM. Set it to target a specific project/session.

### Environment variables

Set in `.env` (copy from `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `AGENT_PROVIDER` | No | `anthropic` (default) or `openai` |
| `ANTHROPIC_API_KEY` | If using anthropic | Anthropic API key |
| `OPENAI_API_KEY` | If using openai | OpenAI API key |
| `DOCS_AGENT_ARGS` | No | CLI args passed through on cloud VMs |
| `GCP_PROJECT` | For GCP runner | GCP project ID |
| `GCS_BUCKET` | For GCP runner | GCS bucket name |
| `AWS_REGION` | For AWS runner | AWS region |
| `S3_BUCKET` | For AWS runner | S3 bucket name |

### Provider notes

**Anthropic** (default) — uses `claude-sonnet-4-6` with the computer-use beta API. Single model handles both desktop actions and structured assessment output.

**OpenAI** — uses a two-model approach:
- `computer-use-preview` for desktop actions (clicking, typing, navigating)
- `gpt-5.2` for generating the structured pass/fail assessment after the CUA session ends

The OpenAI CUA model performs best on browser-based tasks. The agent automatically pre-launches Firefox and a terminal on the desktop so the model can focus on navigation rather than app discovery. Reports include which provider and models were used.

### Reports

```
reports/2026-02-23_14-30-00_full-run/
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
2. **Orchestrate** — Pages are grouped into sessions. Each session gets fresh containers via `docker compose up` plus a desktop sandbox.
3. **Agent loop** — For each page, the LLM receives the docs content (or a URL to navigate to), then enters a tool-use loop: it sees screenshots, issues mouse/keyboard actions, and verifies each step.
4. **Report** — Results are collected into timestamped Markdown reports with per-page pass/fail details and `.mp4` screen recordings.

### Architecture

```
src/docs_agent/
  __main__.py          CLI entry point (+ init command)
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

examples/
  minimal/             Minimal example (nginx + 2 doc pages)
  whodb/               Full example (80 pages, multiple sessions)
```
