"""Concise terminal rendering for laboratory models."""

from rich.console import Console

from makermedic.lab.models import FaultScenario, LabReport, ScenarioResult


def render_scenario_list(
    scenarios: tuple[FaultScenario, ...], console: Console
) -> None:
    console.print("[bold]MakerMedic Diagnostic Lab[/bold]")
    for scenario in scenarios:
        console.print(f"[bold]{scenario.id}[/bold]")
        console.print(f"  {scenario.safety_level.value.replace('_', ' ').title()}")
        console.print(f"  {scenario.description}")


def render_scenario(scenario: FaultScenario, console: Console) -> None:
    console.print(f"[bold]{scenario.id}[/bold]")
    console.print(scenario.description)
    console.print(f"Category: {scenario.category}")
    console.print(f"Safety: {scenario.safety_level.value.replace('_', ' ').title()}")
    console.print("Expected diagnostics:")
    for item in scenario.expected_diagnostics:
        console.print(f"  {item.diagnostic_id}: {item.status or 'any'}")
    console.print("Expected root findings:")
    if scenario.expected_findings:
        for item in scenario.expected_findings:
            console.print(f"  {item.diagnostic_id}: {item.kind or 'any'}")
    else:
        console.print("  None")


def render_scenario_result(result: ScenarioResult, console: Console) -> None:
    console.print(f"[bold]Scenario: {result.scenario_id}[/bold]")
    console.print("Diagnostic contract")
    checked = set(result.diagnostic_checks)
    actual = {item.diagnostic_id: item for item in result.actual_diagnostics}
    for expected in result.expected_diagnostics:
        observed = actual.get(expected.diagnostic_id)
        status = observed.status.value if observed else "MISSING"
        marker = "PASS" if expected.diagnostic_id in checked else "MISMATCH"
        console.print(f"  {expected.diagnostic_id}  {status}  {marker}")
    console.print("Root findings")
    if result.expected_findings:
        checked_findings = set(result.finding_checks)
        for expected in result.expected_findings:
            marker = (
                "PASS" if expected.diagnostic_id in checked_findings else "MISMATCH"
            )
            console.print(
                f"  {expected.diagnostic_id}  {expected.kind or 'any'}  {marker}"
            )
    else:
        console.print("  None expected")
    for error in result.errors:
        console.print(f"  Error: {error}")
    console.print(f"[bold]RESULT: {'PASS' if result.passed else 'FAIL'}[/bold]")


def render_lab_report(report: LabReport, console: Console) -> None:
    console.print("[bold]MakerMedic Diagnostic Lab[/bold]")
    console.print(f"{report.total} scenarios")
    console.print(f"{report.passed} passed")
    console.print(f"{report.failed} failed")
    console.print("[bold]Scenario coverage[/bold]")
    for category, count in report.category_counts.items():
        console.print(f"  {category}: {count}")
    if report.failed:
        console.print("[bold]Failed scenarios[/bold]")
        for result in report.scenario_results:
            if not result.passed:
                console.print(f"  {result.scenario_id}")
