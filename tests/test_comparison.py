from datetime import UTC, datetime

import pytest

from makermedic.core.comparison import (
    AvailabilityChange,
    OutcomeChange,
    RootFindingChangeKind,
    SnapshotComparator,
)
from makermedic.core.errors import SnapshotTargetMismatchError
from makermedic.core.models import (
    DependencyState,
    DiagnosticStatus,
    FindingKind,
    RootCauseAnalysis,
    RootFinding,
)
from makermedic.core.snapshots import (
    DiagnosticSnapshot,
    SnapshotDiagnostic,
    SnapshotMetadata,
)

P = (DiagnosticStatus.PASS, DependencyState.SATISFIED)
WS = (DiagnosticStatus.WARN, DependencyState.SATISFIED)
WU = (DiagnosticStatus.WARN, DependencyState.UNSATISFIED)
F = (DiagnosticStatus.FAIL, DependencyState.UNSATISFIED)
U = (DiagnosticStatus.UNKNOWN, DependencyState.UNKNOWN)
B = (DiagnosticStatus.BLOCKED, DependencyState.UNSATISFIED)


def diagnostic(diagnostic_id, state, *, category="test"):
    status, dependency = state
    return SnapshotDiagnostic(
        diagnostic_id=diagnostic_id,
        category=category,
        status=status,
        dependency_state=dependency,
        result_origin="DEPENDENCY_BLOCKED"
        if status is DiagnosticStatus.BLOCKED
        else "EVALUATED",
        summary=f"{diagnostic_id} {status.value}",
    )


def finding(diagnostic_id, kind, status=DiagnosticStatus.FAIL):
    return RootFinding(
        diagnostic_id=diagnostic_id,
        category="test",
        status=status,
        dependency_state=DependencyState.UNSATISFIED,
        kind=kind,
        summary=diagnostic_id,
    )


def snapshot(*diagnostics, roots=(), category="test", service_url=None):
    actionable = tuple(
        item
        for item in roots
        if item.kind in {FindingKind.FAILURE, FindingKind.MISSING_CAPABILITY}
    )
    unresolved = tuple(item for item in roots if item.kind is FindingKind.UNCERTAIN)
    optional = tuple(
        item for item in roots if item.kind is FindingKind.OPTIONAL_ABSENCE
    )
    return DiagnosticSnapshot(
        schema_version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        makermedic_version="0.1.0",
        metadata=SnapshotMetadata(category_filter=category, service_url=service_url),
        diagnostics=diagnostics,
        root_cause_analysis=RootCauseAnalysis(
            actionable_findings=actionable,
            unresolved_findings=unresolved,
            optional_absences=optional,
            healthy_count=0,
        ),
    )


TRANSITIONS = [
    (P, P, OutcomeChange.UNCHANGED),
    (P, WS, OutcomeChange.REGRESSED),
    (P, WU, OutcomeChange.REGRESSED),
    (P, F, OutcomeChange.REGRESSED),
    (P, U, OutcomeChange.INDETERMINATE),
    (P, B, OutcomeChange.INDETERMINATE),
    (WS, P, OutcomeChange.IMPROVED),
    (WS, WS, OutcomeChange.UNCHANGED),
    (WS, WU, OutcomeChange.REGRESSED),
    (WS, F, OutcomeChange.REGRESSED),
    (WS, U, OutcomeChange.INDETERMINATE),
    (WS, B, OutcomeChange.INDETERMINATE),
    (WU, P, OutcomeChange.RESOLVED),
    (WU, WS, OutcomeChange.IMPROVED),
    (WU, WU, OutcomeChange.UNCHANGED),
    (WU, F, OutcomeChange.REGRESSED),
    (WU, U, OutcomeChange.INDETERMINATE),
    (WU, B, OutcomeChange.INDETERMINATE),
    (F, P, OutcomeChange.RESOLVED),
    (F, WS, OutcomeChange.IMPROVED),
    (F, WU, OutcomeChange.IMPROVED),
    (F, F, OutcomeChange.UNCHANGED),
    (F, U, OutcomeChange.INDETERMINATE),
    (F, B, OutcomeChange.INDETERMINATE),
    (U, P, OutcomeChange.IMPROVED),
    (U, WS, OutcomeChange.INDETERMINATE),
    (U, WU, OutcomeChange.INDETERMINATE),
    (U, F, OutcomeChange.INDETERMINATE),
    (U, U, OutcomeChange.UNCHANGED),
    (U, B, OutcomeChange.INDETERMINATE),
    (B, P, OutcomeChange.INDETERMINATE),
    (B, WS, OutcomeChange.INDETERMINATE),
    (B, WU, OutcomeChange.INDETERMINATE),
    (B, F, OutcomeChange.INDETERMINATE),
    (B, U, OutcomeChange.INDETERMINATE),
    (B, B, OutcomeChange.UNCHANGED),
]


