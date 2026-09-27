"""NVIDIA, NVML, and optional PyTorch evidence collection."""

import importlib
import importlib.util
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from makermedic.core.commands import CommandRunner, CommandStatus
from makermedic.core.models import Evidence, EvidenceAvailability


class NvidiaHardwareProbe:
    """Discover NVIDIA display controllers through Linux PCI sysfs."""

    id = "gpu.nvidia.hardware"
    categories = ("gpu",)

    def __init__(self, pci_root: Path = Path("/sys/bus/pci/devices")) -> None:
        self._pci_root = pci_root

    def collect(self) -> Iterable[Evidence]:
        try:
            entries = tuple(self._pci_root.iterdir())
            devices = [
                {"pci_address": entry.name}
                for entry in entries
                if _is_nvidia_display_device(entry)
            ]
        except OSError:
            return (
                _unavailable("gpu.nvidia.hardware_detected", self.id),
                _unavailable("gpu.nvidia.hardware_count", self.id),
                _unavailable("gpu.nvidia.hardware_devices", self.id),
            )
        return (
            Evidence(
                key="gpu.nvidia.hardware_detected",
                source=self.id,
                value=bool(devices),
            ),
            Evidence(
                key="gpu.nvidia.hardware_count", source=self.id, value=len(devices)
            ),
            Evidence(key="gpu.nvidia.hardware_devices", source=self.id, value=devices),
        )


