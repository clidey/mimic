"""Computer-use agent that tests a single documentation page."""

from __future__ import annotations

import json
import logging
import time

from mimic.assessment import STATUS_RE, parse_result
from mimic.config import (
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    MAX_AGENT_ITERATIONS,
    WRAPUP_THRESHOLD,
)
from mimic.docker_manager import start_recording, stop_recording, take_screenshot
from mimic.models import Page, PageResult, SessionState
from mimic.prompts import build_initial_message, build_system_prompt
from mimic.providers import ToolResult, get_provider
from mimic.tools import dispatch_tool

log = logging.getLogger(__name__)


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
        response = provider.send_initial(build_initial_message(page))
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
                    result_content = dispatch_tool(tc.name, dict(tc.input))
                except Exception as e:
                    log.warning("Tool %s failed: %s", tc.name, e)
                    result_content = [{"type": "text", "text": f"Tool execution failed: {type(e).__name__}: {e}"}]
                is_error = len(result_content) == 1 and result_content[0].get("text", "").startswith(
                    "Tool execution failed"
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
        if not STATUS_RE.search(final_text):
            log.info("Page %s — no assessment from CUA model, trying follow-up", page.slug)
            last_b64 = take_screenshot()
            assessment = provider.generate_assessment(last_screenshot_b64=last_b64)
            if assessment:
                final_text_parts.append(assessment)

        provider.close()
        stop_recording()

    duration = time.monotonic() - start
    final_text = "\n".join(final_text_parts)
    return parse_result(page, final_text, duration, api_calls, total_tokens, hit_limit=hit_limit)
