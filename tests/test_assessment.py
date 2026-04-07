"""Tests for docs_agent.assessment — structured output parsing."""

from __future__ import annotations

import textwrap

from docs_agent.assessment import parse_result
from docs_agent.models import FailureType, Page, PageStatus


def _page(slug: str = "test-page") -> Page:
    return Page(slug=slug, filename=f"{slug}.mdx", content="test content", line_start=0, line_end=0)


class TestParseResult:
    def test_parses_passed(self) -> None:
        text = textwrap.dedent("""\
            STATUS: PASSED
            STEPS:
            - Open homepage : PASS
            - Click login : PASS
            FAILURE_TYPE: unknown
            FAILURE_REASON: n/a
        """)

        result = parse_result(_page(), text, duration=10.0, api_calls=5, tokens=1000)

        assert result.status == PageStatus.PASSED
        assert len(result.steps) == 2
        assert all(s.passed for s in result.steps)
        assert result.duration == 10.0
        assert result.api_calls == 5
        assert result.tokens_used == 1000

    def test_parses_failed_with_reason(self) -> None:
        text = textwrap.dedent("""\
            STATUS: FAILED
            STEPS:
            - Open homepage : PASS
            - Click login : FAIL (button not found)
            FAILURE_TYPE: independent
            FAILURE_REASON: Login button was missing from the page
        """)

        result = parse_result(_page(), text, duration=20.0, api_calls=10, tokens=2000)

        assert result.status == PageStatus.FAILED
        assert len(result.steps) == 2
        assert result.steps[0].passed is True
        assert result.steps[1].passed is False
        assert result.steps[1].error == "button not found"
        assert result.failure_type == FailureType.INDEPENDENT
        assert "Login button" in result.failure_reason

    def test_parses_cascading_failure(self) -> None:
        text = textwrap.dedent("""\
            STATUS: FAILED
            STEPS:
            - Connect to DB : FAIL (connection refused)
            FAILURE_TYPE: likely_cascading
            FAILURE_REASON: Database from previous session not available
        """)

        result = parse_result(_page(), text, duration=5.0, api_calls=3, tokens=500)

        assert result.failure_type == FailureType.LIKELY_CASCADING

    def test_parses_skipped(self) -> None:
        text = "STATUS: SKIPPED\nSTEPS:\nFAILURE_TYPE: unknown\nFAILURE_REASON: Cloud-only page"

        result = parse_result(_page(), text, duration=1.0, api_calls=1, tokens=100)

        assert result.status == PageStatus.SKIPPED

    def test_defaults_to_failed_when_no_status(self) -> None:
        text = "The model did not produce a structured assessment."

        result = parse_result(_page(), text, duration=30.0, api_calls=15, tokens=5000)

        assert result.status == PageStatus.FAILED

    def test_hit_limit_without_assessment(self) -> None:
        text = "Still testing step 3..."

        result = parse_result(
            _page(), text, duration=120.0, api_calls=40, tokens=50000, hit_limit=True
        )

        assert result.status == PageStatus.FAILED
        assert result.failure_type == FailureType.INDEPENDENT
        assert "iteration budget" in result.failure_reason

    def test_hit_limit_with_assessment_uses_assessment(self) -> None:
        text = "STATUS: PASSED\nSTEPS:\n- Step 1 : PASS\n"

        result = parse_result(
            _page(), text, duration=120.0, api_calls=40, tokens=50000, hit_limit=True
        )

        # When the assessment is present, hit_limit doesn't override it
        assert result.status == PageStatus.PASSED

    def test_case_insensitive_status(self) -> None:
        text = "STATUS: passed\nSTEPS:\n- step : pass\n"

        result = parse_result(_page(), text, duration=1.0, api_calls=1, tokens=100)

        assert result.status == PageStatus.PASSED
        assert result.steps[0].passed is True
