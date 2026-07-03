# Mimic - a documentation QA agent
<img src="octopus.png" width="300" height="300">

Mimic is an automated QA agent that tests documentation by following instructions as a real user would — spinning up a sandboxed desktop in Docker, navigating via screenshots and mouse/keyboard, and producing Markdown reports with pass/fail results and screen recordings.

This was built to provide an extra layer of testing for our documentation because it's easy to make mistakes.

Supports **Anthropic Claude** and **OpenAI CUA**. [How it works &darr;](#how-it-works)

## Prerequisites

- **Your app runs in Docker** — the agent spins up your services via `docker-compose.yml` on a shared network with its sandbox. If your app isn't containerized yet, you'll need to containerize it first.
- **Your docs are markdown** — a folder of `.md`/`.mdx` files, or a single concatenated `llms.txt`. The agent reads these to know what to test.
- **An API key** — Anthropic or OpenAI.
- Python 3.10+, [uv](https://github.com/astral-sh/uv), and Docker installed locally (able to run a `--privileged` container). The first run pulls the prebuilt sandbox image from Docker Hub (falls back to a one-time local build if unavailable).

## Quick start

Install from PyPI (published as [`mimic-qa`](https://pypi.org/project/mimic-qa/)):

```bash
# Run without installing (recommended)
uvx --from mimic-qa mimic init my-project

# or install the CLI
pip install mimic-qa
mimic --project examples/minimal --list-pages
```

Or work from a clone (for development, or to run the bundled examples):

```bash
# 1. Clone and install
git clone https://github.com/clidey/mimic.git && cd mimic
uv sync

# 2. Add your API key
cp .env.example .env
# edit .env → set ANTHROPIC_API_KEY or OPENAI_API_KEY

# 3. Run the example
uv run mimic --project examples/minimal --list-pages
uv run mimic --project examples/minimal --page getting-started

# 4. Point it at your own docs (scaffolds a new project)
uv run mimic init my-project
```

> **First run pulls the sandbox image.** The initial run pulls the prebuilt Ubuntu + Firefox desktop image (`clidey/mimic-sandbox`) from Docker Hub, then reuses it. If the pull fails (offline, or on a fork), it falls back to building locally from the bundled Dockerfile — a few minutes, one time. Force a local build with `MIMIC_SANDBOX_BUILD=1`, or point at a different image with `MIMIC_SANDBOX_IMAGE=...`. You'll need Docker running with permission to start a `--privileged` container.

Results appear in `reports/` — a `summary.md`, per-page pass/fail details, and `.mp4` screen recordings. The repo includes `examples/minimal/` (nginx + 2 doc pages) and `examples/whodb/` (80 pages, multiple sessions) to try out.

Ready to test your own docs? See [Create your own project](#create-your-own-project) below.

## Create your own project

```bash
uv run mimic init my-project
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
2. **`docker-compose.yml`** — add your app's services. They must join the `mimic-net` network (use Docker hostnames like `http://myapp:3000`, not `localhost`).
3. **`docs/`** — add one `.md`/`.mdx` file per page you want tested. Or point `docs:` in the yaml at your existing docs folder (e.g. `docs: ../my-app/docs/`) — no need to copy files.

Then run it:

```bash
uv run mimic --project my-project --list-pages   # verify docs parse correctly
uv run mimic --project my-project                 # run full QA suite
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
    networks: [mimic-net]

networks:
  mimic-net:
    name: mimic-net
    external: true   # agent creates this network; compose joins it
```

The `external: true` network is required — the agent creates `mimic-net` so your services and the desktop sandbox share the same network.

### Providers

**Anthropic** (default) — `claude-sonnet-5` with the computer-use beta API. Single model handles actions and assessment. Can run against the first-party Anthropic API or **Amazon Bedrock** (`ANTHROPIC_BACKEND=bedrock`, uses ambient AWS creds + `AWS_REGION`). Note: on Bedrock only some models support the computer tool — `anthropic.claude-opus-4-7` works (and is the Bedrock default); `claude-sonnet-5`/`claude-opus-4-8` currently reject it.

**OpenAI** — two-model approach: `gpt-5.5`'s native `computer` tool for desktop actions, `gpt-5.2` for structured assessment. The agent pre-launches Firefox and a terminal so the CUA model can focus on browser tasks where it performs best.

```bash
AGENT_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=sk-ant-...      # if using anthropic (api backend)
OPENAI_API_KEY=sk-proj-...        # if using openai

# Optional
ANTHROPIC_BACKEND=api             # or bedrock
ANTHROPIC_MODEL=claude-sonnet-5   # override per backend
ANTHROPIC_EFFORT=medium           # low | medium | high | xhigh | max
OPENAI_EFFORT=medium              # low | medium | high | xhigh
```

### Cloud runners

Launch on a GCP spot VM or AWS EC2 spot instance:

```bash
uv run mimic-cloud --cloud gcp --provider anthropic
uv run mimic-cloud --cloud aws --provider openai
uv run mimic-cloud --cloud gcp --wait          # launch + poll + download results
uv run mimic-cloud --cloud aws --cleanup        # kill a stuck instance
```

`--provider` overrides `AGENT_PROVIDER` in `.env`, so you can keep both API keys configured and pick per-run. Auth uses your local CLI credentials (`gcloud auth` / `aws configure`), but project, bucket, and region must be set explicitly in `.env`:

```bash
# GCP (requires gcloud CLI)
GCP_PROJECT=my-gcp-project
GCS_BUCKET=my-bucket

# AWS (requires aws CLI)
AWS_REGION=us-east-1
S3_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=AKIA...         # or use AWS_IAM_INSTANCE_PROFILE instead
AWS_SECRET_ACCESS_KEY=...

# What to run on the VM
MIMIC_ARGS=--project examples/whodb
```

## Troubleshooting

**Docker daemon not running**
```
Error: Cannot connect to the Docker daemon
```
Start Docker Desktop or run `sudo systemctl start docker`.

**API key not set**
```
Error: ANTHROPIC_API_KEY is required in .env
```
Copy `.env.example` to `.env` and fill in your API key. The agent loads `.env` automatically.

**Firefox fails to launch in sandbox**
If the desktop container starts but Firefox doesn't appear, check the container logs:
```bash
docker logs mimic-desktop
```
The sandbox uses the Mozilla PPA build of Firefox (not snap). If the image is stale, rebuild:
```bash
docker rmi mimic-desktop && uv run mimic --project examples/minimal --page getting-started
```

**Screen recording is empty or missing**
ffmpeg records inside the container at `/tmp/recording.mp4`. If recordings are missing:
- Check that ffmpeg is installed in the sandbox: `docker exec mimic-desktop which ffmpeg`
- Check the display is active: `docker exec mimic-desktop xdpyinfo -display :1`

**Desktop container times out**
```
RuntimeError: Desktop container did not become ready
```
The Xvfb display failed to start within 30 seconds. This usually means Docker is out of resources — try `docker system prune` to free space.

**Pages marked NOT_APPLICABLE**
Pages in sessions with `needs_desktop: false` are intentionally skipped. These are informational pages (changelogs, API references) that can't be tested interactively.

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

## License

[MIT](LICENSE) © Clidey, Inc.