@pytest.mark.parametrize(("before_state", "after_state", "expected"), TRANSITIONS)
def test_explicit_transition_matrix(before_state, after_state, expected) -> None:
    report = SnapshotComparator().compare(
        snapshot(diagnostic("a", before_state)),
        snapshot(diagnostic("a", after_state)),
    )
    change = report.diagnostic_changes[0]
    assert change.outcome_change is expected
    if before_state is B and after_state is not B:
        assert change.availability_change is AvailabilityChange.UNBLOCKED
    elif before_state is not B and after_state is B:
        assert change.availability_change is AvailabilityChange.BECAME_BLOCKED
    else:
        assert change.availability_change is AvailabilityChange.SAME


def test_new_and_removed_diagnostics_are_not_assumed_resolved_or_broken() -> None:
    report = SnapshotComparator().compare(
        snapshot(diagnostic("removed", F)),
        snapshot(diagnostic("new-pass", P), diagnostic("new-fail", F)),
    )
    changes = {item.diagnostic_id: item for item in report.diagnostic_changes}
    assert changes["removed"].outcome_change is OutcomeChange.REMOVED_DIAGNOSTIC
    assert changes["new-pass"].outcome_change is OutcomeChange.NEW_DIAGNOSTIC
    assert changes["new-pass"].new_issue is False
    assert changes["new-fail"].new_issue is True
    assert report.verification.regressions == ("new-fail",)


def test_scope_change_is_metadata_not_comparison_failure() -> None:
    before = snapshot(diagnostic("shared", P), category="gpu")
    after = snapshot(diagnostic("shared", P), diagnostic("new", P), category=None)
    report = SnapshotComparator().compare(before, after)
    assert report.scope_changed is True
    assert report.diagnostic_changes[1].outcome_change is OutcomeChange.NEW_DIAGNOSTIC


def test_service_target_mismatch_is_rejected() -> None:
    before = snapshot(
        diagnostic("service.target", P, category="service"),
        service_url="http://localhost:8000/health",
    )
    after = snapshot(
        diagnostic("service.target", P, category="service"),
        service_url="http://localhost:5000/health",
    )
    with pytest.raises(SnapshotTargetMismatchError):
        SnapshotComparator().compare(before, after)


def test_root_finding_resolved_persistent_new_removed_and_changed() -> None:
    before = snapshot(
        diagnostic("resolved", F),
        diagnostic("persistent", F),
        diagnostic("removed", F),
        diagnostic("confirmed", U),
        diagnostic("changed", WU),
        roots=(
            finding("resolved", FindingKind.FAILURE),
            finding("persistent", FindingKind.FAILURE),
            finding("removed", FindingKind.MISSING_CAPABILITY, DiagnosticStatus.WARN),
            finding("confirmed", FindingKind.UNCERTAIN, DiagnosticStatus.UNKNOWN),
            finding("changed", FindingKind.MISSING_CAPABILITY, DiagnosticStatus.WARN),
        ),
    )
    after = snapshot(
        diagnostic("resolved", P),
        diagnostic("persistent", F),
        diagnostic("confirmed", F),
        diagnostic("new", WU),
        diagnostic("changed", WU),
        roots=(
            finding("persistent", FindingKind.FAILURE),
            finding("confirmed", FindingKind.FAILURE),
            finding("new", FindingKind.MISSING_CAPABILITY, DiagnosticStatus.WARN),
            finding("changed", FindingKind.OPTIONAL_ABSENCE, DiagnosticStatus.WARN),
        ),
    )
    changes = {
        item.diagnostic_id: item.change
        for item in SnapshotComparator().compare(before, after).root_finding_changes
    }
    assert changes == {
        "resolved": RootFindingChangeKind.RESOLVED,
        "persistent": RootFindingChangeKind.PERSISTENT,
        "removed": RootFindingChangeKind.REMOVED,
        "confirmed": RootFindingChangeKind.CONFIRMED_FAILURE,
        "new": RootFindingChangeKind.NEW,
        "changed": RootFindingChangeKind.CHANGED,
    }


def test_fail_chain_resolves_and_descendants_unblock() -> None:
    before = snapshot(
        diagnostic("a", F),
        diagnostic("b", B),
        diagnostic("c", B),
        roots=(finding("a", FindingKind.FAILURE),),
    )
    after = snapshot(diagnostic("a", P), diagnostic("b", P), diagnostic("c", P))
    report = SnapshotComparator().compare(before, after)
    assert report.verification.resolved_findings == ("a",)
    assert report.verification.unblocked_diagnostics == ("b", "c")


