import socket
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from makermedic.core.errors import DuplicateRegistrationError, UnknownScenarioError
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
    RootCauseAnalysis,
    RootFinding,
)
from makermedic.lab import LabRunner, build_scenario_registry
from makermedic.lab.models import (
    ExpectedDiagnostic,
    ExpectedFinding,
    FaultScenario,
    SafetyLevel,
)
from makermedic.lab.registry import ScenarioRegistry
from makermedic.lab.runner import _live_service, match_scenario


def scenario(
    *,
    expected: ExpectedDiagnostic | None = None,
    finding: ExpectedFinding | None = None,
    expected_exit_code: int = 0,
) -> FaultScenario:
    return FaultScenario(
        id="test-scenario",
        title="Test",
        description="A deterministic test scenario.",
        category="test",
        safety_level=SafetyLevel.SIMULATED,
        fixture_id="test",
        expected_diagnostics=(expected,) if expected else (),
        expected_findings=(finding,) if finding else (),
        expected_exit_code=expected_exit_code,
    )


def run(
    result: DiagnosticResult,
    *,
    findings: tuple[RootFinding, ...] = (),
) -> DiagnosticRun:
    return DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=(result,),
        root_cause_analysis=RootCauseAnalysis(
            actionable_findings=findings,
            healthy_count=int(result.status is DiagnosticStatus.PASS),
        ),
    )


def result(
    status: DiagnosticStatus = DiagnosticStatus.PASS,
    *,
    state: DependencyState = DependencyState.SATISFIED,
    origin: ResultOrigin = ResultOrigin.EVALUATED,
    blocked_by: tuple[str, ...] = (),
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id="test.rule",
        category="test",
        status=status,
        dependency_state=state,
        origin=origin,
        summary="Fixture",
        blocked_by=blocked_by,
    )


def test_scenario_model_validation_and_immutability() -> None:
    item = scenario()
    with pytest.raises(ValidationError):
        FaultScenario(**{**item.model_dump(), "id": "Not valid"})
    with pytest.raises(ValidationError):
        item.id = "changed"  # type: ignore[misc]


def test_duplicate_scenario_ids_are_rejected() -> None:
    item = scenario()
    with pytest.raises(DuplicateRegistrationError):
        ScenarioRegistry((item, item))


def test_registry_order_is_deterministic_and_ids_are_unique() -> None:
    items = build_scenario_registry().all()
    identifiers = [item.id for item in items]
    assert identifiers == sorted(identifiers)
    assert len(identifiers) == len(set(identifiers)) == 39


def test_unknown_scenario_is_typed() -> None:
    with pytest.raises(UnknownScenarioError):
        LabRunner().run("does-not-exist")


def test_expected_diagnostic_matches_and_extra_pass_is_allowed() -> None:
    expected = ExpectedDiagnostic(
        diagnostic_id="test.rule",
        status=DiagnosticStatus.PASS,
        dependency_state=DependencyState.SATISFIED,
        result_origin=ResultOrigin.EVALUATED,
        blocked_by=(),
    )
    matched = match_scenario(scenario(expected=expected), run(result()))
    assert matched.passed


@pytest.mark.parametrize(
    ("expected", "actual", "fragment"),
    [
        (
            ExpectedDiagnostic(diagnostic_id="test.rule", status="FAIL"),
            result(),
            "status",
        ),
        (
            ExpectedDiagnostic(
                diagnostic_id="test.rule", dependency_state="UNSATISFIED"
            ),
            result(),
            "dependency_state",
        ),
        (
            ExpectedDiagnostic(
                diagnostic_id="test.rule", result_origin="DEPENDENCY_BLOCKED"
            ),
            result(),
            "result_origin",
        ),
        (
            ExpectedDiagnostic(
                diagnostic_id="test.rule", blocked_by=("upstream.rule",)
            ),
            result(),
            "blocked_by",
        ),
    ],
)
def test_matcher_detects_mutated_contract(expected, actual, fragment: str) -> None:
    matched = match_scenario(scenario(expected=expected), run(actual))
    assert not matched.passed
    assert any(fragment in error for error in matched.errors)


