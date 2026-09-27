"""Rich terminal rendering for structured diagnostic runs."""

from rich.console import Console
from rich.table import Table

from makermedic.core.bundles import PRIVACY_GUARANTEES, BundlePlan
from makermedic.core.comparison import (
    AvailabilityChange,
    ComparisonReport,
    OutcomeChange,
)
from makermedic.core.models import DiagnosticRun, DiagnosticStatus, RootFinding


def render_bundle_preview(plan: BundlePlan, console: Console) -> None:
    """Show the exact planned files and evidence keys without creating an artifact."""
    console.print("[bold]MakerMedic Support Bundle Preview[/bold]")
    console.print(f"Source: {plan.manifest.source_type}")
    console.print("[bold]Files[/bold]")
    for name in plan.manifest.file_inventory:
        console.print(f"  {name}")
    console.print("[bold]Exported evidence[/bold]")
    if plan.exported_evidence:
        for key in plan.exported_evidence:
            console.print(f"  {key}")
    else:
        console.print("  None")
    console.print(f"[bold]Omitted evidence ({len(plan.omitted_evidence)})[/bold]")
    if plan.omitted_evidence:
        for key in plan.omitted_evidence:
            console.print(f"  {key}")
    else:
        console.print("  None")
    console.print("[bold]Privacy[/bold]")
    for guarantee in PRIVACY_GUARANTEES:
        console.print(f"  {guarantee}")
    if plan.manifest.source_type == "snapshot":
        console.print("Snapshot bundles contain no category evidence values.")


def render_run(run: DiagnosticRun, console: Console) -> None:
    """Render a concise run summary without changing domain data."""
    console.print("[bold]MakerMedic[/bold]")
    console.print()

    if not run.results:
        console.print("No diagnostics are registered yet.")
        return

    categories = dict.fromkeys(result.category for result in run.results)
    for category in categories:
        console.print(f"[bold]{category.title()}[/bold]")
        table = Table(show_header=True)
        table.add_column("Diagnostic")
        table.add_column("Status")
        for result in run.results:
            if result.category != category:
                continue
            table.add_row(result.summary, result.status.value)
            if result.status is DiagnosticStatus.BLOCKED and result.blocked_by:
                table.add_row(f"  Blocked by: {', '.join(result.blocked_by)}", "")
            if result.status in {DiagnosticStatus.WARN, DiagnosticStatus.FAIL}:
                for cause in result.causes:
                    table.add_row(f"  {cause}", "")
                for recommendation in result.recommendations:
                    table.add_row(f"  Recommendation: {recommendation}", "")
        console.print(table)
        console.print()

    failures = sum(result.status is DiagnosticStatus.FAIL for result in run.results)
    warnings = sum(result.status is DiagnosticStatus.WARN for result in run.results)
    noun = "diagnostic" if len(run.results) == 1 else "diagnostics"
    console.print(f"{len(run.results)} {noun}")
    console.print(f"{failures} failures")
    console.print(f"{warnings} warnings")

    analysis = run.root_cause_analysis
    if analysis is None:
        return
    console.print()
    console.print("[bold]Findings[/bold]")
    if not (
        analysis.actionable_findings
        or analysis.unresolved_findings
        or analysis.optional_absences
        or analysis.supporting_findings
    ):
        console.print("No upstream problems identified.")
        return
    _render_findings(console, "Actionable findings", analysis.actionable_findings)
    _render_findings(console, "Needs investigation", analysis.unresolved_findings)
    _render_findings(
        console, "Optional capabilities unavailable", analysis.optional_absences
    )
    _render_findings(console, "Supporting observations", analysis.supporting_findings)


def _render_findings(
    console: Console, heading: str, findings: tuple[RootFinding, ...]
) -> None:
    if not findings:
        return
    console.print(f"[bold]{heading}[/bold]")
    for finding in findings:
        console.print(f"  {finding.kind.value}: {finding.summary}")
        if finding.affected_diagnostics:
            console.print(
                f"    Affects {len(finding.affected_diagnostics)} downstream "
                "diagnostic(s): " + ", ".join(finding.affected_diagnostics)
            )
        for recommendation in finding.recommendations:
            console.print(f"    Recommendation: {recommendation}")


def render_comparison(
    report: ComparisonReport, console: Console, *, show_all: bool = False
) -> None:
    """Render diagnostic transitions, omitting unchanged entries by default."""
    console.print("[bold]Comparison[/bold]")
    if report.scope_changed:
        console.print(
            f"Scope changed: {report.before_category_filter or 'all'} -> "
            f"{report.after_category_filter or 'all'}"
        )
    shown = 0
    for change in report.diagnostic_changes:
        if not show_all and (
            change.outcome_change is OutcomeChange.UNCHANGED
            and change.availability_change is AvailabilityChange.SAME
        ):
            continue
        shown += 1
        before = change.before_status.value if change.before_status else "absent"
        after = change.after_status.value if change.after_status else "absent"
        console.print(
            f"  {change.diagnostic_id}: {before} -> {after} "
            f"[{change.availability_change.value}, {change.outcome_change.value}]"
        )
    if shown == 0:
        console.print("No diagnostic changes.")
    console.print()
    render_verification(report, console)


def render_verification(report: ComparisonReport, console: Console) -> None:
    """Render the concise verification interpretation of a comparison."""
    console.print("[bold]Verification[/bold]")
    summary = report.verification
    sections = (
        ("Resolved findings", summary.resolved_findings),
        ("Persistent findings", summary.persistent_findings),
        ("New findings", summary.new_findings),
        ("Regressions/new failures", summary.regressions),
        ("Unblocked diagnostics", summary.unblocked_diagnostics),
        ("Newly blocked diagnostics", summary.newly_blocked_diagnostics),
        ("Indeterminate changes", summary.indeterminate_changes),
    )
    displayed = False
    for heading, diagnostic_ids in sections:
        if not diagnostic_ids:
            continue
        displayed = True
        console.print(f"[bold]{heading}[/bold]")
        for diagnostic_id in diagnostic_ids:
            console.print(f"  {diagnostic_id}")
    if not displayed:
        console.print("No verification changes identified.")
