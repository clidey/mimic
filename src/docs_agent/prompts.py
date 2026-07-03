"""System prompt builders for the computer-use agent."""

from __future__ import annotations

import json
import os

from docs_agent.config import ASSESSMENT_FORMAT, MAX_AGENT_ITERATIONS
from docs_agent.models import Page, SessionState


def is_openai_provider() -> bool:
    return os.environ.get("AGENT_PROVIDER", "anthropic").lower() == "openai"


def build_system_prompt(
    page: Page,
    session_state: SessionState,
    environment: str,
    docs_url: str | None = None,
) -> str:
    if is_openai_provider():
        return _build_cua_prompt(page, session_state, environment, docs_url)
    return _build_anthropic_prompt(page, session_state, environment, docs_url)


def build_initial_message(page: Page | None = None) -> str:
    """Build the first user message — different for CUA vs Anthropic."""
    if is_openai_provider() and page:
        return (
            f"Here is your task. Follow these documentation steps on the desktop:\n\n"
            f"{page.content}\n\n"
            f"Start now with step 1. Firefox and a terminal are already open on screen. "
            f"Do NOT stop or ask for confirmation — complete ALL steps above autonomously. "
            f"After each action, take a screenshot and continue to the next step."
        )
    return (
        "Please begin testing this documentation page now. "
        "Start by taking a screenshot to see the current desktop state."
    )


# ---------------------------------------------------------------------------
# Anthropic prompt
# ---------------------------------------------------------------------------


def _build_anthropic_prompt(
    page: Page,
    session_state: SessionState,
    environment: str,
    docs_url: str | None = None,
) -> str:
    """System prompt for Anthropic Claude — full assessment format included."""
    failures_json = json.dumps(session_state.to_context(), indent=2) if session_state.failures else "[]"

    env_block = ""
    if environment.strip():
        env_block = f"\nENVIRONMENT:\n- You are on an Ubuntu desktop with Firefox, a terminal, and standard CLI tools.\n{environment}\n"
    else:
        env_block = "\nENVIRONMENT:\n- You are on an Ubuntu desktop with Firefox, a terminal, and standard CLI tools.\n"

    has_content = bool(page.content.strip())
    browse_url = f"{docs_url.rstrip('/')}/{page.slug}" if docs_url else None

    if has_content and browse_url:
        body = f"""\
INSTRUCTIONS:
1. Read the documentation page content below carefully.
2. The live page is also available at {browse_url} — open it in Firefox.
3. Follow EVERY instruction, step by step. Do NOT skip steps. Open browsers,
   click UI elements, run terminal commands — do exactly what the docs say a
   user should do.
4. After each step, take a screenshot to verify the result.
5. If a step involves cloud services (AWS, GCP, Azure) that cannot be tested
   locally, note it as skipped but continue with remaining steps.
6. When you have finished testing all steps (or when told to wrap up), you MUST
   provide your assessment in this exact format. This is critical — the
   assessment MUST appear in your final message:

{ASSESSMENT_FORMAT}

PREVIOUS FAILURES IN THIS SESSION (for cascading-failure context):
{failures_json}

If your failure seems caused by a prior failure above, mark FAILURE_TYPE as likely_cascading.

---

DOCUMENTATION PAGE: {page.filename}

{page.content}"""

    elif browse_url:
        body = f"""\
INSTRUCTIONS:
1. Open Firefox and navigate to {browse_url}
2. Read the documentation page in the browser.
3. Follow EVERY instruction on the page, step by step. Do NOT skip steps.
   Click UI elements, run terminal commands — do exactly what the docs say
   a user should do.
4. After each step, take a screenshot to verify the result.
5. If a step involves cloud services (AWS, GCP, Azure) that cannot be tested
   locally, note it as skipped but continue with remaining steps.
6. When you have finished testing all steps (or when told to wrap up), you MUST
   provide your assessment in this exact format. This is critical — the
   assessment MUST appear in your final message:

{ASSESSMENT_FORMAT}

PREVIOUS FAILURES IN THIS SESSION (for cascading-failure context):
{failures_json}

If your failure seems caused by a prior failure above, mark FAILURE_TYPE as likely_cascading.

---

DOCUMENTATION PAGE: {page.slug}
(Navigate to {browse_url} to read and test this page)"""

    else:
        body = f"""\
INSTRUCTIONS:
1. Read the documentation page content below carefully.
2. Follow EVERY instruction, step by step. Do NOT skip steps. Open browsers,
   click UI elements, run terminal commands — do exactly what the docs say a
   user should do.
3. After each step, take a screenshot to verify the result.
4. If a step involves cloud services (AWS, GCP, Azure) that cannot be tested
   locally, note it as skipped but continue with remaining steps.
5. When you have finished testing all steps (or when told to wrap up), you MUST
   provide your assessment in this exact format. This is critical — the
   assessment MUST appear in your final message:

{ASSESSMENT_FORMAT}

PREVIOUS FAILURES IN THIS SESSION (for cascading-failure context):
{failures_json}

If your failure seems caused by a prior failure above, mark FAILURE_TYPE as likely_cascading.

---

DOCUMENTATION PAGE: {page.filename}

{page.content}"""

    return f"""\
You are a documentation QA agent. Your job is to test a documentation page by
following every instruction exactly as described, as if you were a new user.
{env_block}
TURN BUDGET: You have at most {MAX_AGENT_ITERATIONS} tool-use turns to complete this test.
Plan accordingly. You MUST produce your structured assessment before running out
of turns. If you are notified that you are running low, stop testing immediately
and produce your assessment based on what you have observed so far.

{body}
"""


