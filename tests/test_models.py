from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from makermedic.core.models import (
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    Evidence,
    EvidenceAvailability,
)


def test_evidence_serialization() -> None:
    evidence = Evidence(
        key="example.count", source="probe.example", value=3, description="Count"
    )

    assert evidence.model_dump(mode="json") == {
        "key": "example.count",
        "source": "probe.example",
        "value": 3,
        "availability": "AVAILABLE",
        "description": "Count",
    }


@pytest.mark.parametrize("value", [False, 0])
def test_available_false_and_zero_values_are_preserved(value: bool | int) -> None:
    evidence = Evidence(key="example.value", source="probe.example", value=value)

    assert evidence.availability is EvidenceAvailability.AVAILABLE
    assert evidence.value == value
    assert type(evidence.value) is type(value)


def test_unavailable_evidence_is_explicit() -> None:
    evidence = Evidence(
        key="example.value",
        source="probe.example",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    assert evidence.value is None
    assert evidence.model_dump(mode="json")["availability"] == "UNAVAILABLE"


@pytest.mark.parametrize("value", [False, 0])
def test_unavailable_differs_from_available_values(value: bool | int) -> None:
    available = Evidence(key="example.value", source="probe.example", value=value)
    unavailable = Evidence(
        key="example.value",
        source="probe.example",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    assert available != unavailable


def test_unavailable_evidence_rejects_a_value() -> None:
    with pytest.raises(ValidationError, match="cannot contain a value"):
        Evidence(
            key="example.value",
            source="probe.example",
            value=1,
            availability=EvidenceAvailability.UNAVAILABLE,
        )


def test_available_null_is_distinct_from_unavailable() -> None:
    available_null = Evidence(key="example.value", source="probe.example", value=None)
    unavailable = Evidence(
        key="example.value",
        source="probe.example",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    assert available_null != unavailable


@pytest.mark.parametrize("status", list(DiagnosticStatus))
def test_all_diagnostic_statuses_serialize(status: DiagnosticStatus) -> None:
    result = DiagnosticResult(
        diagnostic_id="diagnostic.example",
        category="example",
        status=status,
        summary="Example",
    )

    assert result.model_dump(mode="json")["status"] == status.value


def test_diagnostic_result_serialization() -> None:
    result = DiagnosticResult(
        diagnostic_id="diagnostic.example",
        category="example",
        status=DiagnosticStatus.WARN,
        summary="Something noteworthy",
        evidence=("example.value",),
        causes=("A cause",),
        recommendations=("Review it",),
        verification_steps=("Run it again",),
    )

    payload = result.model_dump(mode="json")
    assert payload["recommendations"] == ["Review it"]
    assert payload["dependency_state"] == "UNKNOWN"
    assert payload["blocked_by"] == []


def test_diagnostic_run_serialization() -> None:
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=(),
    )

    data = run.model_dump(mode="json")
    assert data["timestamp"] == "2026-01-01T00:00:00Z"
    assert data["evidence"] == []
