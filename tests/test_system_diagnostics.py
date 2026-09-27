import pytest

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence, EvidenceAvailability
from makermedic.diagnostics.system import (
    GIB,
    MIB,
    DiskAvailabilityRule,
    MemoryAvailabilityRule,
    SystemPlatformRule,
)
from makermedic.probes.system import DiskSnapshot, MemorySnapshot, SystemProbe


def store(key: str, value: object) -> EvidenceStore:
    return EvidenceStore([Evidence(key=key, source="test", value=value)])


@pytest.mark.parametrize(
    ("operating_system", "expected"),
    [("Linux", DiagnosticStatus.PASS), ("Darwin", DiagnosticStatus.WARN)],
)
def test_platform_rule(operating_system: str, expected: DiagnosticStatus) -> None:
    result = SystemPlatformRule().evaluate(store("system.os", operating_system))

    assert result.status is expected


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (GIB, DiagnosticStatus.PASS),
        (512 * MIB, DiagnosticStatus.WARN),
        (511 * MIB, DiagnosticStatus.FAIL),
        (0, DiagnosticStatus.FAIL),
    ],
)
def test_memory_thresholds(available: int, expected: DiagnosticStatus) -> None:
    result = MemoryAvailabilityRule().evaluate(
        store("system.memory.available_bytes", available)
    )

    assert result.status is expected


def test_memory_unavailable_is_unknown() -> None:
    evidence = Evidence(
        key="system.memory.available_bytes",
        source="test",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    assert (
        MemoryAvailabilityRule().evaluate(EvidenceStore([evidence])).status
        is DiagnosticStatus.UNKNOWN
    )


@pytest.mark.parametrize(
    ("free", "expected"),
    [
        (5 * GIB, DiagnosticStatus.PASS),
        (GIB, DiagnosticStatus.WARN),
        (GIB - 1, DiagnosticStatus.FAIL),
        (0, DiagnosticStatus.FAIL),
    ],
)
def test_disk_thresholds(free: int, expected: DiagnosticStatus) -> None:
    result = DiskAvailabilityRule().evaluate(store("system.disk.root.free_bytes", free))

    assert result.status is expected


def test_disk_unavailable_is_unknown() -> None:
    evidence = Evidence(
        key="system.disk.root.free_bytes",
        source="test",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    assert (
        DiskAvailabilityRule().evaluate(EvidenceStore([evidence])).status
        is DiagnosticStatus.UNKNOWN
    )


def test_system_probe_collects_numeric_snapshots_including_zero() -> None:
    probe = SystemProbe(
        system=lambda: "Linux",
        platform_string=lambda: "Test Linux",
        kernel=lambda: "1.0",
        architecture=lambda: "x86_64",
        logical_cpu_count=lambda: 0,
        physical_cpu_count=lambda: 0,
        memory=lambda: MemorySnapshot(total=100, available=0, percent=100.0),
        disk=lambda _path: DiskSnapshot(total=200, free=0, percent=100.0),
    )

    values = {item.key: item.value for item in probe.collect()}
    assert values["system.cpu.logical_count"] == 0
    assert values["system.memory.available_bytes"] == 0
    assert values["system.disk.root.free_bytes"] == 0
