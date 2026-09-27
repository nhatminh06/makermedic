"""Thin command-line adapter for the diagnostic engine."""

from pathlib import Path

import typer
from rich.console import Console

from makermedic import __version__
from makermedic.composition import build_default_registry
from makermedic.core.analysis import RootCauseAnalyzer
from makermedic.core.bundles import BundleBuilder, export_bundle
from makermedic.core.comparison import SnapshotComparator
from makermedic.core.engine import DiagnosticEngine
from makermedic.core.errors import (
    BundleError,
    SnapshotError,
    UnknownCategoryError,
    UnknownScenarioError,
)
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import DiagnosticStatus
from makermedic.core.registry import Registry
from makermedic.core.snapshots import load_snapshot, save_snapshot, snapshot_from_run
from makermedic.lab import LabRunner, build_scenario_registry
from makermedic.lab.presentation import (
    render_lab_report,
    render_scenario,
    render_scenario_list,
    render_scenario_result,
)
from makermedic.presentation.terminal import (
    render_bundle_preview,
    render_comparison,
    render_run,
    render_verification,
)
from makermedic.service import ServiceTarget

app = typer.Typer(
    help="Evidence-based diagnostics for Linux AI, robotics, and maker environments."
)
lab_app = typer.Typer(
    help=(
        "Safe simulated or temporary-local validation scenarios; no intentional "
        "changes to host drivers, permissions, packages, or services."
    )
)
app.add_typer(lab_app, name="lab")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"MakerMedic {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed MakerMedic version and exit.",
    ),
) -> None:
    """Run evidence-based maker environment diagnostics."""


def create_registry(
    package: str | None = None,
    *,
    serial_open_test: bool = False,
    service_target: ServiceTarget | None = None,
) -> Registry:
    """Create the explicit production registry."""
    return build_default_registry(
        package,
        serial_open_test=serial_open_test,
        service_target=service_target,
    )


def _analyzed_run(
    category: str | None,
    package: str | None,
    serial_open_test: bool,
    service_target: ServiceTarget | None,
):
    registry_options: dict[str, object] = {"serial_open_test": serial_open_test}
    if service_target is not None:
        registry_options["service_target"] = service_target
    registry = create_registry(package, **registry_options)
    run = DiagnosticEngine(registry).run(category=category)
    analysis = RootCauseAnalyzer().analyze(run, DiagnosticGraph(registry.rules()))
    return run.model_copy(update={"root_cause_analysis": analysis})