def test_matcher_detects_missing_diagnostic_and_finding() -> None:
    expected = ExpectedDiagnostic(diagnostic_id="missing.rule", status="PASS")
    finding = ExpectedFinding(diagnostic_id="missing.rule", kind="FAILURE")
    matched = match_scenario(
        scenario(expected=expected, finding=finding), run(result())
    )
    assert not matched.passed
    assert any("missing diagnostic" in error for error in matched.errors)
    assert any("missing root finding" in error for error in matched.errors)


@pytest.mark.parametrize("status", [DiagnosticStatus.FAIL, DiagnosticStatus.UNKNOWN])
def test_unexpected_severe_diagnostic_fails(status: DiagnosticStatus) -> None:
    matched = match_scenario(
        scenario(expected_exit_code=int(status is DiagnosticStatus.FAIL)),
        run(result(status, state=DependencyState.UNSATISFIED)),
    )
    assert not matched.passed
    assert matched.unexpected_diagnostics == ("test.rule",)


def test_unexpected_actionable_root_finding_fails() -> None:
    finding = RootFinding(
        diagnostic_id="test.rule",
        category="test",
        status=DiagnosticStatus.FAIL,
        dependency_state=DependencyState.UNSATISFIED,
        kind=FindingKind.FAILURE,
        summary="Fixture failure",
    )
    matched = match_scenario(
        scenario(expected_exit_code=1),
        run(
            result(DiagnosticStatus.FAIL, state=DependencyState.UNSATISFIED),
            findings=(finding,),
        ),
    )
    assert not matched.passed
    assert matched.unexpected_findings == ("test.rule",)


def test_expected_finding_matches_stable_fields() -> None:
    finding = RootFinding(
        diagnostic_id="test.rule",
        category="test",
        status=DiagnosticStatus.FAIL,
        dependency_state=DependencyState.UNSATISFIED,
        kind=FindingKind.FAILURE,
        summary="Prose is not matched",
        affected_diagnostics=("downstream.rule",),
    )
    expected = ExpectedDiagnostic(diagnostic_id="test.rule", status="FAIL")
    expected_finding = ExpectedFinding(
        diagnostic_id="test.rule",
        kind="FAILURE",
        affected_diagnostics=("downstream.rule",),
    )
    matched = match_scenario(
        scenario(expected=expected, finding=expected_finding, expected_exit_code=1),
        run(
            result(DiagnosticStatus.FAIL, state=DependencyState.UNSATISFIED),
            findings=(finding,),
        ),
    )
    assert matched.passed


@pytest.mark.parametrize(
    "scenario_id", build_scenario_registry().all(), ids=lambda item: item.id
)
def test_every_builtin_scenario_passes(scenario_id: FaultScenario) -> None:
    assert LabRunner().run(scenario_id.id).passed


def test_run_all_aggregation_and_json_serialization() -> None:
    report = LabRunner().run_all()
    assert (report.total, report.passed, report.failed) == (39, 39, 0)
    assert report.category_counts == {
        "camera": 7,
        "gpu": 8,
        "python": 5,
        "serial": 5,
        "service": 7,
        "system": 5,
        "usb": 2,
    }
    assert report.scenario_results == tuple(
        sorted(report.scenario_results, key=lambda item: item.scenario_id)
    )
    assert '"scenario_id"' in report.model_dump_json()


def test_temporary_service_is_loopback_ephemeral_and_releases_port() -> None:
    with _live_service(500) as target:
        assert target.host == "127.0.0.1"
        assert target.port != 0
        port = target.port
    replacement = socket.socket()
    try:
        replacement.bind(("127.0.0.1", port))
    finally:
        replacement.close()
