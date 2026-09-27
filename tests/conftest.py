from collections.abc import Collection, Iterable
from dataclasses import dataclass

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
)


@dataclass
class FakeProbe:
    id: str = "probe.example"
    categories: Collection[str] = ("example",)
    items: tuple[Evidence, ...] = ()
    error: Exception | None = None

    def collect(self) -> Iterable[Evidence]:
        if self.error is not None:
            raise self.error
        return self.items


@dataclass
class FakeRule:
    id: str = "diagnostic.example"
    category: str = "example"
    status: DiagnosticStatus = DiagnosticStatus.PASS
    required_evidence: frozenset[str] = frozenset()
    dependencies: tuple[str, ...] = ()

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        references = tuple(key for key in self.required_evidence if key in evidence)
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=self.status,
            summary="Example diagnostic",
            evidence=references,
        )
