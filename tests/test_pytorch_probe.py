from types import SimpleNamespace
from typing import Any

import pytest

from makermedic.core.models import EvidenceAvailability
from makermedic.probes.gpu import PyTorchProbe


class FakeTensor:
    def __init__(self, value: float) -> None:
        self.value = value

    def __add__(self, other: "FakeTensor") -> "FakeTensor":
        return FakeTensor(self.value + other.value)

    def cpu(self) -> "FakeTensor":
        return self

    def item(self) -> float:
        return self.value


class FakeCuda:
    def __init__(self, available: bool, count: int) -> None:
        self.available = available
        self.count = count

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count

    def get_device_name(self, index: int) -> str:
        return f"Test GPU {index}"


class FakeTorch:
    __version__ = "2.5.0"

    def __init__(
        self,
        *,
        build: str | None,
        available: bool,
        count: int,
        allocation_error: Exception | None = None,
        compute_error: Exception | None = None,
    ) -> None:
        self.version = SimpleNamespace(cuda=build)
        self.cuda = FakeCuda(available, count)
        self.allocation_error = allocation_error
        self.compute_error = compute_error

    def empty(self, _size: int, *, device: str) -> FakeTensor:
        assert device == "cuda:0"
        if self.allocation_error:
            raise self.allocation_error
        return FakeTensor(0)

    def tensor(self, values: list[float], *, device: str) -> FakeTensor:
        assert device == "cuda:0"
        if self.compute_error:
            raise self.compute_error
        return FakeTensor(values[0])


def collect(torch: Any | None, environment: dict[str, str] | None = None):
    installed = torch is not None
    return {
        item.key: item
        for item in PyTorchProbe(
            find_spec=lambda _name: object() if installed else None,
            importer=lambda _name: torch,
            environment=environment or {},
        ).collect()
    }


def test_torch_not_installed() -> None:
    evidence = collect(None)

    assert evidence["gpu.pytorch.installed"].value is False
    assert (
        evidence["gpu.pytorch.version"].availability is EvidenceAvailability.UNAVAILABLE
    )


def test_torch_found_but_import_fails() -> None:
    def broken_import(_name: str):
        raise OSError("shared library missing")

    evidence = {
        item.key: item
        for item in PyTorchProbe(
            find_spec=lambda _name: object(), importer=broken_import, environment={}
        ).collect()
    }

    assert evidence["gpu.pytorch.installed"].value is True
    assert evidence["gpu.pytorch.import_success"].value is False
    assert "shared library missing" in evidence["gpu.pytorch.import_error"].value


@pytest.mark.parametrize(
    ("build", "available", "count"),
    [(None, False, 0), ("12.4", False, 0), ("12.4", True, 1), ("12.4", True, 2)],
)
def test_torch_cuda_build_visibility_and_device_counts(
    build: str | None, available: bool, count: int
) -> None:
    evidence = collect(FakeTorch(build=build, available=available, count=count))

    assert evidence["gpu.pytorch.import_success"].value is True
    assert evidence["gpu.pytorch.cuda.build_version"].value == build
    assert evidence["gpu.pytorch.cuda.available"].value is available
    assert evidence["gpu.pytorch.cuda.device_count"].value == count
    assert len(evidence["gpu.pytorch.cuda.devices"].value) == count


@pytest.mark.parametrize(
    ("environment", "is_set", "value"),
    [
        ({}, False, None),
        ({"CUDA_VISIBLE_DEVICES": ""}, True, ""),
        ({"CUDA_VISIBLE_DEVICES": "0"}, True, "0"),
        ({"CUDA_VISIBLE_DEVICES": "0,1"}, True, "0,1"),
    ],
)
def test_cuda_visible_devices_states(
    environment: dict[str, str], is_set: bool, value: str | None
) -> None:
    evidence = collect(None, environment)

    assert evidence["gpu.cuda_visible_devices.set"].value is is_set
    assert evidence["gpu.cuda_visible_devices.value"].value == value


def test_allocation_and_verified_computation_succeed() -> None:
    evidence = collect(FakeTorch(build="12.4", available=True, count=1))

    assert evidence["gpu.pytorch.cuda.allocation_test.attempted"].value is True
    assert evidence["gpu.pytorch.cuda.allocation_test.success"].value is True
    assert evidence["gpu.pytorch.cuda.compute_test.attempted"].value is True
    assert evidence["gpu.pytorch.cuda.compute_test.success"].value is True


def test_allocation_failure_preserves_oom_message_without_reclassification() -> None:
    torch = FakeTorch(
        build="12.4",
        available=True,
        count=1,
        allocation_error=RuntimeError("CUDA out of memory for test"),
    )

    evidence = collect(torch)

    assert evidence["gpu.pytorch.cuda.allocation_test.success"].value is False
    assert (
        "CUDA out of memory" in evidence["gpu.pytorch.cuda.allocation_test.error"].value
    )
    assert evidence["gpu.pytorch.cuda.compute_test.attempted"].value is False


def test_computation_failure_is_preserved() -> None:
    torch = FakeTorch(
        build="12.4",
        available=True,
        count=1,
        compute_error=RuntimeError("kernel launch failed"),
    )

    evidence = collect(torch)

    assert evidence["gpu.pytorch.cuda.allocation_test.success"].value is True
    assert evidence["gpu.pytorch.cuda.compute_test.success"].value is False
    assert (
        "kernel launch failed" in evidence["gpu.pytorch.cuda.compute_test.error"].value
    )
