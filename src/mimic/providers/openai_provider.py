"""OpenAI computer-use provider (gpt-5.5 native `computer` tool)."""

from __future__ import annotations

import logging
from typing import Any

import openai

from mimic.config import (
    ASSESSMENT_FORMAT,
    OPENAI_ASSESSMENT_MODEL,
    OPENAI_EFFORT,
    OPENAI_MAX_TOKENS,
    OPENAI_MODEL,
)
from mimic.providers import Provider, ProviderResponse, ToolCall, ToolResult

log = logging.getLogger(__name__)

_ASSESSMENT_PROMPT = f"""\
You are evaluating a documentation QA test session. A computer-use agent was given
a documentation page and asked to follow each instruction step by step on a live
desktop. Below is the system prompt the agent received (which contains the page
content), a log of every action the agent performed, and a final screenshot showing
the desktop state when the session ended.

Analyze the action log and screenshot, then produce a structured assessment.
For each step in the documentation, determine whether it was completed based
on the actions taken and the final screen state.

You MUST produce your output in EXACTLY this plain-text format (not JSON):

{ASSESSMENT_FORMAT}

Rules:
- STATUS is PASSED only if ALL steps passed.
- Each step line must start with "- " and end with ": PASS" or ": FAIL (reason)".
- FAILURE_TYPE: "independent" if this page failed on its own, "likely_cascading"
  if caused by a prior page's failure, "unknown" if unclear.
- Be concise. One line per step.

=== SYSTEM PROMPT (contains doc page) ===
{{system_prompt}}

=== ACTION LOG ===
{{action_log}}
"""