class NvidiaSmiProbe:
    """Collect one bounded NVIDIA driver/device snapshot."""

    id = "gpu.nvidia.smi"
    categories = ("gpu",)
    _QUERY = (
        "nvidia-smi",
        "--query-gpu=index,name,driver_version,memory.total,memory.used,"
        "utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    )

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or CommandRunner()

    def collect(self) -> Iterable[Evidence]:
        result = self._runner.run(self._QUERY)
        source = self.id
        outcome = result.status.value
        if result.status is CommandStatus.NOT_FOUND:
            return _smi_evidence(source, False, False, outcome=outcome)
        if result.status is CommandStatus.TIMED_OUT:
            return _smi_evidence(source, True, None, outcome=outcome)
        if result.return_code != 0:
            return _smi_evidence(
                source,
                True,
                False,
                outcome=outcome,
                return_code=result.return_code,
                error=_concise(result.stderr or result.stdout),
            )
        devices = _parse_smi_devices(result.stdout)
        if devices is None:
            return _smi_evidence(
                source,
                True,
                None,
                outcome="MALFORMED_OUTPUT",
                return_code=result.return_code,
            )
        driver_version = devices[0]["driver_version"] if devices else None
        return _smi_evidence(
            source,
            True,
            True,
            outcome=outcome,
            return_code=result.return_code,
            driver_version=driver_version,
            devices=devices,
        )


class NvmlProbe:
    """Verify that the NVML binding can initialize and enumerate devices."""

    id = "gpu.nvidia.nvml"
    categories = ("gpu",)

    def __init__(self, loader: Callable[[], Any] | None = None) -> None:
        self._loader = loader or (lambda: importlib.import_module("pynvml"))

    def collect(self) -> Iterable[Evidence]:
        try:
            nvml = self._loader()
        except (ImportError, ModuleNotFoundError) as error:
            return _nvml_evidence(False, False, error=_error_text(error))

        initialized = False
        count: int | None = None
        names: list[str] | None = None
        failure: BaseException | None = None
        try:
            nvml.nvmlInit()
            initialized = True
            count = int(nvml.nvmlDeviceGetCount())
            names = [
                _as_string(nvml.nvmlDeviceGetName(nvml.nvmlDeviceGetHandleByIndex(i)))
                for i in range(count)
            ]
        except Exception as error:  # narrow third-party library boundary
            failure = error
        finally:
            if initialized:
                try:
                    nvml.nvmlShutdown()
                except Exception as error:  # narrow third-party library boundary
                    failure = failure or error
        if failure is not None:
            return _nvml_evidence(True, False, error=_error_text(failure))
        return _nvml_evidence(True, True, count=count, names=names)


class PyTorchProbe:
    """Collect optional PyTorch/CUDA facts and tiny smoke-test outcomes."""

    id = "gpu.pytorch"
    categories = ("gpu",)

    def __init__(
        self,
        *,
        find_spec: Callable[[str], object | None] = importlib.util.find_spec,
        importer: Callable[[str], ModuleType] = importlib.import_module,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._find_spec = find_spec
        self._importer = importer
        self._environment = environment if environment is not None else os.environ

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        visible_set = "CUDA_VISIBLE_DEVICES" in self._environment
        visible_value = self._environment.get("CUDA_VISIBLE_DEVICES")
        base = [
            Evidence(key="gpu.pytorch.installed", source=source, value=False),
            Evidence(
                key="gpu.cuda_visible_devices.set", source=source, value=visible_set
            ),
            Evidence(
                key="gpu.cuda_visible_devices.value",
                source=source,
                value=visible_value,
            ),
        ]
        try:
            installed = self._find_spec("torch") is not None
        except (ImportError, ValueError):
            installed = False
        if not installed:
            return (*base, *_unavailable_torch_facts(source))
        base[0] = Evidence(key="gpu.pytorch.installed", source=source, value=True)
        try:
            torch = self._importer("torch")
        except Exception as error:  # narrow optional import boundary
            return (
                *base,
                Evidence(key="gpu.pytorch.import_success", source=source, value=False),
                Evidence(
                    key="gpu.pytorch.import_error",
                    source=source,
                    value=_error_text(error),
                ),
                *_unavailable_torch_runtime_facts(source),
            )
        return (*base, *self._collect_torch_runtime(torch))

    def _collect_torch_runtime(self, torch: Any) -> tuple[Evidence, ...]:
        source = self.id
        try:
            version = str(torch.__version__)
            build_version = torch.version.cuda
            cuda_available = bool(torch.cuda.is_available())
            device_count = int(torch.cuda.device_count())
            devices = [
                {"index": index, "name": str(torch.cuda.get_device_name(index))}
                for index in range(device_count)
            ]
        except Exception as error:  # narrow optional runtime boundary
            return (
                Evidence(key="gpu.pytorch.import_success", source=source, value=True),
                _unavailable("gpu.pytorch.import_error", source),
                Evidence(
                    key="gpu.pytorch.version",
                    source=source,
                    value=str(torch.__version__),
                ),
                Evidence(
                    key="gpu.pytorch.runtime_error",
                    source=source,
                    value=_error_text(error),
                ),
                *_unavailable_cuda_facts(source),
            )

        evidence = [
            Evidence(key="gpu.pytorch.import_success", source=source, value=True),
            _unavailable("gpu.pytorch.import_error", source),
            Evidence(key="gpu.pytorch.version", source=source, value=version),
            _unavailable("gpu.pytorch.runtime_error", source),
            Evidence(
                key="gpu.pytorch.cuda.build_version",
                source=source,
                value=build_version,
            ),
            Evidence(
                key="gpu.pytorch.cuda.available", source=source, value=cuda_available
            ),
            Evidence(
                key="gpu.pytorch.cuda.device_count", source=source, value=device_count
            ),
            Evidence(key="gpu.pytorch.cuda.devices", source=source, value=devices),
        ]
        prerequisites = (
            build_version is not None and cuda_available and device_count > 0
        )
        if not prerequisites:
            evidence.extend(_not_attempted_smoke_facts(source))
            return tuple(evidence)
        try:
            allocation = torch.empty(1, device="cuda:0")
        except Exception as error:
            evidence.extend(_smoke_failure("allocation", source, _error_text(error)))
            evidence.extend(_not_attempted_compute_facts(source))
            return tuple(evidence)
        evidence.extend(_smoke_success("allocation", source))
        try:
            result = (
                (
                    torch.tensor([1.0], device="cuda:0")
                    + torch.tensor([2.0], device="cuda:0")
                )
                .cpu()
                .item()
            )
            computation_success = result == 3.0
            if not computation_success:
                raise ValueError(f"unexpected result: {result!r}")
            del allocation
        except Exception as error:
            evidence.extend(_smoke_failure("compute", source, _error_text(error)))
        else:
            evidence.extend(_smoke_success("compute", source))
        return tuple(evidence)


def _is_nvidia_display_device(entry: Path) -> bool:
    return entry.joinpath(
        "vendor"
    ).read_text().strip().casefold() == "0x10de" and entry.joinpath(
        "class"
    ).read_text().strip().casefold().startswith("0x03")


def _parse_smi_devices(output: str) -> list[dict[str, object]] | None:
    if not output.strip():
        return []
    devices = []
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 7:
            return None
        try:
            devices.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "driver_version": fields[2],
                    "memory_total_mib": int(fields[3]),
                    "memory_used_mib": int(fields[4]),
                    "utilization_percent": int(fields[5]),
                    "temperature_celsius": int(fields[6]),
                }
            )
        except ValueError:
            return None
    return devices


