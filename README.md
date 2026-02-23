# Mimic - a documentation QA agent
<img src="octopus.png" width="300" height="300">

Mimic is an automated QA agent that tests documentation by following instructions as a real user would — spinning up a sandboxed desktop in Docker, navigating via screenshots and mouse/keyboard, and producing Markdown reports with pass/fail results and screen recordings.

This was built to provide an extra layer of testing for our documentation because it's easy to make mistakes.

Supports **Anthropic Claude** and **OpenAI CUA**. [How it works &darr;](#how-it-works)

## Prerequisites

- **Your app runs in Docker** — the agent spins up your services via `docker-compose.yml` on a shared network with its sandbox. If your app isn't containerized yet, you'll need to containerize it first.
- **Your docs are markdown** — a folder of `.md`/`.mdx` files, or a single concatenated `llms.txt`. The agent reads these to know what to test.
- **An API key** — Anthropic or OpenAI.
- Python 3.10+, [uv](https://github.com/astral-sh/uv), Docker installed locally.

## Quick start

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

Results appear in `reports/` — a `summary.md`, per-page pass/fail details, and `.mp4` screen recordings. The repo includes `examples/minimal/` (nginx + 2 doc pages) and `examples/whodb/` (80 pages, multiple sessions) to try out.

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
2. **`docker-compose.yml`** — add your app's services. They must join the `docsagent-net` network (use Docker hostnames like `http://myapp:3000`, not `localhost`).
3. **`docs/`** — add one `.md`/`.mdx` file per page you want tested. Or point `docs:` in the yaml at your existing docs folder (e.g. `docs: ../my-app/docs/`) — no need to copy files.

Then run it:

```bash
uv run docs-agent --project my-project --list-pages   # verify docs parse correctly
uv run docs-agent --project my-project                 # run full QA suite
```

## Reference

### `qa-project.yaml`

```yaml
name: my-project
docs: docs/                # folder of .md/.mdx files (recommended)

# Free-text injected into the LLM system prompt.
# Tell it what's running and how to reach it (use Docker network hostnames, not localhost).
environment: |
  - My app is running at http://myapp:3000
  - PostgreSQL at db:5432 (user=admin, password=secret, db=mydb)

sessions:
  - name: Getting Started
    pages: [installation, quickstart, guides/*]

  - name: Premium Features
    pages: [features/billing, features/teams]
    compose_profiles: [stripe]
```

### Sessions

Sessions group pages that share the same infrastructure. Each session gets a **fresh set of Docker containers** — compose services are torn down and restarted between sessions. This matters when:

- Different pages need different services running (e.g. one session needs Stripe, another doesn't)
- You want a clean state between groups of tests (no leftover data from previous pages)
- Some pages don't need Docker at all (API reference, changelogs)

Session fields:
- **`pages`** — list of page slugs to test. Slugs match filenames minus extension. Globs work (`features/*`, `guides/**`).
- **`compose_profiles`** — Docker Compose profiles to activate for this session (maps to `docker compose --profile`). Use for optional services.
- **`needs_desktop: false`** — skip Docker entirely, mark pages as NOT_APPLICABLE. Useful for reference pages that can't be tested interactively.

**If you omit `sessions`**, pages are auto-grouped by directory prefix — all pages under `features/` become one session, all under `guides/` become another, etc. This is fine for simple projects.

### Docs sources

**Directory** (recommended) — point `docs:` at a folder of `.md`/`.mdx` files. Works with Docusaurus, MkDocs, VitePress, Mintlify, or any markdown source. Each file becomes one test page; the filename (minus extension) is the slug.

```yaml
docs: docs/                     # local folder in the project
docs: ../my-app/docs/           # existing docs folder elsewhere
```

**Concatenated file** — a single file with `# filename.mdx` headers separating pages. Useful if your docs site publishes an `llms.txt`:

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

```yaml
docs: assets/llms.txt               # local file
docs: https://example.com/llms.txt  # or a remote URL
```

> **Browse mode:** Set `docs_url: https://docs.example.com` to have the LLM navigate to each page in Firefox instead of reading content from the prompt. Requires listing pages in `sessions`. Can be combined with `docs` to give the LLM both content and a live URL.

### `docker-compose.yml`

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

The `external: true` network is required — the agent creates `docsagent-net` so your services and the desktop sandbox share the same network.

### Providers

**Anthropic** (default) — `claude-sonnet-4-6` with the computer-use beta API. Single model handles actions and assessment.

**OpenAI** — two-model approach: `computer-use-preview` for desktop actions, `gpt-5.2` for structured assessment. The agent pre-launches Firefox and a terminal so the CUA model can focus on browser tasks where it performs best.

```bash
AGENT_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=sk-ant-...      # if using anthropic
OPENAI_API_KEY=sk-proj-...        # if using openai
```

### Cloud runners

Launch on a GCP spot VM or AWS EC2 spot instance:

```bash
uv run docs-agent-gcp [--wait] [--cleanup]
uv run docs-agent-aws [--wait] [--cleanup]
```

`--wait` polls until done and downloads results. `--cleanup` kills a stuck instance.

Auth uses your local CLI credentials (`gcloud auth` / `aws configure`), but project, bucket, and region must be set explicitly in `.env`:

```bash
# GCP
GCP_PROJECT=my-gcp-project       # required — no default from gcloud config
GCS_BUCKET=my-bucket              # required

# AWS
AWS_REGION=us-east-1              # required — no default from aws config
S3_BUCKET=my-bucket               # required
AWS_ACCESS_KEY_ID=AKIA...         # or use AWS_IAM_INSTANCE_PROFILE instead
AWS_SECRET_ACCESS_KEY=...

# What to run on the VM
DOCS_AGENT_ARGS=--project examples/whodb --session "Core Features"
```

## How it works

```
qa-project.yaml ──► parse docs ──► orchestrate sessions ──► agent loop ──► reports/
       │                │                  │                      │
  project config    Page objects      Docker infra            LLM + tools
  + compose.yml                       per session      (screenshot, click, type)
```

1. **Parse** — Docs source is split into `Page` objects.
2. **Orchestrate** — Pages are grouped into sessions. Each session gets fresh containers via `docker compose up` plus a desktop sandbox.
3. **Agent loop** — The LLM receives docs content, then enters a tool-use loop: screenshots, mouse/keyboard actions, and step verification.
4. **Report** — Results are collected into timestamped Markdown reports with per-page pass/fail details and `.mp4` recordings.
