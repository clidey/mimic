"""Tests for mimic.report — Markdown report generation."""

from __future__ import annotations

from pathlib import Path

from mimic.models import FailureType, Page, PageResult, PageStatus, StepResult
from mimic.report import generate_report, slug_to_filename, status_subdir


def _page(slug: str = "test-page") -> Page:
    return Page(slug=slug, filename=f"{slug}.mdx", content="", line_start=0, line_end=0)


def _result(
    slug: str = "test-page",
    status: PageStatus = PageStatus.PASSED,
    **kwargs: object,
) -> PageResult:
    return PageResult(page=_page(slug), status=status, **kwargs)


class TestSlugToFilename:
    def test_replaces_slashes(self) -> None:
        assert slug_to_filename("data/sorting-pagination") == "data--sorting-pagination"

    def test_simple_slug_unchanged(self) -> None:
        assert slug_to_filename("installation") == "installation"

    def test_deeply_nested(self) -> None:
        assert slug_to_filename("a/b/c") == "a--b--c"


class TestStatusSubdir:
    def test_passed(self) -> None:
        assert status_subdir(_result(status=PageStatus.PASSED)) == "passed"

    def test_failed(self) -> None:
        assert status_subdir(_result(status=PageStatus.FAILED)) == "failed"

    def test_skipped(self) -> None:
        assert status_subdir(_result(status=PageStatus.SKIPPED)) == "skipped"

    def test_not_applicable(self) -> None:
        assert status_subdir(_result(status=PageStatus.NOT_APPLICABLE)) == "skipped"


class TestGenerateReport:
    def test_creates_report_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        import mimic.report as report_mod

        monkeypatch.setattr(report_mod, "REPORTS_DIR", tmp_path / "reports")

        results = [
            _result("install", PageStatus.PASSED, duration=10.0, api_calls=5, tokens_used=1000),
            _result(
                "config",
                PageStatus.FAILED,
                failure_reason="Button not found",
                failure_type=FailureType.INDEPENDENT,
                duration=20.0,
                api_calls=10,
                tokens_used=2000,
                steps=[
                    StepResult(description="Open page", passed=True),
                    StepResult(description="Click button", passed=False, error="not found"),
                ],
            ),
            _result("changelog", PageStatus.SKIPPED, duration=0.0, api_calls=0, tokens_used=0),
        ]

        run_dir = generate_report(results, run_name="test-run")

        assert run_dir.exists()
        assert "test-run" in run_dir.name

        # Check summary
        summary = (run_dir / "summary.md").read_text()
        assert "Passed" in summary
        assert "Failed" in summary
        assert "install" in summary
        assert "config" in summary

        # Check subdirectory structure
        assert (run_dir / "passed" / "install.md").exists()
        assert (run_dir / "failed" / "config.md").exists()
        assert (run_dir / "skipped" / "changelog.md").exists()

        # Check failed page detail
        failed_content = (run_dir / "failed" / "config.md").read_text()
        assert "Button not found" in failed_content
        assert "FAIL" in failed_content

    def test_handles_nested_slugs(self, tmp_path: Path, monkeypatch: object) -> None:
        import mimic.report as report_mod

        monkeypatch.setattr(report_mod, "REPORTS_DIR", tmp_path / "reports")

        results = [_result("features/billing", PageStatus.PASSED, duration=5.0, api_calls=3, tokens_used=500)]

        run_dir = generate_report(results, run_name="nested")

        assert (run_dir / "passed" / "features--billing.md").exists()
