"""Computer-use agent that tests a single documentation page."""

from __future__ import annotations

import json
import logging
import os
import re
import time

from docs_agent.config import (
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    MAX_AGENT_ITERATIONS,
    WRAPUP_THRESHOLD,
)
from docs_agent.docker_manager import exec_in_desktop, start_recording, stop_recording, take_screenshot, xdotool
from docs_agent.models import FailureType, Page, PageResult, PageStatus, SessionState, StepResult
from docs_agent.providers import ToolResult, get_provider

log = logging.getLogger(__name__)

_ASSESSMENT_FORMAT = """\
STATUS: PASSED | FAILED | SKIPPED
STEPS:
- [step description] : PASS | FAIL ([error if failed])
- [step description] : PASS | FAIL ([error if failed])
FAILURE_TYPE: independent | likely_cascading | unknown
FAILURE_REASON: [explanation if failed]"""


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _is_openai_provider() -> bool:
    return os.environ.get("AGENT_PROVIDER", "anthropic").lower() == "openai"


def build_system_prompt(
    page: Page,
    session_state: SessionState,
    environment: str,
    docs_url: str | None = None,
) -> str:
    if _is_openai_provider():
        return _build_cua_prompt(page, session_state, environment, docs_url)
    return _build_anthropic_prompt(page, session_state, environment, docs_url)


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

{_ASSESSMENT_FORMAT}

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

{_ASSESSMENT_FORMAT}

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

{_ASSESSMENT_FORMAT}

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


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _screenshot_result(b64: str | None) -> list[dict]:
    """Build a tool_result content block from a screenshot, handling failures."""
    if b64:
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]
    return [{"type": "text", "text": "Screenshot failed — the desktop display may be unavailable."}]


def _execute_computer_tool(action: str, **kwargs: object) -> list[dict]:
    """Execute a computer-use action and return tool_result content blocks."""
    if action == "screenshot":
        return _screenshot_result(take_screenshot())

    if action == "left_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 1")
    elif action == "right_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 3")
    elif action == "double_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click --repeat 2 1")
    elif action == "triple_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click --repeat 3 1")
    elif action == "middle_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 2")
    elif action == "mouse_move":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y}")
    elif action == "type":
        text = kwargs["text"]
        # Escape single quotes for shell
        escaped = str(text).replace("'", "'\\''")
        xdotool(f"type --delay 12 '{escaped}'")
    elif action == "key":
        key = str(kwargs["text"])
        xdotool(f"key {key}")
    elif action == "scroll":
        x, y = kwargs["coordinate"]
        direction = kwargs.get("scroll_direction", kwargs.get("direction", "down"))
        amount = int(kwargs.get("scroll_amount", kwargs.get("amount", 3)))
        button_map = {"up": 4, "down": 5, "left": 6, "right": 7}
        button = button_map.get(direction, 5)
        xdotool(f"mousemove {x} {y}")
        xdotool(f"click --repeat {amount} {button}")
    elif action == "left_click_drag":
        sx, sy = kwargs["start_coordinate"]
        ex, ey = kwargs["coordinate"]
        xdotool(f"mousemove {sx} {sy} mousedown 1")
        xdotool(f"mousemove {ex} {ey} mouseup 1")
    elif action == "wait":
        secs = int(kwargs.get("duration", 2))
        time.sleep(secs)
    else:
        return [{"type": "text", "text": f"Unknown computer action: {action}"}]

    # For non-screenshot actions, auto-take a screenshot to show result
    return _screenshot_result(take_screenshot())


def _execute_bash_tool(command: str) -> list[dict]:
    """Execute a bash command inside the desktop container."""
    output = exec_in_desktop(command, timeout=60)
    return [{"type": "text", "text": output or "(no output)"}]