@app.command()
def diagnose(
    category: str | None = typer.Option(None, help="Run one registered category."),
    package: str | None = typer.Option(
        None, help="Inspect installed metadata for one Python package."
    ),
    serial_open_test: bool = typer.Option(
        False,
        "--serial-open-test",
        help="Opt in to a cautious serial-port open/close test.",
    ),
    url: str | None = typer.Option(
        None, "--url", help="Diagnose one explicit local HTTP/HTTPS service URL."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
    save: Path | None = typer.Option(  # noqa: B008
        None, "--save", help="Save a diagnostic snapshot."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing snapshot."
    ),
) -> None:
    """Collect evidence and evaluate registered diagnostic rules."""
    if package is not None and category not in {None, "python"}:
        raise typer.BadParameter(
            "package inspection requires the python category",
            param_hint="--package",
        )
    if serial_open_test and category != "serial":
        raise typer.BadParameter(
            "serial open testing requires --category serial",
            param_hint="--serial-open-test",
        )
    if category == "service" and url is None:
        raise typer.BadParameter(
            "service diagnostics require --url", param_hint="--url"
        )
    if url is not None and category != "service":
        raise typer.BadParameter(
            "--url requires --category service", param_hint="--url"
        )
    if force and save is None:
        raise typer.BadParameter("--force requires --save", param_hint="--force")
    try:
        service_target = ServiceTarget.parse(url) if url is not None else None
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--url") from error
    try:
        analyzed_run = _analyzed_run(
            category, package, serial_open_test, service_target
        )
    except UnknownCategoryError as error:
        raise typer.BadParameter(str(error), param_hint="--category") from error

    if save is not None:
        snapshot = snapshot_from_run(
            analyzed_run,
            category_filter=category,
            service_url=url,
            package=package,
            serial_open_test=serial_open_test,
        )
        try:
            save_snapshot(snapshot, save, force=force)
        except SnapshotError as error:
            raise typer.BadParameter(str(error), param_hint="--save") from error
    if json_output:
        typer.echo(analyzed_run.model_dump_json(indent=2))
    else:
        render_run(analyzed_run, Console())
        if save is not None:
            typer.echo(f"Snapshot saved: {save}")

    if any(result.status is DiagnosticStatus.FAIL for result in analyzed_run.results):
        raise typer.Exit(code=1)


@app.command()
def bundle(
    preview: bool = typer.Option(
        False, "--preview", help="Preview without writing a ZIP."
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None, "--output", help="Write a support-bundle ZIP."
    ),
    snapshot: Path | None = typer.Option(  # noqa: B008
        None, "--snapshot", help="Build from an existing diagnostic snapshot."
    ),
    category: str | None = typer.Option(None, help="Run one registered category."),
    package: str | None = typer.Option(None, help="Inspect one Python package."),
    serial_open_test: bool = typer.Option(
        False, "--serial-open-test", help="Opt in to serial open/close testing."
    ),
    url: str | None = typer.Option(None, "--url", help="Explicit local service URL."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing bundle."),
) -> None:
    """Preview or export a privacy-allowlisted support bundle."""
    if preview == (output is not None):
        raise typer.BadParameter("choose exactly one of --preview or --output")
    if force and output is None:
        raise typer.BadParameter("--force requires --output", param_hint="--force")
    if (
        snapshot is not None
        and any(value is not None for value in (category, package, url))
        or snapshot is not None
        and serial_open_test
    ):
        raise typer.BadParameter(
            "--snapshot cannot be combined with live diagnostic options",
            param_hint="--snapshot",
        )
    if package is not None and category not in {None, "python"}:
        raise typer.BadParameter(
            "package inspection requires the python category", param_hint="--package"
        )
    if serial_open_test and category != "serial":
        raise typer.BadParameter(
            "serial open testing requires --category serial",
            param_hint="--serial-open-test",
        )
    if category == "service" and url is None:
        raise typer.BadParameter(
            "service diagnostics require --url", param_hint="--url"
        )
    if url is not None and category != "service":
        raise typer.BadParameter(
            "--url requires --category service", param_hint="--url"
        )
    try:
        if snapshot is not None:
            plan = BundleBuilder().from_snapshot(load_snapshot(snapshot))
        else:
            target = ServiceTarget.parse(url) if url is not None else None
            plan = BundleBuilder().from_run(
                _analyzed_run(category, package, serial_open_test, target)
            )
        if output is not None:
            export_bundle(plan, output, force=force)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--url") from error
    except UnknownCategoryError as error:
        raise typer.BadParameter(str(error), param_hint="--category") from error
    except SnapshotError as error:
        raise typer.BadParameter(str(error), param_hint="--snapshot") from error
    except BundleError as error:
        raise typer.BadParameter(str(error), param_hint="--output") from error
    if preview:
        render_bundle_preview(plan, Console())
    else:
        typer.echo(f"Support bundle saved: {output}")


@lab_app.command("list")
def lab_list(
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
) -> None:
    """List built-in safe validation scenarios."""
    scenarios = build_scenario_registry().all()
    if json_output:
        typer.echo(
            "[\n"
            + ",\n".join(item.model_dump_json(indent=2) for item in scenarios)
            + "\n]"
        )
    else:
        render_scenario_list(scenarios, Console())


def _lab_scenario(scenario_id: str):
    try:
        return build_scenario_registry().get(scenario_id)
    except KeyError as error:
        raise typer.BadParameter(
            str(error).strip("'"), param_hint="SCENARIO"
        ) from error


@lab_app.command("show")
def lab_show(
    scenario_id: str = typer.Argument(..., metavar="SCENARIO"),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
) -> None:
    """Show one scenario's stable expected contract."""
    scenario = _lab_scenario(scenario_id)
    if json_output:
        typer.echo(scenario.model_dump_json(indent=2))
    else:
        render_scenario(scenario, Console())


@lab_app.command("run")
def lab_run(
    scenario_id: str = typer.Argument(..., metavar="SCENARIO"),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
) -> None:
    """Run one scenario and validate its diagnostic contract."""
    try:
        result = LabRunner().run(scenario_id)
    except UnknownScenarioError as error:
        raise typer.BadParameter(str(error), param_hint="SCENARIO") from error
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        render_scenario_result(result, Console())
    if not result.passed:
        raise typer.Exit(code=1)


@lab_app.command("run-all")
def lab_run_all(
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
) -> None:
    """Run every built-in safe scenario in deterministic order."""
    report = LabRunner().run_all()
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        render_lab_report(report, Console())
    if report.failed:
        raise typer.Exit(code=1)


def _comparison(before: Path, after: Path):
    try:
        return SnapshotComparator().compare(load_snapshot(before), load_snapshot(after))
    except SnapshotError as error:
        raise typer.BadParameter(str(error), param_hint="snapshot") from error


@app.command()
def compare(
    before: Path = typer.Argument(..., help="Baseline snapshot."),  # noqa: B008
    after: Path = typer.Argument(..., help="Later snapshot."),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
    show_all: bool = typer.Option(
        False, "--all", help="Include unchanged diagnostics."
    ),
) -> None:
    """Show detailed deterministic changes between two snapshots."""
    report = _comparison(before, after)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        render_comparison(report, Console(), show_all=show_all)
    if report.verification.regressions:
        raise typer.Exit(code=1)


@app.command()
def verify(
    before: Path = typer.Argument(..., help="Baseline snapshot."),  # noqa: B008
    after: Path = typer.Argument(..., help="Later snapshot."),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON."),
) -> None:
    """Summarize resolutions, persistence, regressions, and availability changes."""
    report = _comparison(before, after)
    if json_output:
        typer.echo(report.verification.model_dump_json(indent=2))
    else:
        render_verification(report, Console())
    if report.verification.regressions:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
