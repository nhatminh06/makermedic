from collections.abc import Sequence
from pathlib import Path

import pytest

from makermedic.core.commands import CommandResult, CommandStatus
from makermedic.core.models import EvidenceAvailability
from makermedic.probes.gpu import NvidiaHardwareProbe, NvidiaSmiProbe, NvmlProbe


class FakeRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(args))
        return self.result


def values(probe: object) -> dict[str, object]:
    return {item.key: item.value for item in probe.collect()}  # type: ignore[attr-defined]


def add_pci_device(root: Path, address: str, vendor: str, device_class: str) -> None:
    device = root / address
    device.mkdir()
    device.joinpath("vendor").write_text(vendor)
    device.joinpath("class").write_text(device_class)


def test_nvidia_hardware_detected(tmp_path: Path) -> None:
    add_pci_device(tmp_path, "0000:01:00.0", "0x10de", "0x030000")

    result = values(NvidiaHardwareProbe(tmp_path))

    assert result["gpu.nvidia.hardware_detected"] is True
    assert result["gpu.nvidia.hardware_count"] == 1


def test_no_nvidia_hardware(tmp_path: Path) -> None:
    add_pci_device(tmp_path, "0000:00:02.0", "0x8086", "0x030000")

    result = values(NvidiaHardwareProbe(tmp_path))

    assert result["gpu.nvidia.hardware_detected"] is False
    assert result["gpu.nvidia.hardware_count"] == 0


def test_multiple_nvidia_devices_and_audio_function_excluded(tmp_path: Path) -> None:
    add_pci_device(tmp_path, "0000:01:00.0", "0x10de", "0x030000")
    add_pci_device(tmp_path, "0000:02:00.0", "0x10de", "0x030200")
    add_pci_device(tmp_path, "0000:01:00.1", "0x10de", "0x040300")

    result = values(NvidiaHardwareProbe(tmp_path))

    assert result["gpu.nvidia.hardware_count"] == 2


def test_hardware_evidence_unavailable(tmp_path: Path) -> None:
    evidence = list(NvidiaHardwareProbe(tmp_path / "missing").collect())

    assert all(
        item.availability is EvidenceAvailability.UNAVAILABLE for item in evidence
    )


SMI_LINE = "0, NVIDIA Test GPU, 555.42, 8192, 128, 4, 42\n"


def command_result(
    *,
    status: CommandStatus = CommandStatus.COMPLETED,
    code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        args=("nvidia-smi",),
        status=status,
        return_code=code,
        stdout=stdout,
        stderr=stderr,
    )


def test_nvidia_smi_success_parses_driver_and_device() -> None:
    runner = FakeRunner(command_result(stdout=SMI_LINE))

    result = values(NvidiaSmiProbe(runner))  # type: ignore[arg-type]

    assert result["gpu.nvidia.smi.available"] is True
    assert result["gpu.nvidia.driver.available"] is True
    assert result["gpu.nvidia.driver.version"] == "555.42"
    assert result["gpu.nvidia.driver.device_count"] == 1
    assert result["gpu.nvidia.driver.devices"][0]["memory_total_mib"] == 8192
    assert runner.calls[0][0] == "nvidia-smi"


def test_nvidia_smi_multiple_devices() -> None:
    output = SMI_LINE + "1, NVIDIA Second GPU, 555.42, 4096, 0, 0, 35\n"

    result = values(NvidiaSmiProbe(FakeRunner(command_result(stdout=output))))  # type: ignore[arg-type]

    assert result["gpu.nvidia.driver.device_count"] == 2


@pytest.mark.parametrize(
    ("result", "smi_available", "driver_available"),
    [
        (command_result(status=CommandStatus.NOT_FOUND, code=None), False, False),
        (command_result(code=9, stderr="driver communication failed"), True, False),
    ],
)
def test_nvidia_smi_absent_or_failed(
    result: CommandResult,
    smi_available: bool,
    driver_available: bool,
) -> None:
    collected = values(NvidiaSmiProbe(FakeRunner(result)))  # type: ignore[arg-type]

    assert collected["gpu.nvidia.smi.available"] is smi_available
    assert collected["gpu.nvidia.driver.available"] is driver_available


def test_nvidia_smi_failure_captures_concise_stdout_when_stderr_empty() -> None:
    result = command_result(code=9, stdout="driver communication failed\n")

    collected = values(NvidiaSmiProbe(FakeRunner(result)))  # type: ignore[arg-type]

    assert collected["gpu.nvidia.smi.error"] == "driver communication failed"


@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        (command_result(stdout="not,csv"), "MALFORMED_OUTPUT"),
        (command_result(status=CommandStatus.TIMED_OUT, code=None), "TIMED_OUT"),
    ],
)
def test_nvidia_smi_malformed_or_timeout_is_unknown(
    result: CommandResult, outcome: str
) -> None:
    evidence = {item.key: item for item in NvidiaSmiProbe(FakeRunner(result)).collect()}  # type: ignore[arg-type]

    assert (
        evidence["gpu.nvidia.driver.available"].availability
        is EvidenceAvailability.UNAVAILABLE
    )
    assert evidence["gpu.nvidia.smi.outcome"].value == outcome


class FakeNvml:
    def __init__(self, count: int = 1, init_error: Exception | None = None) -> None:
        self.count = count
        self.init_error = init_error
        self.shutdowns = 0

    def nvmlInit(self) -> None:
        if self.init_error:
            raise self.init_error

    def nvmlDeviceGetCount(self) -> int:
        return self.count

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        return index

    def nvmlDeviceGetName(self, index: int) -> str:
        return f"GPU {index}"

    def nvmlShutdown(self) -> None:
        self.shutdowns += 1


@pytest.mark.parametrize("count", [0, 2])
def test_nvml_success_counts_devices_and_shuts_down(count: int) -> None:
    nvml = FakeNvml(count=count)

    result = values(NvmlProbe(loader=lambda: nvml))

    assert result["gpu.nvidia.nvml.available"] is True
    assert result["gpu.nvidia.nvml.device_count"] == count
    assert nvml.shutdowns == 1


def test_nvml_binding_unavailable() -> None:
    def unavailable() -> FakeNvml:
        raise ModuleNotFoundError("pynvml")

    result = values(NvmlProbe(loader=unavailable))

    assert result["gpu.nvidia.nvml.binding_available"] is False
    assert result["gpu.nvidia.nvml.available"] is False


def test_nvml_initialization_failure_does_not_shutdown() -> None:
    nvml = FakeNvml(init_error=RuntimeError("driver unavailable"))

    result = values(NvmlProbe(loader=lambda: nvml))

    assert result["gpu.nvidia.nvml.available"] is False
    assert "driver unavailable" in result["gpu.nvidia.nvml.error"]
    assert nvml.shutdowns == 0