def _execute_text_editor_tool(command: str, **kwargs: object) -> list[dict]:
    """Execute a text editor command inside the desktop container."""
    path = kwargs.get("path", "")
    if command == "view":
        output = exec_in_desktop(f"cat '{path}'")
    elif command == "create":
        content = str(kwargs.get("file_text", ""))
        escaped = content.replace("'", "'\\''")
        exec_in_desktop(f"mkdir -p $(dirname '{path}') && printf '%s' '{escaped}' > '{path}'")
        output = f"Created {path}"
    elif command == "str_replace":
        old = str(kwargs.get("old_str", ""))
        new = str(kwargs.get("new_str", ""))
        old_esc = old.replace("'", "'\\''")
        new_esc = new.replace("'", "'\\''")
        exec_in_desktop(
            f"python3 -c \"\nimport pathlib\np = pathlib.Path('{path}')\nt = p.read_text()\nassert t.count('''{old_esc}''') == 1, f'Expected 1 occurrence, found {{t.count(\\\"\\\"\\\"{ old_esc }\\\"\\\"\\\")}}'\np.write_text(t.replace('''{old_esc}''', '''{new_esc}''', 1))\nprint('Replaced successfully')\n\""
        )
        output = f"Replaced in {path}"
    elif command == "insert":
        line = int(kwargs.get("insert_line", 0))
        text = str(kwargs.get("new_str", ""))
        text_esc = text.replace("'", "'\\''")
        exec_in_desktop(
            f"python3 -c \"\nimport pathlib\np = pathlib.Path('{path}')\nlines = p.read_text().splitlines(True)\nlines.insert({line}, '''{text_esc}\\n''')\np.write_text(''.join(lines))\nprint('Inserted at line {line}')\n\""
        )
        output = f"Inserted at line {line} in {path}"
    else:
        output = f"Unknown editor command: {command}"
    return [{"type": "text", "text": output}]


def _dispatch_tool(tool_name: str, tool_input: dict) -> list[dict]:
    """Route a tool call to the appropriate handler."""
    if tool_name == "computer":
        action = tool_input.pop("action", "")
        return _execute_computer_tool(action, **tool_input)
    elif tool_name == "bash":
        return _execute_bash_tool(tool_input.get("command", ""))
    elif tool_name == "str_replace_based_edit_tool":
        cmd = tool_input.pop("command", "")
        return _execute_text_editor_tool(cmd, **tool_input)
    return [{"type": "text", "text": f"Unknown tool: {tool_name}"}]


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _initial_message(page: Page | None = None) -> str:
    """Build the first user message — different for CUA vs Anthropic."""
    if _is_openai_provider() and page:
        # CUA model needs the task steps in the user message, not just
        # the system prompt — it treats instructions as background context
        # but the user message as the actual thing to do.
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