def test_unblocked_failure_is_not_called_resolved() -> None:
    report = SnapshotComparator().compare(
        snapshot(diagnostic("b", B)), snapshot(diagnostic("b", F))
    )
    change = report.diagnostic_changes[0]
    assert change.availability_change is AvailabilityChange.UNBLOCKED
    assert change.outcome_change is OutcomeChange.INDETERMINATE


def test_gpu_partial_and_complete_recovery_scenarios() -> None:
    before = snapshot(
        diagnostic("gpu.hardware", P),
        diagnostic("gpu.driver", F),
        diagnostic("gpu.nvml", B),
        diagnostic("gpu.pytorch", WU),
        diagnostic("gpu.build", B),
        diagnostic("gpu.visibility", B),
        diagnostic("gpu.allocation", B),
        diagnostic("gpu.compute", B),
        roots=(
            finding("gpu.driver", FindingKind.FAILURE),
            finding(
                "gpu.pytorch",
                FindingKind.MISSING_CAPABILITY,
                DiagnosticStatus.WARN,
            ),
        ),
        category="gpu",
    )
    partial = snapshot(
        diagnostic("gpu.hardware", P),
        diagnostic("gpu.driver", P),
        diagnostic("gpu.nvml", P),
        diagnostic("gpu.pytorch", WU),
        diagnostic("gpu.build", B),
        diagnostic("gpu.visibility", B),
        diagnostic("gpu.allocation", B),
        diagnostic("gpu.compute", B),
        roots=(
            finding(
                "gpu.pytorch",
                FindingKind.MISSING_CAPABILITY,
                DiagnosticStatus.WARN,
            ),
        ),
        category="gpu",
    )
    complete = snapshot(
        diagnostic("gpu.hardware", P),
        diagnostic("gpu.driver", P),
        diagnostic("gpu.nvml", P),
        diagnostic("gpu.pytorch", P),
        diagnostic("gpu.build", P),
        diagnostic("gpu.visibility", P),
        diagnostic("gpu.allocation", P),
        diagnostic("gpu.compute", P),
        category="gpu",
    )
    partial_report = SnapshotComparator().compare(before, partial)
    complete_report = SnapshotComparator().compare(before, complete)
    assert partial_report.verification.resolved_findings == ("gpu.driver",)
    assert partial_report.verification.persistent_findings == ("gpu.pytorch",)
    assert partial_report.verification.unblocked_diagnostics == ("gpu.nvml",)
    assert complete_report.verification.resolved_findings == (
        "gpu.driver",
        "gpu.pytorch",
    )
    assert complete_report.verification.unblocked_diagnostics == (
        "gpu.nvml",
        "gpu.build",
        "gpu.visibility",
        "gpu.allocation",
        "gpu.compute",
    )


@pytest.mark.parametrize(
    "category, presence, children",
    [
        ("camera", "camera.presence", ("camera.permissions", "camera.busy")),
        ("serial", "serial.presence", ("serial.permissions", "serial.busy")),
    ],
)
def test_optional_device_appearance_resolves_absence_and_unblocks_checks(
    category, presence, children
) -> None:
    before = snapshot(
        diagnostic(presence, WU, category=category),
        *(diagnostic(child, B, category=category) for child in children),
        roots=(
            finding(
                presence,
                FindingKind.OPTIONAL_ABSENCE,
                DiagnosticStatus.WARN,
            ),
        ),
        category=category,
    )
    after = snapshot(
        diagnostic(presence, P, category=category),
        *(diagnostic(child, P, category=category) for child in children),
        category=category,
    )
    report = SnapshotComparator().compare(before, after)
    assert report.verification.resolved_findings == (presence,)
    assert report.verification.unblocked_diagnostics == children


def test_service_tcp_and_http_health_recovery() -> None:
    target = "http://localhost:8000/health"
    tcp_before = snapshot(
        diagnostic("service.tcp", F, category="service"),
        diagnostic("service.http", B, category="service"),
        roots=(finding("service.tcp", FindingKind.FAILURE),),
        category="service",
        service_url=target,
    )
    tcp_after = snapshot(
        diagnostic("service.tcp", P, category="service"),
        diagnostic("service.http", P, category="service"),
        category="service",
        service_url=target,
    )
    tcp_report = SnapshotComparator().compare(tcp_before, tcp_after)
    assert tcp_report.verification.resolved_findings == ("service.tcp",)
    assert tcp_report.verification.unblocked_diagnostics == ("service.http",)

    health_before = snapshot(
        diagnostic("service.health", F, category="service"),
        roots=(finding("service.health", FindingKind.FAILURE),),
        category="service",
        service_url=target,
    )
    health_after = snapshot(
        diagnostic("service.health", P, category="service"),
        category="service",
        service_url=target,
    )
    health_report = SnapshotComparator().compare(health_before, health_after)
    assert health_report.verification.resolved_findings == ("service.health",)
