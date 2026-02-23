"""Provider abstraction for interchangeable LLM computer-use backends."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Normalized types shared between providers and the agent loop
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    """Result of executing a tool call, sent back to the model."""
    call_id: str
    content: list[dict]
    is_error: bool = False


@dataclass
class ProviderResponse:
    """Normalized response from a provider's send method."""
    tool_calls: list[ToolCall] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    tokens_used: int = 0
    done: bool = False


# ---------------------------------------------------------------------------
# Provider ABC
# ---------------------------------------------------------------------------

class Provider(ABC):
    """Abstract base for LLM computer-use providers."""

    @abstractmethod
    def setup(self, system_prompt: str, display_width: int, display_height: int) -> None:
        """Configure the provider with the system prompt and screen dimensions."""

    @abstractmethod
    def send_initial(self, user_message: str) -> ProviderResponse:
        """Send the first user message and return the model's response."""

    @abstractmethod
    def send_tool_results(
        self, results: list[ToolResult], nudge_text: str | None = None
    ) -> ProviderResponse:
        """Send tool execution results (and optional nudge) and return the next response."""

    def generate_assessment(self, last_screenshot_b64: str | None = None) -> str | None:
        """Generate a structured assessment after the CUA loop.

        Called when the CUA model didn't produce one itself. Returns assessment
        text or None if not supported by this provider.
        """
        return None

    def close(self) -> None:
        """Clean up any resources. Default is a no-op."""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider(name: str | None = None) -> Provider:
    """Instantiate a provider by name (defaults to AGENT_PROVIDER env var)."""
    provider_name = (name or os.environ.get("AGENT_PROVIDER", "anthropic")).lower()

    if provider_name == "anthropic":
        from docs_agent.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    if provider_name == "openai":
        from docs_agent.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()

    raise ValueError(
        f"Unknown provider: {provider_name!r}. Supported: 'anthropic', 'openai'"
    )
