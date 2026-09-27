"""Pure deterministic comparison and verification of diagnostic snapshots."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from makermedic.core.errors import SnapshotTargetMismatchError
from makermedic.core.models import DependencyState, DiagnosticStatus, FindingKind
from makermedic.core.snapshots import DiagnosticSnapshot, SnapshotDiagnostic


class AvailabilityChange(StrEnum):
    SAME = "SAME"
    UNBLOCKED = "UNBLOCKED"
    BECAME_BLOCKED = "BECAME_BLOCKED"
    ADDED = "ADDED"
    REMOVED = "REMOVED"


class OutcomeChange(StrEnum):
    RESOLVED = "RESOLVED"
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    REGRESSED = "REGRESSED"
    INDETERMINATE = "INDETERMINATE"
    NEW_DIAGNOSTIC = "NEW_DIAGNOSTIC"
    REMOVED_DIAGNOSTIC = "REMOVED_DIAGNOSTIC"


class RootFindingChangeKind(StrEnum):
    RESOLVED = "RESOLVED"
    PERSISTENT = "PERSISTENT"
    NEW = "NEW"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"
    CONFIRMED_FAILURE = "CONFIRMED_FAILURE"


class DiagnosticChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    diagnostic_id: str
    category: str
    before_status: DiagnosticStatus | None = None
    after_status: DiagnosticStatus | None = None
    before_dependency_state: DependencyState | None = None
    after_dependency_state: DependencyState | None = None
    availability_change: AvailabilityChange
    outcome_change: OutcomeChange
    before_summary: str | None = None
    after_summary: str | None = None
    new_issue: bool = False


class RootFindingChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    diagnostic_id: str
    before_kind: FindingKind | None = None
    after_kind: FindingKind | None = None
    change: RootFindingChangeKind


class VerificationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolved_findings: tuple[str, ...] = ()
    persistent_findings: tuple[str, ...] = ()
    new_findings: tuple[str, ...] = ()
    regressions: tuple[str, ...] = ()
    unblocked_diagnostics: tuple[str, ...] = ()
    newly_blocked_diagnostics: tuple[str, ...] = ()
    indeterminate_changes: tuple[str, ...] = ()


class ComparisonReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    before_created_at: str
    after_created_at: str
    before_category_filter: str | None = None
    after_category_filter: str | None = None
    scope_changed: bool
    diagnostic_changes: tuple[DiagnosticChange, ...]
    root_finding_changes: tuple[RootFindingChange, ...]
    verification: VerificationSummary


class SnapshotComparator:
    """Compare portable snapshots without accessing the diagnosed environment."""

    def compare(
        self, before: DiagnosticSnapshot, after: DiagnosticSnapshot
    ) -> ComparisonReport:
        before_items = {item.diagnostic_id: item for item in before.diagnostics}
        after_items = {item.diagnostic_id: item for item in after.diagnostics}
        shared_service = any(
            before_items[item].category == "service"
            and after_items[item].category == "service"
            for item in before_items.keys() & after_items.keys()
        )
        if shared_service and before.metadata.service_url != after.metadata.service_url:
            raise SnapshotTargetMismatchError(
                "service snapshot targets differ and cannot be compared"
            )

        order = list(before_items)
        order.extend(item for item in after_items if item not in before_items)
        changes = tuple(
            _diagnostic_change(
                diagnostic_id,
                before_items.get(diagnostic_id),
                after_items.get(diagnostic_id),
            )
            for diagnostic_id in order
        )
        root_changes = _root_finding_changes(before, after, before_items, after_items)
        indeterminate = [
            item.diagnostic_id
            for item in changes
            if item.outcome_change is OutcomeChange.INDETERMINATE
        ]
        indeterminate.extend(
            item.diagnostic_id
            for item in root_changes
            if item.change
            in {
                RootFindingChangeKind.REMOVED,
                RootFindingChangeKind.CHANGED,
                RootFindingChangeKind.CONFIRMED_FAILURE,
            }
            and item.diagnostic_id not in indeterminate
        )
        verification = VerificationSummary(
            resolved_findings=tuple(
                item.diagnostic_id
                for item in root_changes
                if item.change is RootFindingChangeKind.RESOLVED
            ),
            persistent_findings=tuple(
                item.diagnostic_id
                for item in root_changes
                if item.change is RootFindingChangeKind.PERSISTENT
            ),
            new_findings=tuple(
                item.diagnostic_id
                for item in root_changes
                if item.change is RootFindingChangeKind.NEW
            ),
            regressions=tuple(
                item.diagnostic_id
                for item in changes
                if item.new_issue
                or (
                    item.outcome_change is OutcomeChange.REGRESSED
                    and item.after_status is DiagnosticStatus.FAIL
                )
            ),
            unblocked_diagnostics=tuple(
                item.diagnostic_id
                for item in changes
                if item.availability_change is AvailabilityChange.UNBLOCKED
            ),
            newly_blocked_diagnostics=tuple(
                item.diagnostic_id
                for item in changes
                if item.availability_change is AvailabilityChange.BECAME_BLOCKED
            ),
            indeterminate_changes=tuple(indeterminate),
        )
        return ComparisonReport(
            before_created_at=before.created_at.isoformat(),
            after_created_at=after.created_at.isoformat(),
            before_category_filter=before.metadata.category_filter,
            after_category_filter=after.metadata.category_filter,
            scope_changed=before.metadata.category_filter
            != after.metadata.category_filter,
            diagnostic_changes=changes,
            root_finding_changes=root_changes,
            verification=verification,
        )


def _diagnostic_change(
    diagnostic_id: str,
    before: SnapshotDiagnostic | None,
    after: SnapshotDiagnostic | None,
) -> DiagnosticChange:
    if before is None:
        assert after is not None
        return DiagnosticChange(
            diagnostic_id=diagnostic_id,
            category=after.category,
            after_status=after.status,
            after_dependency_state=after.dependency_state,
            availability_change=AvailabilityChange.ADDED,
            outcome_change=OutcomeChange.NEW_DIAGNOSTIC,
            after_summary=after.summary,
            new_issue=after.status is DiagnosticStatus.FAIL,
        )
    if after is None:
        return DiagnosticChange(
            diagnostic_id=diagnostic_id,
            category=before.category,
            before_status=before.status,
            before_dependency_state=before.dependency_state,
            availability_change=AvailabilityChange.REMOVED,
            outcome_change=OutcomeChange.REMOVED_DIAGNOSTIC,
            before_summary=before.summary,
        )
    availability = _availability_change(before.status, after.status)
    outcome = _outcome_change(before, after, availability)
    return DiagnosticChange(
        diagnostic_id=diagnostic_id,
        category=after.category,
        before_status=before.status,
        after_status=after.status,
        before_dependency_state=before.dependency_state,
        after_dependency_state=after.dependency_state,
        availability_change=availability,
        outcome_change=outcome,
        before_summary=before.summary,
        after_summary=after.summary,
    )


def _availability_change(
    before: DiagnosticStatus, after: DiagnosticStatus
) -> AvailabilityChange:
    before_blocked = before is DiagnosticStatus.BLOCKED
    after_blocked = after is DiagnosticStatus.BLOCKED
    if before_blocked and not after_blocked:
        return AvailabilityChange.UNBLOCKED
    if not before_blocked and after_blocked:
        return AvailabilityChange.BECAME_BLOCKED
    return AvailabilityChange.SAME


def _outcome_change(
    before: SnapshotDiagnostic,
    after: SnapshotDiagnostic,
    availability: AvailabilityChange,
) -> OutcomeChange:
    if availability is not AvailabilityChange.SAME:
        return OutcomeChange.INDETERMINATE
    if before.status is DiagnosticStatus.BLOCKED:
        return OutcomeChange.UNCHANGED
    before_key = (before.status, before.dependency_state)
    after_key = (after.status, after.dependency_state)
    if before_key == after_key:
        return OutcomeChange.UNCHANGED
    if DiagnosticStatus.UNKNOWN in {before.status, after.status}:
        if (
            before.status is DiagnosticStatus.UNKNOWN
            and after.status is DiagnosticStatus.PASS
        ):
            return OutcomeChange.IMPROVED
        return OutcomeChange.INDETERMINATE
    if before.status is DiagnosticStatus.FAIL:
        if after.status is DiagnosticStatus.PASS:
            return OutcomeChange.RESOLVED
        if after.status is DiagnosticStatus.WARN:
            return OutcomeChange.IMPROVED
    if before.status is DiagnosticStatus.PASS:
        return OutcomeChange.REGRESSED
    if before.status is DiagnosticStatus.WARN:
        if after.status is DiagnosticStatus.PASS:
            return (
                OutcomeChange.RESOLVED
                if before.dependency_state is DependencyState.UNSATISFIED
                else OutcomeChange.IMPROVED
            )
        if after.status is DiagnosticStatus.FAIL:
            return OutcomeChange.REGRESSED
        if after.status is DiagnosticStatus.WARN:
            if (
                before.dependency_state is DependencyState.UNSATISFIED
                and after.dependency_state is DependencyState.SATISFIED
            ):
                return OutcomeChange.IMPROVED
            if (
                before.dependency_state is DependencyState.SATISFIED
                and after.dependency_state is DependencyState.UNSATISFIED
            ):
                return OutcomeChange.REGRESSED
    return OutcomeChange.INDETERMINATE


def _root_finding_changes(
    before: DiagnosticSnapshot,
    after: DiagnosticSnapshot,
    before_items: dict[str, SnapshotDiagnostic],
    after_items: dict[str, SnapshotDiagnostic],
) -> tuple[RootFindingChange, ...]:
    before_roots = _root_findings(before)
    after_roots = _root_findings(after)
    order = list(before_roots)
    order.extend(item for item in after_roots if item not in before_roots)
    changes = []
    for diagnostic_id in order:
        old = before_roots.get(diagnostic_id)
        new = after_roots.get(diagnostic_id)
        if old is None:
            change = RootFindingChangeKind.NEW
        elif new is not None:
            if old.kind == new.kind:
                change = RootFindingChangeKind.PERSISTENT
            elif old.kind is FindingKind.UNCERTAIN and new.kind is FindingKind.FAILURE:
                change = RootFindingChangeKind.CONFIRMED_FAILURE
            else:
                change = RootFindingChangeKind.CHANGED
        elif diagnostic_id not in after_items:
            change = RootFindingChangeKind.REMOVED
        elif after_items[diagnostic_id].dependency_state is DependencyState.SATISFIED:
            change = RootFindingChangeKind.RESOLVED
        else:
            change = RootFindingChangeKind.CHANGED
        changes.append(
            RootFindingChange(
                diagnostic_id=diagnostic_id,
                before_kind=old.kind if old else None,
                after_kind=new.kind if new else None,
                change=change,
            )
        )
    return tuple(changes)


def _root_findings(snapshot: DiagnosticSnapshot):
    analysis = snapshot.root_cause_analysis
    if analysis is None:
        return {}
    findings = (
        analysis.actionable_findings
        + analysis.unresolved_findings
        + analysis.optional_absences
    )
    return {finding.diagnostic_id: finding for finding in findings}
