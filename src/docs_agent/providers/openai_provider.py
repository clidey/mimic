"""OpenAI CUA (Computer Use Agent) provider."""

from __future__ import annotations

import logging

import openai

from docs_agent.config import OPENAI_MAX_TOKENS, OPENAI_MODEL
from docs_agent.providers import Provider, ProviderResponse, ToolCall, ToolResult

log = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    """Provider backed by the OpenAI Responses API with computer-use-preview."""

    def __init__(self) -> None:
        self._client: openai.OpenAI | None = None
        self._previous_response_id: str | None = None
        self._display_width: int = 1280
        self._display_height: int = 800
        self._system: str = ""
        self._tools: list[dict] = []

    def setup(self, system_prompt: str, display_width: int, display_height: int) -> None:
        self._client = openai.OpenAI()
        self._system = system_prompt
        self._display_width = display_width
        self._display_height = display_height
        self._tools = [
            {
                "type": "computer_use_preview",
                "display_width": display_width,
                "display_height": display_height,
                "environment": "ubuntu",
            },
        ]

    def send_initial(self, user_message: str) -> ProviderResponse:
        # OpenAI CUA requires an initial screenshot
        from docs_agent.docker_manager import take_screenshot

        b64 = take_screenshot()
        content: list[dict] = [{"type": "input_text", "text": user_message}]
        if b64:
            content.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64}",
            })

        response = self._client.responses.create(
            model=OPENAI_MODEL,
            instructions=self._system,
            input=content,
            tools=self._tools,
            truncation="auto",
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
            items.append({"type": "input_text", "text": nudge_text})

        response = self._client.responses.create(
            model=OPENAI_MODEL,
            previous_response_id=self._previous_response_id,
            input=items,
            tools=self._tools,
            truncation="auto",
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        self._previous_response_id = response.id
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_output(self, result: ToolResult) -> dict:
        """Build a computer_call_output item from a ToolResult."""
        # Find the screenshot (base64 image) in the result content
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
        if screenshot_b64:
            output["output"] = {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{screenshot_b64}",
            }
        # If there's only text (e.g. from bash execution routed through computer),
        # we still need to provide a screenshot
        elif text_parts:
            from docs_agent.docker_manager import take_screenshot

            fresh_b64 = take_screenshot()
            if fresh_b64:
                output["output"] = {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{fresh_b64}",
                }

        return output

    def _parse_response(self, response: object) -> ProviderResponse:
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
                # Collect pending safety checks
                for check in getattr(item, "pending_safety_checks", []):
                    log.info("OpenAI safety check: %s — %s", check.code, check.message)
                    pending_safety.append({"id": check.id, "code": check.code, "message": check.message})
            elif item.type == "text":
                text_parts.append(item.text)

        tokens = 0
        if hasattr(response, "usage") and response.usage:
            tokens = (getattr(response.usage, "input_tokens", 0) or 0) + (
                getattr(response.usage, "output_tokens", 0) or 0
            )

        done = not tool_calls

        # Store safety checks to acknowledge in next request
        self._pending_safety_checks = pending_safety

        return ProviderResponse(
            tool_calls=tool_calls,
            text_parts=text_parts,
            tokens_used=tokens,
            done=done,
        )

    def _normalize_action(self, action: object) -> dict:
        """Map an OpenAI CUA action to an Anthropic-style tool name + input dict.

        This lets the existing _dispatch_tool() in agent.py handle all actions
        without any changes.
        """
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
            # OpenAI sends list of keys like ["ctrl", "c"], Anthropic expects "ctrl+c"
            keys = action.keys if hasattr(action, "keys") else []
            key_str = "+".join(keys)
            return {
                "tool_name": "computer",
                "input": {"action": "key", "text": key_str},
            }

        if action_type == "scroll":
            # OpenAI gives pixel deltas; convert to xdotool click counts
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
            start = path[0] if path else {"x": 0, "y": 0}
            end = path[-1] if len(path) > 1 else start
            return {
                "tool_name": "computer",
                "input": {
                    "action": "left_click_drag",
                    "start_coordinate": [start["x"], start["y"]],
                    "coordinate": [end["x"], end["y"]],
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

        # Fallback — pass through as-is and let _dispatch_tool handle the error
        log.warning("Unknown OpenAI CUA action type: %s", action_type)
        return {
            "tool_name": "computer",
            "input": {"action": action_type},
        }
