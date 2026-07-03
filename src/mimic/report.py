"""Generate Markdown reports from test results."""

from __future__ import annotations

import datetime
import os
from collections.abc import Callable
from pathlib import Path

from mimic.models import FailureType, PageResult, PageStatus, StepResult

# Type alias for the `w = lines.append` pattern used throughout
_LineAppender = Callable[[str], None]

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def generate_report(results: list[PageResult], run_name: str | None = None) -> Path:
    """Write a report directory and return its path.

    Structure:
        reports/<timestamp>_<run_name>/
            summary.md
            failed/<slug>.md
            passed/<slug>.md
            skipped/<slug>.md
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dir_name = f"{ts}_{run_name}" if run_name else ts
    run_dir = REPORTS_DIR / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)

    passed = [r for r in results if r.status == PageStatus.PASSED]
    failed = [r for r in results if r.status == PageStatus.FAILED]
    skipped = [r for r in results if r.status == PageStatus.SKIPPED]
    na = [r for r in results if r.status == PageStatus.NOT_APPLICABLE]

    # Write individual page reports into status subdirectories
    for r in failed:
        _write_page_file(run_dir / "failed", r)
    for r in passed:
        _write_page_file(run_dir / "passed", r)
    for r in skipped + na:
        _write_page_file(run_dir / "skipped", r)

    # Write consolidated summary
    summary_path = run_dir / "summary.md"
    summary_path.write_text(_build_summary(results, ts, passed, failed, skipped, na))

    return run_dir


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------


def _build_summary(
    results: list[PageResult],
    ts: str,
    passed: list[PageResult],
    failed: list[PageResult],
    skipped: list[PageResult],
    na: list[PageResult],
) -> str:
    total_duration = sum(r.duration for r in results)
    total_tokens = sum(r.tokens_used for r in results)
    total_api_calls = sum(r.api_calls for r in results)

    lines: list[str] = []
    w = lines.append

    w(f"# Documentation QA Report — {ts}")
    w("")
    w("## Summary")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total pages | {len(results)} |")
    w(f"| Passed | {len(passed)} |")
    w(f"| Failed | {len(failed)} |")
    w(f"| Skipped | {len(skipped)} |")
    w(f"| Not applicable | {len(na)} |")
    w(f"| Duration | {_fmt_duration(total_duration)} |")
    w(f"| API calls | {total_api_calls} |")
    w(f"| Tokens used | {total_tokens:,} |")

    provider = os.environ.get("AGENT_PROVIDER", "anthropic")
    if provider == "anthropic":
        from mimic.config import ANTHROPIC_MODEL

        w(f"| Provider | {provider} ({ANTHROPIC_MODEL}) |")
    elif provider == "openai":
        from mimic.config import OPENAI_ASSESSMENT_MODEL, OPENAI_MODEL

        w(f"| Provider | {provider} ({OPENAI_MODEL} + {OPENAI_ASSESSMENT_MODEL}) |")
    else:
        w(f"| Provider | {provider} |")

    w("")

    if failed:
        w("## Failed Pages")
        w("")
        for r in failed:
            slug_file = slug_to_filename(r.page.slug)
            w(f"- [{r.page.slug}](failed/{slug_file}.md)")
            if r.failure_reason:
                w(f"  - {r.failure_reason}")
        w("")

    if passed:
        w("## Passed Pages")
        w("")
        for r in passed:
            slug_file = slug_to_filename(r.page.slug)
            w(f"- [{r.page.slug}](passed/{slug_file}.md) — {_fmt_duration(r.duration)}, {r.tokens_used:,} tokens")
        w("")

    if skipped or na:
        w("## Skipped / Not Applicable")
        w("")
        for r in skipped + na:
            w(f"- **{r.page.slug}** — {r.status.value}")
        w("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual page reports
# ---------------------------------------------------------------------------


def _write_page_file(status_dir: Path, r: PageResult) -> None:
    status_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slug_to_filename(r.page.slug)}.md"
    path = status_dir / filename

    lines: list[str] = []
    w = lines.append

    w(f"# {r.page.slug}")
    w("")
    w(f"**Status:** {r.status.value}")
    w("")

    if r.status == PageStatus.FAILED:
        _write_failed_detail(w, r)
    elif r.status == PageStatus.PASSED:
        _write_passed_detail(w, r)
    else:
        if r.failure_reason:
            w(r.failure_reason)
            w("")

    path.write_text("\n".join(lines))


def _write_failed_detail(w: _LineAppender, r: PageResult) -> None:
    if r.failure_reason:
        w(f"**Reason:** {r.failure_reason}")
        w("")
    if r.failure_type and r.failure_type != FailureType.UNKNOWN:
        label = {
            FailureType.INDEPENDENT: "Independent failure",
            FailureType.LIKELY_CASCADING: "Likely caused by a prior failure",
        }.get(r.failure_type, r.failure_type.value)
        w(f"**Failure type:** {label}")
        w("")
    w(f"*{_fmt_duration(r.duration)} | {r.api_calls} API calls | {r.tokens_used:,} tokens*")
    w("")
    _write_steps_table(w, r.steps)


def _write_passed_detail(w: _LineAppender, r: PageResult) -> None:
    w(f"*{_fmt_duration(r.duration)} | {r.api_calls} API calls | {r.tokens_used:,} tokens*")
    w("")
    _write_steps_table(w, r.steps)


def _write_steps_table(w: _LineAppender, steps: list[StepResult]) -> None:
    if not steps:
        return
    w("| Step | Result | Error |")
    w("|------|--------|-------|")
    for s in steps:
        status = "PASS" if s.passed else "FAIL"
        error = s.error or ""
        w(f"| {s.description} | {status} | {error} |")
    w("")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slug_to_filename(slug: str) -> str:
    """Convert 'data/sorting-pagination' to 'data--sorting-pagination'."""
    return slug.replace("/", "--")


def status_subdir(result: PageResult) -> str:
    """Return the subdirectory name for a result's status."""
    if result.status == PageStatus.PASSED:
        return "passed"
    elif result.status == PageStatus.FAILED:
        return "failed"
    return "skipped"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"