class OpenAIProvider(Provider):
    """Provider backed by the OpenAI Responses API with the gpt-5.5 `computer` tool.

    gpt-5.5 batches actions: each ``computer_call`` output item carries an
    ``actions`` list (the legacy singular ``action`` field is always null), and
    the API expects exactly one ``computer_call_output`` per ``call_id``. This
    provider therefore emits a single normalized ``ToolCall`` per ``computer_call``
    whose input is ``{"actions": [...]}``; the tool dispatcher executes the whole
    batch and returns one screenshot reflecting the final desktop state.
    """

    def __init__(self) -> None:
        self._client: openai.OpenAI = openai.OpenAI(max_retries=2)
        self._previous_response_id: str | None = None
        self._display_width: int = 1280
        self._display_height: int = 800
        self._system: str = ""
        self._tools: list[dict] = []
        self._action_log: list[str] = []
        self._pending_safety_checks: list[dict] = []

    def setup(self, system_prompt: str, display_width: int, display_height: int) -> None:
        self._system = system_prompt
        self._display_width = display_width
        self._display_height = display_height
        # gpt-5.5's native computer tool takes no display/environment fields.
        self._tools = [{"type": "computer"}]

    def send_initial(self, user_message: str) -> ProviderResponse:
        from mimic.docker_manager import take_screenshot

        b64 = take_screenshot()
        content: list[dict] = [{"type": "input_text", "text": user_message}]
        if b64:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{b64}",
                    "detail": "original",
                }
            )

        response = self._client.responses.create(  # type: ignore[call-overload]
            model=OPENAI_MODEL,
            instructions=self._system,
            input=[{"role": "user", "content": content}],
            tools=self._tools,
            truncation="auto",
            reasoning={"summary": "concise", "effort": OPENAI_EFFORT},
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        self._previous_response_id = response.id
        return self._parse_response(response)

    def send_tool_results(self, results: list[ToolResult], nudge_text: str | None = None) -> ProviderResponse:
        items: list[dict] = [self._build_output(r) for r in results]

        if nudge_text:
            items.append({"role": "user", "content": [{"type": "input_text", "text": nudge_text}]})

        response = self._client.responses.create(  # type: ignore[call-overload]
            model=OPENAI_MODEL,
            previous_response_id=self._previous_response_id,
            input=items,
            tools=self._tools,
            truncation="auto",
            reasoning={"summary": "concise", "effort": OPENAI_EFFORT},
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        self._previous_response_id = response.id
        return self._parse_response(response)

    def generate_assessment(self, last_screenshot_b64: str | None = None) -> str | None:
        """Call the assessment model to produce a structured assessment from the action log."""
        if not self._action_log:
            return None

        log.info("Generating assessment via %s (%d actions logged)", OPENAI_ASSESSMENT_MODEL, len(self._action_log))

        action_text = "\n".join(f"  {i + 1}. {a}" for i, a in enumerate(self._action_log))
        prompt = _ASSESSMENT_PROMPT.format(system_prompt=self._system, action_log=action_text)

        messages: list[dict] = []
        content: list[dict] = [{"type": "text", "text": prompt}]
        if last_screenshot_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{last_screenshot_b64}"},
                }
            )
        messages.append({"role": "user", "content": content})

        try:
            resp = self._client.chat.completions.create(
                model=OPENAI_ASSESSMENT_MODEL,
                messages=messages,  # type: ignore[arg-type]
                max_completion_tokens=4096,
            )
            text = resp.choices[0].message.content or ""
            log.info("Assessment generated (%d chars)", len(text))
            return text
        except Exception as e:
            log.error("Assessment generation failed: %s", e)
            return (
                "STATUS: FAILED\n"
                "STEPS:\n"
                "- Assessment generation : FAIL (follow-up LLM call failed)\n"
                f"FAILURE_TYPE: independent\n"
                f"FAILURE_REASON: Assessment could not be generated: {type(e).__name__}: {e}"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_output(self, result: ToolResult) -> dict:
        """Build a single computer_call_output item from a ToolResult.

        The API expects one output per call_id; a computer_call may have batched
        several actions, but the ToolResult carries the single post-batch
        screenshot. Pending safety checks from the previous response are
        acknowledged here.
        """
        screenshot_b64: str | None = None
        for block in result.content:
            if block.get("type") == "image" and block.get("source", {}).get("type") == "base64":
                screenshot_b64 = block["source"]["data"]

        output: dict = {
            "type": "computer_call_output",
            "call_id": result.call_id,
        }

        # Acknowledge any pending safety checks from the previous response.
        if self._pending_safety_checks:
            output["acknowledged_safety_checks"] = [sc["id"] for sc in self._pending_safety_checks]
            self._pending_safety_checks = []

        # A screenshot is always expected back; fetch a fresh one if the tool
        # result carried only text (e.g. a bash-only action).
        if screenshot_b64 is None:
            from mimic.docker_manager import take_screenshot

            screenshot_b64 = take_screenshot()

        if screenshot_b64:
            output["output"] = {
                "type": "computer_screenshot",
                "image_url": f"data:image/png;base64,{screenshot_b64}",
                "detail": "original",
            }

        return output

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse an OpenAI Responses API response into a ProviderResponse.

        Each ``computer_call`` becomes one ToolCall whose input bundles all of
        the call's batched actions under an ``actions`` key.
        """
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        pending_safety: list[dict] = []

        for item in response.output:
            if item.type == "computer_call":
                dumped = item.model_dump()
                actions = dumped.get("actions") or []
                normalized = [self._normalize_action(a) for a in actions]
                tool_calls.append(
                    ToolCall(
                        id=dumped["call_id"],
                        name="computer",
                        input={"actions": normalized},
                    )
                )
                for a in actions:
                    self._action_log.append(self._describe_action(a))
                for check in dumped.get("pending_safety_checks") or []:
                    log.info("OpenAI safety check: %s — %s", check.get("code"), check.get("message"))
                    pending_safety.append(check)
            elif item.type == "reasoning":
                for s in getattr(item, "summary", None) or []:
                    log.debug("CUA reasoning: %s", getattr(s, "text", str(s))[:300])
            elif item.type == "message":
                for block in getattr(item, "content", None) or []:
                    text = getattr(block, "text", None)
                    if text:
                        text_parts.append(text)
            elif item.type == "text":
                text_parts.append(item.text)

        tokens = 0
        if getattr(response, "usage", None):
            tokens = (getattr(response.usage, "input_tokens", 0) or 0) + (
                getattr(response.usage, "output_tokens", 0) or 0
            )

        done = not tool_calls
        if done and text_parts:
            log.info("CUA model finished with text: %s", " | ".join(t[:200] for t in text_parts))

        # Store safety checks — acknowledged in the next _build_output call.
        self._pending_safety_checks = pending_safety

        return ProviderResponse(
            tool_calls=tool_calls,
            text_parts=text_parts,
            tokens_used=tokens,
            done=done,
        )

    @staticmethod
    def _describe_action(action: dict) -> str:
        """Produce a human-readable one-liner describing a CUA action dict."""
        t = action.get("type", "unknown")
        x, y = action.get("x"), action.get("y")
        if t == "click":
            mods = "+".join(action.get("keys") or [])
            prefix = f"{mods}+" if mods else ""
            return f"click({prefix}{action.get('button')}) at ({x}, {y})"
        if t == "double_click":
            return f"double_click at ({x}, {y})"
        if t == "type":
            text = action.get("text", "")
            if len(text) > 80:
                text = text[:77] + "..."
            return f'type "{text}"'
        if t == "keypress":
            return f"keypress {'+'.join(action.get('keys') or [])}"
        if t == "scroll":
            dy = action.get("scroll_y", action.get("scrollY", 0))
            return f"scroll at ({x}, {y}) dy={dy}"
        if t == "screenshot":
            return "screenshot"
        if t == "drag":
            path = action.get("path") or []
            start = _point(path[0]) if path else (None, None)
            end = _point(path[-1]) if len(path) > 1 else start
            return f"drag {start} -> {end}"
        if t == "wait":
            return f"wait {action.get('duration', '?')}s"
        if t == "move":
            return f"move to ({x}, {y})"
        return f"{t} (unknown)"

    def _normalize_action(self, action: dict) -> dict:
        """Map an OpenAI CUA action dict to an Anthropic-style computer input dict."""
        t = action.get("type")
        x, y = action.get("x", 0), action.get("y", 0)
        modifiers = action.get("keys") or []

        if t == "click":
            button_map = {"left": "left_click", "right": "right_click", "middle": "middle_click"}
            inp: dict = {"action": button_map.get(action.get("button") or "left", "left_click"), "coordinate": [x, y]}
            if modifiers:
                inp["modifiers"] = modifiers
            return inp

        if t == "double_click":
            return {"action": "double_click", "coordinate": [x, y]}

        if t == "type":
            return {"action": "type", "text": action.get("text", "")}

        if t == "keypress":
            return {"action": "key", "text": "+".join(action.get("keys") or [])}

        if t == "scroll":
            scroll_x = action.get("scroll_x", action.get("scrollX", 0)) or 0
            scroll_y = action.get("scroll_y", action.get("scrollY", 0)) or 0
            if abs(scroll_y) >= abs(scroll_x):
                direction = "down" if scroll_y > 0 else "up"
                amount = max(1, abs(scroll_y) // 30)
            else:
                direction = "right" if scroll_x > 0 else "left"
                amount = max(1, abs(scroll_x) // 30)
            return {
                "action": "scroll",
                "coordinate": [x, y],
                "scroll_direction": direction,
                "scroll_amount": amount,
            }

        if t == "drag":
            path = action.get("path") or []
            sx, sy = _point(path[0]) if path else (0, 0)
            ex, ey = _point(path[-1]) if len(path) > 1 else (sx, sy)
            return {"action": "left_click_drag", "start_coordinate": [sx, sy], "coordinate": [ex, ey]}

        if t == "screenshot":
            return {"action": "screenshot"}

        if t == "wait":
            return {"action": "wait", "duration": action.get("duration", 2)}

        if t == "move":
            return {"action": "mouse_move", "coordinate": [x, y]}

        log.warning("Unknown OpenAI CUA action type: %s", t)
        return {"action": t or "screenshot"}


def _point(p: Any) -> tuple[Any, Any]:
    """Extract (x, y) from a drag path point (dict or [x, y] pair)."""
    if isinstance(p, dict):
        return p.get("x", 0), p.get("y", 0)
    if isinstance(p, list | tuple) and len(p) >= 2:
        return p[0], p[1]
    return 0, 0
