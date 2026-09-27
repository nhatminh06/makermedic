from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from makermedic.core.analysis import RootCauseAnalyzer
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
)


@dataclass
class Rule:
    id: str
    dependencies: tuple[str, ...] = ()
    category: str = "test"
    required_evidence: frozenset[str] = frozenset()

    def evaluate(self, _evidence):
        raise NotImplementedError


def result(
    diagnostic_id: str,
    status: DiagnosticStatus,
    *,
    state: DependencyState | None = None,
    kind: FindingKind | None = None,
    origin: ResultOrigin = ResultOrigin.EVALUATED,
    blocked_by: tuple[str, ...] = (),
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id=diagnostic_id,
        category="test",
        status=status,
        dependency_state=state,
        finding_kind=kind,
        origin=origin,
        summary=f"Summary for {diagnostic_id}",
        evidence=(f"evidence.{diagnostic_id}",),
        recommendations=(f"Recommendation for {diagnostic_id}",),
        blocked_by=blocked_by,
    )


def analyze(rules, results):
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=tuple(results),
    )
    return RootCauseAnalyzer().analyze(run, DiagnosticGraph(tuple(rules)))


def blocked(diagnostic_id: str, *blockers: str) -> DiagnosticResult:
    return result(
        diagnostic_id,
        DiagnosticStatus.BLOCKED,
        state=DependencyState.UNSATISFIED,
        origin=ResultOrigin.DEPENDENCY_BLOCKED,
        blocked_by=tuple(blockers),
    )


def test_healthy_graph_has_no_findings() -> None:
    analysis = analyze(
        (Rule("a"), Rule("b", ("a",))),
        (result("a", DiagnosticStatus.PASS), result("b", DiagnosticStatus.PASS)),
    )
    assert analysis.actionable_findings == ()
    assert analysis.unresolved_findings == ()
    assert analysis.optional_absences == ()
    assert analysis.blocked_diagnostics == ()
    assert analysis.healthy_count == 2


def test_basic_finding_kinds_and_engine_blocked_exclusion() -> None:
    rules = tuple(
        Rule(name) for name in ("failure", "missing", "unknown", "optional", "blocked")
    )
    analysis = analyze(
        rules,
        (
            result("failure", DiagnosticStatus.FAIL),
            result(
                "missing",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.MISSING_CAPABILITY,
            ),
            result("unknown", DiagnosticStatus.UNKNOWN),
            result(
                "optional",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.OPTIONAL_ABSENCE,
            ),
            blocked("blocked", "failure"),
        ),
    )
    assert [item.kind for item in analysis.actionable_findings] == [
        FindingKind.FAILURE,
        FindingKind.MISSING_CAPABILITY,
    ]
    assert analysis.unresolved_findings[0].kind is FindingKind.UNCERTAIN
    assert analysis.optional_absences[0].kind is FindingKind.OPTIONAL_ABSENCE
    assert analysis.blocked_diagnostics == ("blocked",)


def test_chain_reduces_to_one_root_with_transitive_impact() -> None:
    rules = (Rule("a"), Rule("b", ("a",)), Rule("c", ("b",)))
    analysis = analyze(
        rules,
        (result("a", DiagnosticStatus.FAIL), blocked("b", "a"), blocked("c", "b")),
    )
    assert [item.diagnostic_id for item in analysis.actionable_findings] == ["a"]
    assert analysis.actionable_findings[0].affected_diagnostics == ("b", "c")


def test_branch_reports_only_current_non_satisfied_descendants() -> None:
    rules = (
        Rule("a"),
        Rule("b", ("a",)),
        Rule("c", ("a",)),
        Rule("d", ("b",)),
        Rule("e", ("c",)),
        Rule("healthy", ("a",)),
    )
    analysis = analyze(
        rules,
        (
            result("a", DiagnosticStatus.FAIL),
            blocked("b", "a"),
            blocked("c", "a"),
            blocked("d", "b"),
            blocked("e", "c"),
            result("healthy", DiagnosticStatus.PASS),
        ),
    )
    assert analysis.actionable_findings[0].affected_diagnostics == ("b", "c", "d", "e")


def test_converging_roots_share_affected_descendants() -> None:
    rules = (Rule("a"), Rule("b"), Rule("c", ("a", "b")), Rule("d", ("c",)))
    analysis = analyze(
        rules,
        (
            result("a", DiagnosticStatus.FAIL),
            result("b", DiagnosticStatus.FAIL),
            blocked("c", "a", "b"),
            blocked("d", "c"),
        ),
    )
    assert [item.diagnostic_id for item in analysis.actionable_findings] == ["a", "b"]
    assert all(
        item.affected_diagnostics == ("c", "d") for item in analysis.actionable_findings
    )


def test_priority_then_affected_count_then_graph_order_is_deterministic() -> None:
    rules = (
        Rule("failure-small"),
        Rule("failure-large"),
        Rule("impact", ("failure-large",)),
        Rule("missing"),
        Rule("uncertain"),
        Rule("optional"),
    )
    results = (
        result("failure-small", DiagnosticStatus.FAIL),
        result("failure-large", DiagnosticStatus.FAIL),
        blocked("impact", "failure-large"),
        result(
            "missing",
            DiagnosticStatus.WARN,
            state=DependencyState.UNSATISFIED,
            kind=FindingKind.MISSING_CAPABILITY,
        ),
        result("uncertain", DiagnosticStatus.UNKNOWN),
        result(
            "optional",
            DiagnosticStatus.WARN,
            state=DependencyState.UNSATISFIED,
            kind=FindingKind.OPTIONAL_ABSENCE,
        ),
    )
    first = analyze(rules, results)
    second = analyze(rules, results)
    assert [item.diagnostic_id for item in first.actionable_findings] == [
        "failure-large",
        "failure-small",
        "missing",
    ]
    assert first == second


def test_intentional_rule_blocked_result_is_not_a_root_or_dependency_symptom() -> None:
    analysis = analyze(
        (Rule("serial.open"),), (result("serial.open", DiagnosticStatus.BLOCKED),)
    )
    assert analysis.actionable_findings == ()
    assert analysis.blocked_diagnostics == ()


def test_finding_reuses_recommendations_and_evidence_references() -> None:
    analysis = analyze((Rule("a"),), (result("a", DiagnosticStatus.FAIL),))
    finding = analysis.actionable_findings[0]
    assert finding.recommendations == ("Recommendation for a",)
    assert finding.evidence_refs == ("evidence.a",)


def test_result_missing_from_graph_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown diagnostic ID"):
        analyze((Rule("a"),), (result("missing", DiagnosticStatus.FAIL),))


def test_duplicate_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate diagnostic result"):
        analyze(
            (Rule("a"),),
            (result("a", DiagnosticStatus.FAIL), result("a", DiagnosticStatus.FAIL)),
        )
