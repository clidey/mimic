"""Anthropic Claude computer-use provider."""

from __future__ import annotations

from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaOutputConfigParam

from docs_agent.config import (
    ANTHROPIC_BACKEND,
    ANTHROPIC_BETA,
    ANTHROPIC_EFFORT,
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
)
from docs_agent.providers import Provider, ProviderResponse, ToolCall, ToolResult


def _build_client() -> anthropic.Anthropic | anthropic.AnthropicBedrockMantle:
    """Construct the Claude client for the configured backend.

    "bedrock" routes through Amazon Bedrock (uses ambient AWS credentials and
    AWS_REGION); "api" uses the first-party Anthropic API (ANTHROPIC_API_KEY).
    Both expose the same beta.messages.create surface.
    """
    if ANTHROPIC_BACKEND == "bedrock":
        return anthropic.AnthropicBedrockMantle(max_retries=2)
    return anthropic.Anthropic(max_retries=2)


class AnthropicProvider(Provider):
    """Provider backed by the Anthropic messages-beta API (direct or via Bedrock)."""

    def __init__(self) -> None:
        self._client = _build_client()
        self._system: str = ""
        self._messages: list[dict] = []
        self._tools: list[dict] = []

    def setup(self, system_prompt: str, display_width: int, display_height: int) -> None:
        self._system = system_prompt
        self._tools = [
            {
                "type": "computer_20251124",
                "name": "computer",
                "display_width_px": display_width,
                "display_height_px": display_height,
                "display_number": 1,
            },
            {"type": "bash_20250124", "name": "bash"},
            {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
        ]

    def send_initial(self, user_message: str) -> ProviderResponse:
        self._messages = [{"role": "user", "content": user_message}]
        return self._call()

    def send_tool_results(self, results: list[ToolResult], nudge_text: str | None = None) -> ProviderResponse:
        content: list[dict] = [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in results
        ]
        if nudge_text:
            content.append({"type": "text", "text": nudge_text})
        self._messages.append({"role": "user", "content": content})
        return self._call()

    # ------------------------------------------------------------------

    def _call(self) -> ProviderResponse:
        response = self._client.beta.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=self._system,
            messages=self._messages,  # type: ignore[arg-type]
            tools=self._tools,  # type: ignore[arg-type]
            betas=[ANTHROPIC_BETA],
            output_config=BetaOutputConfigParam(effort=cast(Any, ANTHROPIC_EFFORT)),
        )

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
            elif block.type == "text":
                text_parts.append(block.text)

        # Append raw assistant message (Anthropic SDK objects) to maintain conversation
        self._messages.append({"role": "assistant", "content": response.content})

        tokens = response.usage.input_tokens + response.usage.output_tokens
        done = not tool_calls or response.stop_reason == "end_turn"

        return ProviderResponse(
            tool_calls=tool_calls,
            text_parts=text_parts,
            tokens_used=tokens,
            done=done,
        )
