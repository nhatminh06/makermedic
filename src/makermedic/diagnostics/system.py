"""Deterministic rules for basic system evidence."""

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticStatus,
    EvidenceAvailability,
    dependency_state_for_status,
)

GIB = 1024**3
MIB = 1024**2


class SystemPlatformRule:
    id = "system.platform.support"
    category = "system"
    dependencies = ()
    required_evidence = frozenset({"system.os"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        operating_system = _value(evidence, "system.os", str)
        if operating_system is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Operating system could not be determined"
            causes = ()
        elif operating_system.casefold() == "linux":
            status = DiagnosticStatus.PASS
            summary = "Linux platform"
            causes = ()
        else:
            status = DiagnosticStatus.WARN
            summary = "Non-Linux platform"
            causes = (f"Detected platform: {operating_system}",)
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.SATISFIED
            ),
            summary=summary,
            evidence=("system.os",),
            causes=causes,
            recommendations=(
                "Use Linux for full support from later hardware diagnostics.",
            )
            if status is DiagnosticStatus.WARN
            else (),
        )


class MemoryAvailabilityRule:
    """PASS at 1 GiB, WARN at 512 MiB, otherwise FAIL."""

    id = "system.memory.available"
    category = "system"
    dependencies = ()
    required_evidence = frozenset({"system.memory.available_bytes"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        available = _number(evidence, "system.memory.available_bytes")
        if available is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Available memory could not be determined"
        elif available >= GIB:
            status = DiagnosticStatus.PASS
            summary = "Available memory"
        elif available >= 512 * MIB:
            status = DiagnosticStatus.WARN
            summary = "Available memory is low"
        else:
            status = DiagnosticStatus.FAIL
            summary = "Available memory is critically low"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.SATISFIED
            ),
            summary=summary,
            evidence=("system.memory.available_bytes",),
            causes=(f"Available memory: {_gib(available)}",)
            if available is not None and status is not DiagnosticStatus.PASS
            else (),
            recommendations=("Free memory before running memory-intensive tools.",)
            if status in {DiagnosticStatus.WARN, DiagnosticStatus.FAIL}
            else (),
        )


class DiskAvailabilityRule:
    """Evaluate free bytes on the root filesystem only."""

    id = "system.disk.root.available"
    category = "system"
    dependencies = ()
    required_evidence = frozenset({"system.disk.root.free_bytes"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        free = _number(evidence, "system.disk.root.free_bytes")
        if free is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Root filesystem free space could not be determined"
        elif free >= 5 * GIB:
            status = DiagnosticStatus.PASS
            summary = "Root filesystem free space"
        elif free >= GIB:
            status = DiagnosticStatus.WARN
            summary = "Root filesystem free space is low"
        else:
            status = DiagnosticStatus.FAIL
            summary = "Root filesystem free space is critically low"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.SATISFIED
            ),
            summary=summary,
            evidence=("system.disk.root.free_bytes",),
            causes=(f"Free space on /: {_gib(free)}",)
            if free is not None and status is not DiagnosticStatus.PASS
            else (),
            recommendations=("Free space on the root filesystem.",)
            if status in {DiagnosticStatus.WARN, DiagnosticStatus.FAIL}
            else (),
        )


def _value(evidence: EvidenceStore, key: str, expected: type[str]) -> str | None:
    item = evidence.get(key)
    if (
        item is None
        or item.availability is EvidenceAvailability.UNAVAILABLE
        or not isinstance(item.value, expected)
    ):
        return None
    return item.value


def _number(evidence: EvidenceStore, key: str) -> int | float | None:
    item = evidence.get(key)
    if item is None or item.availability is EvidenceAvailability.UNAVAILABLE:
        return None
    if isinstance(item.value, bool) or not isinstance(item.value, (int, float)):
        return None
    return item.value


def _gib(value: int | float) -> str:
    return f"{value / GIB:.1f} GiB"
