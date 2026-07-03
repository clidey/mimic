"""Tests for mimic.models — data classes and enums."""

from __future__ import annotations

from mimic.models import FailureType, PageStatus, SessionState


class TestSessionState:
    def test_starts_empty(self) -> None:
        state = SessionState()

        assert state.failures == []
        assert state.to_context() == []

    def test_records_failure(self) -> None:
        state = SessionState()
        state.record_failure("install", "Docker not running")

        assert len(state.failures) == 1
        assert state.failures[0]["page_slug"] == "install"
        assert state.failures[0]["reason"] == "Docker not running"

    def test_multiple_failures(self) -> None:
        state = SessionState()
        state.record_failure("a", "error 1")
        state.record_failure("b", "error 2")

        ctx = state.to_context()
        assert len(ctx) == 2
        assert ctx[0]["page_slug"] == "a"
        assert ctx[1]["page_slug"] == "b"

    def test_to_context_returns_copy(self) -> None:
        state = SessionState()
        state.record_failure("a", "err")

        ctx = state.to_context()
        ctx.clear()

        assert len(state.failures) == 1  # original unaffected


class TestEnums:
    def test_page_status_values(self) -> None:
        assert PageStatus.PASSED.value == "passed"
        assert PageStatus.FAILED.value == "failed"
        assert PageStatus.SKIPPED.value == "skipped"
        assert PageStatus.NOT_APPLICABLE.value == "not_applicable"

    def test_failure_type_values(self) -> None:
        assert FailureType.INDEPENDENT.value == "independent"
        assert FailureType.LIKELY_CASCADING.value == "likely_cascading"
        assert FailureType.UNKNOWN.value == "unknown"
