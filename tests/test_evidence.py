import pytest

from makermedic.core.errors import DuplicateEvidenceError
from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import Evidence


def make_evidence(key: str = "example.value") -> Evidence:
    return Evidence(key=key, source="probe.example", value=True)


def test_evidence_store_lookup() -> None:
    evidence = make_evidence()
    store = EvidenceStore([evidence])

    assert store.get(evidence.key) is evidence
    assert store.require(evidence.key) is evidence
    assert "example.value" in store


def test_evidence_store_missing_lookup() -> None:
    store = EvidenceStore()

    assert store.get("missing") is None
    with pytest.raises(KeyError, match="evidence not found"):
        store.require("missing")


def test_duplicate_evidence_is_rejected_without_overwrite() -> None:
    original = make_evidence()
    store = EvidenceStore([original])

    with pytest.raises(DuplicateEvidenceError, match="example.value"):
        store.add(Evidence(key="example.value", source="probe.other", value=False))

    assert store.require("example.value") is original


def test_store_preserves_insertion_order_for_serialization() -> None:
    store = EvidenceStore([make_evidence("second"), make_evidence("first")])

    assert [item.key for item in store.values()] == ["second", "first"]
