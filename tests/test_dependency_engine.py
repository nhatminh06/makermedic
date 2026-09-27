from dataclasses import dataclass, field

import pytest

from makermedic.core.engine import DiagnosticEngine
from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticStatus,
    ResultOrigin,
)
from makermedic.core.registry import Registry


@dataclass
class TrackingRule:
    id: str
    status: DiagnosticStatus = DiagnosticStatus.PASS
    dependency_state: DependencyState | None = None
    dependencies: tuple[str, ...] = ()
    category: str = "test"
    required_evidence: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    def evaluate(self, _evidence: EvidenceStore) -> DiagnosticResult:
        self.calls.append(self.id)
        if self.error:
            raise self.error
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=self.status,
            dependency_state=self.dependency_state,
            summary=self.id,
        )


def run(*rules: TrackingRule):
    registry = Registry()
    for rule in rules:
        registry.register_rule(rule)
    return DiagnosticEngine(registry).run()


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (DiagnosticStatus.PASS, DependencyState.SATISFIED),
        (DiagnosticStatus.FAIL, DependencyState.UNSATISFIED),
        (DiagnosticStatus.BLOCKED, DependencyState.UNSATISFIED),
        (DiagnosticStatus.UNKNOWN, DependencyState.UNKNOWN),
    ],
)
def test_default_dependency_states(status, state) -> None:
    result = DiagnosticResult(
        diagnostic_id="a", category="test", status=status, summary="a"
    )
    assert result.dependency_state is state


def test_warn_dependency_state_is_explicit() -> None:
    default = DiagnosticResult(
        diagnostic_id="a", category="test", status=DiagnosticStatus.WARN, summary="a"
    )
    explicit = DiagnosticResult(
        diagnostic_id="b",
        category="test",
        status=DiagnosticStatus.WARN,
        dependency_state=DependencyState.SATISFIED,
        summary="b",
    )
    assert default.dependency_state is DependencyState.UNKNOWN
    assert explicit.dependency_state is DependencyState.SATISFIED


def test_satisfied_dependency_allows_evaluation() -> None:
    upstream = TrackingRule("upstream")
    downstream = TrackingRule("downstream", dependencies=("upstream",))
    result = run(downstream, upstream)
    assert downstream.calls == ["downstream"]
    assert [item.diagnostic_id for item in result.results] == ["upstream", "downstream"]


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (DiagnosticStatus.FAIL, None),
        (DiagnosticStatus.UNKNOWN, None),
        (DiagnosticStatus.BLOCKED, None),
        (DiagnosticStatus.WARN, DependencyState.UNSATISFIED),
    ],
)
def test_non_satisfied_dependency_blocks_without_calling_rule(status, state) -> None:
    upstream = TrackingRule("upstream", status=status, dependency_state=state)
    downstream = TrackingRule(
        "downstream",
        dependencies=("upstream",),
        error=AssertionError("must not run"),
    )
    result = run(upstream, downstream)
    blocked = result.results[1]
    assert downstream.calls == []
    assert blocked.status is DiagnosticStatus.BLOCKED
    assert blocked.dependency_state is DependencyState.UNSATISFIED
    assert blocked.origin is ResultOrigin.DEPENDENCY_BLOCKED
    assert blocked.blocked_by == ("upstream",)


def test_multiple_dependencies_and_deterministic_blockers() -> None:
    first = TrackingRule("first", status=DiagnosticStatus.FAIL)
    second = TrackingRule("second", status=DiagnosticStatus.UNKNOWN)
    downstream = TrackingRule("downstream", dependencies=("second", "first"))
    result = run(first, second, downstream)
    blocked = result.results[-1]
    assert downstream.calls == []
    assert blocked.blocked_by == ("second", "first")
    payload = blocked.model_dump(mode="json")
    assert payload["dependency_state"] == "UNSATISFIED"
    assert payload["blocked_by"] == ["second", "first"]


@pytest.mark.parametrize(
    "status",
    [DiagnosticStatus.PASS, DiagnosticStatus.WARN, DiagnosticStatus.FAIL],
)
def test_rule_results_are_evaluated_origin(status) -> None:
    result = run(TrackingRule("rule", status=status)).results[0]
    assert result.origin is ResultOrigin.EVALUATED


def test_rule_generated_blocked_result_remains_evaluated_origin() -> None:
    result = run(TrackingRule("rule", status=DiagnosticStatus.BLOCKED)).results[0]
    assert result.origin is ResultOrigin.EVALUATED


def test_multiple_satisfied_dependencies_allow_evaluation() -> None:
    first = TrackingRule("first")
    second = TrackingRule("second")
    downstream = TrackingRule("downstream", dependencies=("first", "second"))
    run(first, second, downstream)
    assert downstream.calls == ["downstream"]


def test_category_filter_includes_cross_category_ancestor_but_hides_its_result() -> (
    None
):
    upstream = TrackingRule("upstream", category="foundation")
    downstream = TrackingRule(
        "downstream", category="requested", dependencies=("upstream",)
    )
    registry = Registry()
    registry.register_rule(upstream)
    registry.register_rule(downstream)
    result = DiagnosticEngine(registry).run(category="requested")
    assert upstream.calls == ["upstream"]
    assert downstream.calls == ["downstream"]
    assert [item.diagnostic_id for item in result.results] == ["downstream"]