def _smi_evidence(
    source: str,
    smi_available: bool,
    driver_available: bool | None,
    *,
    outcome: str,
    return_code: int | None = None,
    error: str | None = None,
    driver_version: object | None = None,
    devices: list[dict[str, object]] | None = None,
) -> tuple[Evidence, ...]:
    driver_details_available = driver_available is True
    devices = devices or []
    return (
        Evidence(key="gpu.nvidia.smi.available", source=source, value=smi_available),
        _optional("gpu.nvidia.driver.available", source, driver_available),
        _optional("gpu.nvidia.driver.version", source, driver_version),
        Evidence(key="gpu.nvidia.smi.outcome", source=source, value=outcome),
        _optional("gpu.nvidia.smi.return_code", source, return_code),
        _optional("gpu.nvidia.smi.error", source, error),
        _optional(
            "gpu.nvidia.driver.device_count",
            source,
            len(devices) if driver_details_available else None,
        ),
        _optional(
            "gpu.nvidia.driver.devices",
            source,
            devices if driver_details_available else None,
        ),
    )


def _nvml_evidence(
    binding: bool,
    available: bool,
    *,
    count: int | None = None,
    names: list[str] | None = None,
    error: str | None = None,
) -> tuple[Evidence, ...]:
    source = NvmlProbe.id
    return (
        Evidence(key="gpu.nvidia.nvml.binding_available", source=source, value=binding),
        Evidence(key="gpu.nvidia.nvml.available", source=source, value=available),
        _optional("gpu.nvidia.nvml.device_count", source, count),
        _optional("gpu.nvidia.nvml.device_names", source, names),
        _optional("gpu.nvidia.nvml.error", source, error),
    )


def _unavailable_torch_facts(source: str) -> tuple[Evidence, ...]:
    return (
        _unavailable("gpu.pytorch.import_success", source),
        _unavailable("gpu.pytorch.import_error", source),
        *_unavailable_torch_runtime_facts(source),
    )


def _unavailable_torch_runtime_facts(source: str) -> tuple[Evidence, ...]:
    return (
        _unavailable("gpu.pytorch.version", source),
        _unavailable("gpu.pytorch.runtime_error", source),
        *_unavailable_cuda_facts(source),
    )


def _unavailable_cuda_facts(source: str) -> tuple[Evidence, ...]:
    keys = (
        "gpu.pytorch.cuda.build_version",
        "gpu.pytorch.cuda.available",
        "gpu.pytorch.cuda.device_count",
        "gpu.pytorch.cuda.devices",
    )
    return (
        *(_unavailable(key, source) for key in keys),
        *_not_attempted_smoke_facts(source),
    )


def _not_attempted_smoke_facts(source: str) -> tuple[Evidence, ...]:
    return (
        Evidence(
            key="gpu.pytorch.cuda.allocation_test.attempted", source=source, value=False
        ),
        _unavailable("gpu.pytorch.cuda.allocation_test.success", source),
        _unavailable("gpu.pytorch.cuda.allocation_test.error", source),
        *_not_attempted_compute_facts(source),
    )


def _not_attempted_compute_facts(source: str) -> tuple[Evidence, ...]:
    return (
        Evidence(
            key="gpu.pytorch.cuda.compute_test.attempted", source=source, value=False
        ),
        _unavailable("gpu.pytorch.cuda.compute_test.success", source),
        _unavailable("gpu.pytorch.cuda.compute_test.error", source),
    )


def _smoke_success(kind: str, source: str) -> tuple[Evidence, ...]:
    prefix = f"gpu.pytorch.cuda.{kind}_test"
    return (
        Evidence(key=f"{prefix}.attempted", source=source, value=True),
        Evidence(key=f"{prefix}.success", source=source, value=True),
        _unavailable(f"{prefix}.error", source),
    )


def _smoke_failure(kind: str, source: str, error: str) -> tuple[Evidence, ...]:
    prefix = f"gpu.pytorch.cuda.{kind}_test"
    return (
        Evidence(key=f"{prefix}.attempted", source=source, value=True),
        Evidence(key=f"{prefix}.success", source=source, value=False),
        Evidence(key=f"{prefix}.error", source=source, value=error),
    )


def _optional(key: str, source: str, value: object | None) -> Evidence:
    if value is None:
        return _unavailable(key, source)
    return Evidence(key=key, source=source, value=value)


def _unavailable(key: str, source: str) -> Evidence:
    return Evidence(
        key=key, source=source, availability=EvidenceAvailability.UNAVAILABLE
    )


def _error_text(error: BaseException) -> str:
    return _concise(f"{type(error).__name__}: {error}")


def _concise(value: str) -> str:
    return " ".join(value.split())[:300]


def _as_string(value: str | bytes) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
