from datetime import UTC, datetime

import pytest
from conftest import FakeProbe, FakeRule

from makermedic.core.engine import DiagnosticEngine
from makermedic.core.errors import ProbeCollectionError
from makermedic.core.models import DiagnosticStatus, Evidence, ProbeStatus
from makermedic.core.registry import Registry

NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_successful_probe_and_rule_execution() -> None:
    registry = Registry()
    registry.register_probe(
        FakeProbe(
            items=(
                Evidence(key="example.available", source="probe.example", value=True),
            )
        )
    )
    registry.register_rule(FakeRule(required_evidence=frozenset({"example.available"})))

    run = DiagnosticEngine(registry, clock=lambda: NOW).run()

    assert run.timestamp == NOW
    assert run.probe_outcomes[0].status is ProbeStatus.SUCCESS
    assert run.probe_outcomes[0].evidence_keys == ("example.available",)
    assert run.results[0].status is DiagnosticStatus.PASS
    assert run.results[0].evidence == ("example.available",)


def test_expected_probe_failure_is_recorded() -> None:
    registry = Registry()
    registry.register_probe(FakeProbe(error=ProbeCollectionError("tool missing")))

    run = DiagnosticEngine(registry).run()

    assert run.probe_outcomes[0].status is ProbeStatus.FAILED
    assert run.probe_outcomes[0].error == "tool missing"


def test_probe_continues_after_expected_failure() -> None:
    registry = Registry()
    registry.register_probe(
        FakeProbe(id="probe.failed", error=ProbeCollectionError("failed"))
    )
    registry.register_probe(
        FakeProbe(
            id="probe.healthy",
            items=(
                Evidence(key="example.healthy", source="probe.healthy", value=True),
            ),
        )
    )

    run = DiagnosticEngine(registry).run()

    assert [outcome.status for outcome in run.probe_outcomes] == [
        ProbeStatus.FAILED,
        ProbeStatus.SUCCESS,
    ]
    assert run.evidence[0].key == "example.healthy"


def test_unexpected_probe_exception_remains_visible() -> None:
    registry = Registry()
    registry.register_probe(FakeProbe(error=RuntimeError("programming defect")))

    with pytest.raises(RuntimeError, match="programming defect"):
        DiagnosticEngine(registry).run()


def test_rule_evaluation_is_deterministic_for_identical_evidence() -> None:
    registry = Registry()
    registry.register_probe(
        FakeProbe(
            items=(Evidence(key="example.value", source="probe.example", value=0),)
        )
    )
    registry.register_rule(FakeRule(status=DiagnosticStatus.WARN))
    engine = DiagnosticEngine(registry, clock=lambda: NOW)

    first = engine.run()
    second = engine.run()

    assert first.results == second.results


def test_engine_filters_by_category() -> None:
    registry = Registry()
    registry.register_probe(FakeProbe(id="probe.example", categories=("example",)))
    registry.register_probe(FakeProbe(id="probe.other", categories=("other",)))
    registry.register_rule(FakeRule(id="rule.example", category="example"))
    registry.register_rule(FakeRule(id="rule.other", category="other"))

    run = DiagnosticEngine(registry).run(category="other")

    assert [item.probe_id for item in run.probe_outcomes] == ["probe.other"]
    assert [item.diagnostic_id for item in run.results] == ["rule.other"]


def test_empty_registry_produces_an_empty_run() -> None:
    run = DiagnosticEngine(Registry(), clock=lambda: NOW).run()

    assert run.evidence == ()
    assert run.probe_outcomes == ()
    assert run.results == ()


def test_probe_only_category_still_collects_evidence() -> None:
    registry = Registry()
    registry.register_probe(
        FakeProbe(
            categories=("probe-only",),
            items=(Evidence(key="probe.only", source="probe.example", value=True),),
        )
    )
    run = DiagnosticEngine(registry).run(category="probe-only")
    assert run.evidence[0].key == "probe.only"
    assert run.results == ()
