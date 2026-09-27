"""Typed immutable contracts and reports for validation scenarios."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from makermedic.core.models import (
    DependencyState,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
)


class SafetyLevel(StrEnum):
    SIMULATED = "SIMULATED"
    TEMPORARY_LOCAL = "TEMPORARY_LOCAL"


class ExpectedDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str = Field(min_length=1)
    status: DiagnosticStatus | None = None
    dependency_state: DependencyState | None = None
    result_origin: ResultOrigin | None = None
    blocked_by: tuple[str, ...] | None = None


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str = Field(min_length=1)
    kind: FindingKind | None = None
    affected_diagnostics: tuple[str, ...] | None = None


class FaultScenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    safety_level: SafetyLevel
    fixture_id: str = Field(min_length=1)
    expected_diagnostics: tuple[ExpectedDiagnostic, ...]
    expected_findings: tuple[ExpectedFinding, ...] = ()
    expected_exit_code: int = Field(ge=0, le=1)
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "FaultScenario":
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.id) is None:
            raise ValueError("scenario ID must use stable kebab-case")
        identifiers = [item.diagnostic_id for item in self.expected_diagnostics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("scenario contains duplicate diagnostic expectations")
        findings = [item.diagnostic_id for item in self.expected_findings]
        if len(findings) != len(set(findings)):
            raise ValueError("scenario contains duplicate finding expectations")
        return self


class ActualDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str
    status: DiagnosticStatus
    dependency_state: DependencyState
    result_origin: ResultOrigin
    blocked_by: tuple[str, ...]


class ActualFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str
    kind: FindingKind
    affected_diagnostics: tuple[str, ...]


class ScenarioResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    category: str
    safety_level: SafetyLevel
    passed: bool
    expected_diagnostics: tuple[ExpectedDiagnostic, ...]
    expected_findings: tuple[ExpectedFinding, ...]
    actual_diagnostics: tuple[ActualDiagnostic, ...]
    actual_findings: tuple[ActualFinding, ...]
    diagnostic_checks: tuple[str, ...]
    finding_checks: tuple[str, ...]
    unexpected_diagnostics: tuple[str, ...]
    unexpected_findings: tuple[str, ...]
    errors: tuple[str, ...]
    expected_exit_code: int
    actual_exit_code: int


class LabReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    category_counts: dict[str, int]
    scenario_results: tuple[ScenarioResult, ...]
