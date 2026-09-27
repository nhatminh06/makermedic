"""Serializable domain models with no presentation dependencies."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class EvidenceAvailability(StrEnum):
    """Whether an observation was successfully obtained."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class Evidence(BaseModel):
    """One environmental fact emitted by a probe.

    Availability is explicit so false, zero, and available null values remain
    distinct from a value that could not be collected.
    """

    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    source: str = Field(min_length=1)
    value: JsonValue = None
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE
    description: str | None = None

    @model_validator(mode="after")
    def unavailable_has_no_value(self) -> "Evidence":
        if (
            self.availability is EvidenceAvailability.UNAVAILABLE
            and self.value is not None
        ):
            raise ValueError("unavailable evidence cannot contain a value")
        return self


class DiagnosticStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class DependencyState(StrEnum):
    """Whether a diagnostic result permits dependent diagnostics to run."""

    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


class FindingKind(StrEnum):
    """How analysis should interpret a directly evaluated non-satisfied result."""

    FAILURE = "FAILURE"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    OPTIONAL_ABSENCE = "OPTIONAL_ABSENCE"
    UNCERTAIN = "UNCERTAIN"
    SUPPORTING = "SUPPORTING"


class ResultOrigin(StrEnum):
    """Whether a result came from its rule or dependency orchestration."""

    EVALUATED = "EVALUATED"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"


def dependency_state_for_status(
    status: DiagnosticStatus,
    *,
    warning: DependencyState = DependencyState.UNKNOWN,
) -> DependencyState:
    """Return the standard dependency state, with explicit WARN semantics."""
    if status is DiagnosticStatus.PASS:
        return DependencyState.SATISFIED
    if status in {DiagnosticStatus.FAIL, DiagnosticStatus.BLOCKED}:
        return DependencyState.UNSATISFIED
    if status is DiagnosticStatus.UNKNOWN:
        return DependencyState.UNKNOWN
    return warning


class DiagnosticResult(BaseModel):
    """A deterministic conclusion supported by evidence references."""

    model_config = ConfigDict(frozen=True)

    diagnostic_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: DiagnosticStatus
    dependency_state: DependencyState | None = None
    finding_kind: FindingKind | None = None
    origin: ResultOrigin = ResultOrigin.EVALUATED
    summary: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()
    causes: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    verification_steps: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()

    @model_validator(mode="after")
    def populate_dependency_state(self) -> "DiagnosticResult":
        if self.dependency_state is None:
            object.__setattr__(
                self, "dependency_state", dependency_state_for_status(self.status)
            )
        if self.finding_kind is None:
            kind = None
            if self.status is DiagnosticStatus.FAIL:
                kind = FindingKind.FAILURE
            elif self.status is DiagnosticStatus.UNKNOWN:
                kind = FindingKind.UNCERTAIN
            object.__setattr__(self, "finding_kind", kind)
        return self


class RootFinding(BaseModel):
    """One directly observed upstream finding and its current graph impact."""

    model_config = ConfigDict(frozen=True)

    diagnostic_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: DiagnosticStatus
    dependency_state: DependencyState
    kind: FindingKind
    summary: str = Field(min_length=1)
    affected_diagnostics: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class RootCauseAnalysis(BaseModel):
    """Deterministic grouping of upstream findings and blocked symptoms."""

    model_config = ConfigDict(frozen=True)

    actionable_findings: tuple[RootFinding, ...] = ()
    unresolved_findings: tuple[RootFinding, ...] = ()
    optional_absences: tuple[RootFinding, ...] = ()
    supporting_findings: tuple[RootFinding, ...] = ()
    blocked_diagnostics: tuple[str, ...] = ()
    healthy_count: int = Field(ge=0)


class ProbeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ProbeOutcome(BaseModel):
    """Collection metadata, including expected collection failures."""

    model_config = ConfigDict(frozen=True)

    probe_id: str = Field(min_length=1)
    status: ProbeStatus
    evidence_keys: tuple[str, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def status_matches_error(self) -> "ProbeOutcome":
        if self.status is ProbeStatus.SUCCESS and self.error is not None:
            raise ValueError("a successful probe cannot contain an error")
        if self.status is ProbeStatus.FAILED and not self.error:
            raise ValueError("a failed probe must describe its error")
        return self


class DiagnosticRun(BaseModel):
    """Complete serializable output of one engine execution."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    evidence: tuple[Evidence, ...]
    probe_outcomes: tuple[ProbeOutcome, ...]
    results: tuple[DiagnosticResult, ...]
    root_cause_analysis: RootCauseAnalysis | None = None
