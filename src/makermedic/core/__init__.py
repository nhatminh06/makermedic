"""Presentation-independent diagnostic engine contracts."""

from makermedic.core.engine import DiagnosticEngine
from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    Evidence,
    EvidenceAvailability,
    ProbeOutcome,
    ProbeStatus,
)
from makermedic.core.registry import Registry

__all__ = [
    "DiagnosticEngine",
    "DiagnosticResult",
    "DiagnosticRun",
    "DiagnosticStatus",
    "Evidence",
    "EvidenceAvailability",
    "EvidenceStore",
    "ProbeOutcome",
    "ProbeStatus",
    "Registry",
]
