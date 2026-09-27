"""Contract for deterministic evidence interpretation."""

from typing import Protocol

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticResult


class DiagnosticRule(Protocol):
    """A pure interpretation of evidence already present in a store."""

    @property
    def id(self) -> str: ...

    @property
    def category(self) -> str: ...

    @property
    def required_evidence(self) -> frozenset[str]: ...

    @property
    def dependencies(self) -> tuple[str, ...]: ...

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult: ...
