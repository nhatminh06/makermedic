from datetime import UTC, datetime

from rich.console import Console

from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    RootCauseAnalysis,
    RootFinding,
)
from makermedic.presentation.terminal import render_run


def test_blocked_result_renders_immediate_dependency_ids() -> None:
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=(
            DiagnosticResult(
                diagnostic_id="downstream",
                category="test",
                status=DiagnosticStatus.BLOCKED,
                summary="Blocked by diagnostic prerequisites",
                blocked_by=("upstream.one", "upstream.two"),
            ),
        ),
    )
    console = Console(record=True, width=120)
    render_run(run, console)
    output = console.export_text()
    assert "Blocked by: upstream.one, upstream.two" in output


def test_root_findings_render_kind_impact_and_recommendation() -> None:
    finding = RootFinding(
        diagnostic_id="root",
        category="test",
        status=DiagnosticStatus.FAIL,
        dependency_state=DependencyState.UNSATISFIED,
        kind=FindingKind.FAILURE,
        summary="Root failed",
        affected_diagnostics=("child",),
        recommendations=("Review root.",),
    )
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=(
            DiagnosticResult(
                diagnostic_id="root",
                category="test",
                status=DiagnosticStatus.FAIL,
                summary="Root failed",
            ),
        ),
        root_cause_analysis=RootCauseAnalysis(
            actionable_findings=(finding,), healthy_count=0
        ),
    )
    console = Console(record=True, width=120)
    render_run(run, console)
    output = console.export_text()
    assert "FAILURE: Root failed" in output
    assert "Affects 1 downstream diagnostic(s): child" in output
    assert "Recommendation: Review root." in output
