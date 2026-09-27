"""Basic, privacy-conscious system fact collection."""

import platform
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import psutil

from makermedic.core.models import Evidence, EvidenceAvailability


@dataclass(frozen=True)
class MemorySnapshot:
    total: int
    available: int
    percent: float


@dataclass(frozen=True)
class DiskSnapshot:
    total: int
    free: int
    percent: float


class SystemProbe:
    """Collect bounded platform, CPU, memory, and root-filesystem facts."""

    id = "system.basic"
    categories = ("system",)

    def __init__(
        self,
        *,
        system: Callable[[], str] = platform.system,
        platform_string: Callable[[], str] = platform.platform,
        kernel: Callable[[], str] = platform.release,
        architecture: Callable[[], str] = platform.machine,
        logical_cpu_count: Callable[[], int | None] | None = None,
        physical_cpu_count: Callable[[], int | None] | None = None,
        memory: Callable[[], MemorySnapshot] | None = None,
        disk: Callable[[str], DiskSnapshot] | None = None,
    ) -> None:
        self._system = system
        self._platform = platform_string
        self._kernel = kernel
        self._architecture = architecture
        self._logical_cpu_count = logical_cpu_count or (
            lambda: psutil.cpu_count(logical=True)
        )
        self._physical_cpu_count = physical_cpu_count or (
            lambda: psutil.cpu_count(logical=False)
        )
        self._memory = memory or _memory_snapshot
        self._disk = disk or _disk_snapshot

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        evidence = [
            Evidence(key="system.os", source=source, value=self._system()),
            Evidence(key="system.platform", source=source, value=self._platform()),
            Evidence(key="system.kernel", source=source, value=self._kernel()),
            Evidence(
                key="system.architecture", source=source, value=self._architecture()
            ),
            _optional_evidence(
                "system.cpu.logical_count", source, self._logical_cpu_count
            ),
            _optional_evidence(
                "system.cpu.physical_count", source, self._physical_cpu_count
            ),
        ]
        try:
            memory = self._memory()
        except (OSError, psutil.Error):
            evidence.extend(
                _unavailable(key, source)
                for key in (
                    "system.memory.total_bytes",
                    "system.memory.available_bytes",
                    "system.memory.percent_used",
                )
            )
        else:
            evidence.extend(
                (
                    Evidence(
                        key="system.memory.total_bytes",
                        source=source,
                        value=memory.total,
                    ),
                    Evidence(
                        key="system.memory.available_bytes",
                        source=source,
                        value=memory.available,
                    ),
                    Evidence(
                        key="system.memory.percent_used",
                        source=source,
                        value=memory.percent,
                    ),
                )
            )
        try:
            disk = self._disk("/")
        except (OSError, psutil.Error):
            evidence.extend(
                _unavailable(key, source)
                for key in (
                    "system.disk.root.total_bytes",
                    "system.disk.root.free_bytes",
                    "system.disk.root.percent_used",
                )
            )
        else:
            evidence.extend(
                (
                    Evidence(
                        key="system.disk.root.total_bytes",
                        source=source,
                        value=disk.total,
                    ),
                    Evidence(
                        key="system.disk.root.free_bytes",
                        source=source,
                        value=disk.free,
                    ),
                    Evidence(
                        key="system.disk.root.percent_used",
                        source=source,
                        value=disk.percent,
                    ),
                )
            )
        return evidence


def _memory_snapshot() -> MemorySnapshot:
    value = psutil.virtual_memory()
    return MemorySnapshot(value.total, value.available, value.percent)


def _disk_snapshot(path: str) -> DiskSnapshot:
    value = psutil.disk_usage(path)
    return DiskSnapshot(value.total, value.free, value.percent)


def _optional_evidence(
    key: str, source: str, provider: Callable[[], int | None]
) -> Evidence:
    value = provider()
    if value is None:
        return _unavailable(key, source)
    return Evidence(key=key, source=source, value=value)


def _unavailable(key: str, source: str) -> Evidence:
    return Evidence(
        key=key,
        source=source,
        availability=EvidenceAvailability.UNAVAILABLE,
    )
