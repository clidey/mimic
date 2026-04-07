"""OpenAI CUA (Computer Use Agent) provider."""

from __future__ import annotations

import logging
from typing import Any

import openai

from docs_agent.config import ASSESSMENT_FORMAT, OPENAI_ASSESSMENT_MODEL, OPENAI_MAX_TOKENS, OPENAI_MODEL
from docs_agent.providers import Provider, ProviderResponse, ToolCall, ToolResult

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
    """Provider backed by the OpenAI Responses API with computer-use-preview."""

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
        self._tools = [
            {
                "type": "computer_use_preview",
                "display_width": display_width,
                "display_height": display_height,
                "environment": "linux",
            },
        ]

    def send_initial(self, user_message: str) -> ProviderResponse:
        from docs_agent.docker_manager import take_screenshot

        b64 = take_screenshot()
        content: list[dict] = [{"type": "input_text", "text": user_message}]
        if b64:
            content.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64}",
            })

        response = self._client.responses.create(  # type: ignore[call-overload]
            model=OPENAI_MODEL,
            instructions=self._system,
            input=[{"role": "user", "content": content}],
            tools=self._tools,
            truncation="auto",
            reasoning={"summary": "concise"},
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        self._previous_response_id = response.id
        return self._parse_response(response)

    def send_tool_results(
        self, results: list[ToolResult], nudge_text: str | None = None
    ) -> ProviderResponse:
        items: list[dict] = []
        for r in results:
            output = self._build_output(r)
            items.append(output)

        if nudge_text:
            items.append({"role": "user", "content": [{"type": "input_text", "text": nudge_text}]})

        response = self._client.responses.create(  # type: ignore[call-overload]
            model=OPENAI_MODEL,
            previous_response_id=self._previous_response_id,
            input=items,
            tools=self._tools,
            truncation="auto",
            reasoning={"summary": "concise"},
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        self._previous_response_id = response.id
        return self._parse_response(response)

    def generate_assessment(self, last_screenshot_b64: str | None = None) -> str | None:
        """Call gpt-5.2 to produce a structured assessment from the CUA action log."""
        if not self._action_log:
            return None

        log.info("Generating assessment via %s (%d actions logged)", OPENAI_ASSESSMENT_MODEL, len(self._action_log))

        action_text = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(self._action_log))
        prompt = _ASSESSMENT_PROMPT.format(system_prompt=self._system, action_log=action_text)

        messages: list[dict] = []
        content: list[dict] = [{"type": "text", "text": prompt}]
        if last_screenshot_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{last_screenshot_b64}"},
            })
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
        """Build a computer_call_output item from a ToolResult.

        Per the docs, the output field is a single image object, and
        pending_safety_checks from the previous response must be acknowledged.
        """
        screenshot_b64: str | None = None
        text_parts: list[str] = []
        for block in result.content:
            if block.get("type") == "image" and block.get("source", {}).get("type") == "base64":
                screenshot_b64 = block["source"]["data"]
            elif block.get("type") == "text":
                text_parts.append(block["text"])

        output: dict = {
            "type": "computer_call_output",
            "call_id": result.call_id,
        }

        # Acknowledge any pending safety checks from the previous response
        if self._pending_safety_checks:
            output["acknowledged_safety_checks"] = [
                sc["id"] for sc in self._pending_safety_checks
            ]
            self._pending_safety_checks = []

        if screenshot_b64:
            output["output"] = {
                "type": "computer_screenshot",
                "image_url": f"data:image/png;base64,{screenshot_b64}",
            }
        elif text_parts:
            # Text-only result (e.g. bash output) — still need a screenshot
            from docs_agent.docker_manager import take_screenshot
            fresh_b64 = take_screenshot()
            if fresh_b64:
                output["output"] = {
                    "type": "computer_screenshot",
                    "image_url": f"data:image/png;base64,{fresh_b64}",
                }

        return output

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse an OpenAI Responses API response into a ProviderResponse."""
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        pending_safety: list[dict] = []

        for item in response.output:
            if item.type == "computer_call":
                normalized = self._normalize_action(item.action)
                tool_calls.append(ToolCall(
                    id=item.call_id,
                    name=normalized["tool_name"],
                    input=normalized["input"],
                ))
                self._action_log.append(self._describe_action(item.action))
                for check in getattr(item, "pending_safety_checks", []):
                    log.info("OpenAI safety check: %s — %s", check.code, check.message)
                    pending_safety.append({"id": check.id, "code": check.code, "message": check.message})
            elif item.type == "reasoning":
                summary = getattr(item, "summary", None)
                if summary:
                    for s in summary:
                        log.debug("CUA reasoning: %s", getattr(s, "text", str(s))[:300])
            elif item.type == "text":
                text_parts.append(item.text)

        tokens = 0
        if hasattr(response, "usage") and response.usage:
            tokens = (getattr(response.usage, "input_tokens", 0) or 0) + (
                getattr(response.usage, "output_tokens", 0) or 0
            )

        done = not tool_calls
        if done and text_parts:
            log.info("CUA model finished with text: %s", " | ".join(t[:200] for t in text_parts))

        # Store safety checks — will be acknowledged in the next _build_output call
        self._pending_safety_checks = pending_safety

        return ProviderResponse(
            tool_calls=tool_calls,
            text_parts=text_parts,
            tokens_used=tokens,
            done=done,
        )

    @staticmethod
    def _describe_action(action: Any) -> str:
        """Produce a human-readable one-liner describing a CUA action."""
        t = action.type
        if t == "click":
            return f"click({action.button}) at ({action.x}, {action.y})"
        if t == "double_click":
            return f"double_click at ({action.x}, {action.y})"
        if t == "type":
            text = action.text
            if len(text) > 80:
                text = text[:77] + "..."
            return f'type "{text}"'
        if t == "keypress":
            keys = action.keys if hasattr(action, "keys") else []
            return f"keypress {'+'.join(keys)}"
        if t == "scroll":
            return f"scroll at ({action.x}, {action.y}) dy={getattr(action, 'scroll_y', 0)}"
        if t == "screenshot":
            return "screenshot"
        if t == "drag":
            path = action.path
            start = path[0] if path else None
            end = path[-1] if len(path) > 1 else start
            return f"drag ({getattr(start, 'x', '?')},{getattr(start, 'y', '?')}) -> ({getattr(end, 'x', '?')},{getattr(end, 'y', '?')})"
        if t == "wait":
            return f"wait {getattr(action, 'duration', '?')}s"
        if t == "move":
            return f"move to ({action.x}, {action.y})"
        return f"{t} (unknown)"

    def _normalize_action(self, action: Any) -> dict:
        """Map an OpenAI CUA action to an Anthropic-style tool name + input dict."""
        action_type = action.type

        if action_type == "click":
            button_map = {"left": "left_click", "right": "right_click", "middle": "middle_click"}
            anthropic_action = button_map.get(action.button, "left_click")
            return {
                "tool_name": "computer",
                "input": {"action": anthropic_action, "coordinate": [action.x, action.y]},
            }

        if action_type == "double_click":
            return {
                "tool_name": "computer",
                "input": {"action": "double_click", "coordinate": [action.x, action.y]},
            }

        if action_type == "type":
            return {
                "tool_name": "computer",
                "input": {"action": "type", "text": action.text},
            }

        if action_type == "keypress":
            keys = action.keys if hasattr(action, "keys") else []
            key_str = "+".join(keys)
            return {
                "tool_name": "computer",
                "input": {"action": "key", "text": key_str},
            }

        if action_type == "scroll":
            scroll_x = getattr(action, "scroll_x", 0) or 0
            scroll_y = getattr(action, "scroll_y", 0) or 0
            if abs(scroll_y) >= abs(scroll_x):
                direction = "down" if scroll_y > 0 else "up"
                amount = max(1, abs(scroll_y) // 30)
            else:
                direction = "right" if scroll_x > 0 else "left"
                amount = max(1, abs(scroll_x) // 30)
            return {
                "tool_name": "computer",
                "input": {
                    "action": "scroll",
                    "coordinate": [action.x, action.y],
                    "scroll_direction": direction,
                    "scroll_amount": amount,
                },
            }

        if action_type == "drag":
            path = action.path
            start = path[0] if path else None
            end = path[-1] if len(path) > 1 else start
            sx = getattr(start, "x", 0) if start else 0
            sy = getattr(start, "y", 0) if start else 0
            ex = getattr(end, "x", 0) if end else 0
            ey = getattr(end, "y", 0) if end else 0
            return {
                "tool_name": "computer",
                "input": {
                    "action": "left_click_drag",
                    "start_coordinate": [sx, sy],
                    "coordinate": [ex, ey],
                },
            }

        if action_type == "screenshot":
            return {
                "tool_name": "computer",
                "input": {"action": "screenshot"},
            }

        if action_type == "wait":
            return {
                "tool_name": "computer",
                "input": {"action": "wait", "duration": getattr(action, "duration", 2)},
            }

        if action_type == "move":
            return {
                "tool_name": "computer",
                "input": {"action": "mouse_move", "coordinate": [action.x, action.y]},
            }

        log.warning("Unknown OpenAI CUA action type: %s", action_type)
        return {
            "tool_name": "computer",
            "input": {"action": action_type},
        }
