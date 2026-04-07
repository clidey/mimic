"""Parse structured assessment output from the LLM into PageResult objects."""

from __future__ import annotations

import re

from docs_agent.config import MAX_AGENT_ITERATIONS
from docs_agent.models import FailureType, Page, PageResult, PageStatus, StepResult

# ---------------------------------------------------------------------------
# Regexes for parsing structured assessments
# ---------------------------------------------------------------------------

STATUS_RE = re.compile(r"^STATUS:\s*(PASSED|FAILED|SKIPPED)", re.IGNORECASE | re.MULTILINE)
STEP_RE = re.compile(r"^-\s+(.+?)\s*:\s*(PASS|FAIL)(?:\s*\((.+?)\))?", re.IGNORECASE | re.MULTILINE)
FAILURE_TYPE_RE = re.compile(r"FAILURE_TYPE:\s*(independent|likely_cascading|unknown)", re.IGNORECASE)
FAILURE_REASON_RE = re.compile(r"FAILURE_REASON:\s*(.+)", re.IGNORECASE)


def parse_result(
    page: Page,
    text: str,
    duration: float,
    api_calls: int,
    tokens: int,
    *,
    hit_limit: bool = False,
) -> PageResult:
    """Parse the LLM's structured final output into a PageResult."""
    status = PageStatus.FAILED  # default
    m = STATUS_RE.search(text)
    if m:
        status_str = m.group(1).upper()
        status = {"PASSED": PageStatus.PASSED, "FAILED": PageStatus.FAILED, "SKIPPED": PageStatus.SKIPPED}.get(
            status_str, PageStatus.FAILED
        )

    steps = []
    for sm in STEP_RE.finditer(text):
        steps.append(StepResult(
            description=sm.group(1).strip(),
            passed=sm.group(2).upper() == "PASS",
            error=sm.group(3),
        ))

    failure_type = None
    ft = FAILURE_TYPE_RE.search(text)
    if ft:
        failure_type = FailureType(ft.group(1).lower())

    failure_reason = None
    fr = FAILURE_REASON_RE.search(text)
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