def test_page(
    page: Page,
    session_state: SessionState,
    environment: str,
    docs_url: str | None = None,
) -> PageResult:
    """Run the computer-use agent on a single documentation page."""
    provider = get_provider()
    system = build_system_prompt(page, session_state, environment, docs_url=docs_url)
    provider.setup(system, DISPLAY_WIDTH, DISPLAY_HEIGHT)

    total_tokens = 0
    api_calls = 0
    start = time.monotonic()
    hit_limit = False
    final_text_parts: list[str] = []

    start_recording()

    try:
        api_calls += 1
        response = provider.send_initial(_initial_message(page))
        total_tokens += response.tokens_used
        final_text_parts.extend(response.text_parts)

        for iteration in range(MAX_AGENT_ITERATIONS):
            log.info("Page %s — iteration %d/%d", page.slug, iteration + 1, MAX_AGENT_ITERATIONS)

            if response.done:
                break

            # Execute tools and build results
            tool_results: list[ToolResult] = []
            for tc in response.tool_calls:
                log.debug("Tool call: %s(%s)", tc.name, json.dumps(tc.input)[:200])
                try:
                    result_content = _dispatch_tool(tc.name, dict(tc.input))
                except Exception as e:
                    log.warning("Tool %s failed: %s", tc.name, e)
                    result_content = [{"type": "text", "text": f"Tool execution failed: {type(e).__name__}: {e}"}]
                is_error = (
                    len(result_content) == 1
                    and result_content[0].get("text", "").startswith("Tool execution failed")
                )
                tool_results.append(ToolResult(call_id=tc.id, content=result_content, is_error=is_error))

            # Build wrap-up nudge if approaching the limit
            nudge: str | None = None
            remaining = MAX_AGENT_ITERATIONS - iteration - 1
            if iteration + 1 == WRAPUP_THRESHOLD:
                log.info("Page %s — injecting wrap-up nudge (%d turns remaining)", page.slug, remaining)
                nudge = (
                    f"IMPORTANT: You have {remaining} turns remaining out of {MAX_AGENT_ITERATIONS}. "
                    "You are running low on turns. Finish your current step, then STOP testing and "
                    "immediately produce your structured assessment (STATUS/STEPS/FAILURE_TYPE/FAILURE_REASON) "
                    "based on what you have tested so far. Do NOT use any more tool calls after writing "
                    "the assessment."
                )

            api_calls += 1
            response = provider.send_tool_results(tool_results, nudge)
            total_tokens += response.tokens_used
            final_text_parts.extend(response.text_parts)
        else:
            hit_limit = True
            log.warning("Page %s — hit max iterations (%d)", page.slug, MAX_AGENT_ITERATIONS)
    finally:
        # If the CUA model never produced a structured assessment, ask a
        # text model to generate one from the action log + final screenshot.
        final_text = "\n".join(final_text_parts)
        if not _STATUS_RE.search(final_text):
            log.info("Page %s — no assessment from CUA model, trying follow-up", page.slug)
            last_b64 = take_screenshot()
            assessment = provider.generate_assessment(last_screenshot_b64=last_b64)
            if assessment:
                final_text_parts.append(assessment)

        provider.close()
        stop_recording()

    duration = time.monotonic() - start
    final_text = "\n".join(final_text_parts)
    return _parse_result(page, final_text, duration, api_calls, total_tokens, hit_limit=hit_limit)


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

_STATUS_RE = re.compile(r"^STATUS:\s*(PASSED|FAILED|SKIPPED)", re.IGNORECASE | re.MULTILINE)
_STEP_RE = re.compile(r"^-\s+(.+?)\s*:\s*(PASS|FAIL)(?:\s*\((.+?)\))?", re.IGNORECASE | re.MULTILINE)
_FAILURE_TYPE_RE = re.compile(r"FAILURE_TYPE:\s*(independent|likely_cascading|unknown)", re.IGNORECASE)
_FAILURE_REASON_RE = re.compile(r"FAILURE_REASON:\s*(.+)", re.IGNORECASE)


def _parse_result(page: Page, text: str, duration: float, api_calls: int, tokens: int, *, hit_limit: bool = False) -> PageResult:
    """Parse Claude's structured final output into a PageResult."""
    status = PageStatus.FAILED  # default
    m = _STATUS_RE.search(text)
    if m:
        status_str = m.group(1).upper()
        status = {"PASSED": PageStatus.PASSED, "FAILED": PageStatus.FAILED, "SKIPPED": PageStatus.SKIPPED}.get(
            status_str, PageStatus.FAILED
        )

    steps = []
    for sm in _STEP_RE.finditer(text):
        steps.append(StepResult(
            description=sm.group(1).strip(),
            passed=sm.group(2).upper() == "PASS",
            error=sm.group(3),
        ))

    failure_type = None
    ft = _FAILURE_TYPE_RE.search(text)
    if ft:
        failure_type = FailureType(ft.group(1).lower())

    failure_reason = None
    fr = _FAILURE_REASON_RE.search(text)
    if fr:
        failure_reason = fr.group(1).strip()

    if hit_limit and not m:
        status = PageStatus.FAILED
        failure_type = FailureType.INDEPENDENT
        failure_reason = (
            f"Page exceeded the {MAX_AGENT_ITERATIONS}-turn iteration budget without "
            "producing an assessment. This page may be too long or complex and should "
            "be shortened or split into smaller pages."
        )

    return PageResult(
        page=page,
        status=status,
        steps=steps,
        failure_reason=failure_reason,
        failure_type=failure_type,
        duration=duration,
        api_calls=api_calls,
        tokens_used=tokens,
    )