# ---------------------------------------------------------------------------
# OpenAI CUA prompt
# ---------------------------------------------------------------------------


def _build_cua_prompt(
    page: Page,
    session_state: SessionState,
    environment: str,
    docs_url: str | None = None,
) -> str:
    """System prompt for OpenAI CUA — action-oriented, no assessment format.

    Key differences from the Anthropic prompt:
    - Explicit desktop navigation guidance (how to open Firefox, terminal)
    - No structured assessment format (gpt-5.2 handles that separately)
    - Shorter, more directive — CUA responds better to clear action instructions
    """
    has_content = bool(page.content.strip())
    browse_url = f"{docs_url.rstrip('/')}/{page.slug}" if docs_url else None

    env_lines = ""
    if environment.strip():
        env_lines = environment

    if has_content and browse_url:
        task_block = f"""\
TASK: Test the documentation page below by following every instruction on a live desktop.

The live page is also at {browse_url} — open it in Firefox to follow along.

DOCUMENTATION PAGE: {page.filename}

{page.content}"""

    elif browse_url:
        task_block = f"""\
TASK: Navigate to {browse_url} in Firefox, read the documentation page, and
follow every instruction on a live desktop.

DOCUMENTATION PAGE: {page.slug}"""

    else:
        task_block = f"""\
TASK: Test the documentation page below by following every instruction on a live desktop.

DOCUMENTATION PAGE: {page.filename}

{page.content}"""

    return f"""\
You are a documentation QA tester on a Linux (Ubuntu) desktop.
Your job is to follow every step in the documentation page exactly.

DESKTOP ENVIRONMENT:
- Firefox is ALREADY OPEN on the desktop — just click its window and use the address bar.
- A terminal (xterm) is ALREADY OPEN — click it and type commands directly.
- Do NOT try to launch new applications. Use the ones already on screen.
- Do NOT use Alt+F2 or application menus. Everything you need is already running.
{env_lines}

HOW TO WORK:
1. Click the Firefox window and type the URL in the address bar to navigate.
   To run commands, click the terminal window and type them.
2. Follow EVERY step in the documentation. Execute commands, click UI elements,
   fill in forms — do exactly what the docs tell a user to do.
3. After each action, take a screenshot to verify it worked before moving on.
4. If something fails, try once more, then move to the next step.
5. Keep going until you have attempted every step in the documentation.

{task_block}
"""
