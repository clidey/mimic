"""Data models for the documentation QA agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PageStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class FailureType(Enum):
    INDEPENDENT = "independent"
    LIKELY_CASCADING = "likely_cascading"
    UNKNOWN = "unknown"


@dataclass
class Page:
    slug: str
    filename: str
    content: str
    line_start: int
    line_end: int


@dataclass
class StepResult:
    description: str
    passed: bool
    error: str | None = None


@dataclass
class PageResult:
    page: Page
    status: PageStatus
    steps: list[StepResult] = field(default_factory=list)
    failure_reason: str | None = None
    failure_type: FailureType | None = None
    duration: float = 0.0
    api_calls: int = 0
    tokens_used: int = 0


@dataclass
class SessionState:
    """Tracks failures across pages in a session for cascading-failure detection."""

    failures: list[dict[str, str]] = field(default_factory=list)

    def record_failure(self, page_slug: str, reason: str) -> None:
        self.failures.append({"page_slug": page_slug, "reason": reason})

    def to_context(self) -> list[dict[str, str]]:
        return list(self.failures)


@dataclass
class SessionConfig:
    name: str
    page_slugs: list[str]
    needs_desktop: bool = True
    compose_profiles: list[str] = field(default_factory=list)
