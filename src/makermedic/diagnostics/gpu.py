"""Focused deterministic NVIDIA, NVML, and PyTorch/CUDA rules."""

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticStatus,
    EvidenceAvailability,
    FindingKind,
    dependency_state_for_status,
)


class NvidiaHardwareRule:
    id = "gpu.nvidia.hardware"
    category = "gpu"
    dependencies = ()
    required_evidence = frozenset({"gpu.nvidia.hardware_detected"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        detected = _value(evidence, "gpu.nvidia.hardware_detected", bool)
        count = _number(evidence, "gpu.nvidia.hardware_count")
        if detected is None:
            status, summary = DiagnosticStatus.UNKNOWN, "NVIDIA hardware is unknown"
        elif detected:
            status, summary = (
                DiagnosticStatus.PASS,
                f"NVIDIA hardware detected ({count or 1})",
            )
        else:
            status, summary = DiagnosticStatus.WARN, "No NVIDIA GPU detected"
        return _result(
            self,
            status,
            summary,
            recommendations=(
                "NVIDIA/CUDA diagnostics do not apply without NVIDIA hardware.",
            )
            if status is DiagnosticStatus.WARN
            else (),
            finding_kind=FindingKind.OPTIONAL_ABSENCE,
        )


class NvidiaDriverRule:
    id = "gpu.nvidia.driver"
    category = "gpu"
    dependencies = ("gpu.nvidia.hardware",)
    required_evidence = frozenset(
        {"gpu.nvidia.hardware_detected", "gpu.nvidia.driver.available"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        driver = _value(evidence, "gpu.nvidia.driver.available", bool)
        version = _value(evidence, "gpu.nvidia.driver.version", str)
        error = _value(evidence, "gpu.nvidia.smi.error", str)
        if driver is None:
            status, summary = DiagnosticStatus.UNKNOWN, "NVIDIA driver state is unknown"
        elif driver:
            status, summary = DiagnosticStatus.PASS, "NVIDIA driver is operational"
        else:
            status, summary = (
                DiagnosticStatus.FAIL,
                "NVIDIA driver communication failed",
            )
        causes = tuple(
            value
            for value in (f"Driver: {version}" if version else None, error)
            if value
        )
        return _result(
            self,
            status,
            summary,
            causes=causes,
            recommendations=(
                "Verify the NVIDIA driver and confirm `nvidia-smi` can communicate "
                "with the GPU.",
            )
            if status is DiagnosticStatus.FAIL
            else (),
        )


class NvmlRule:
    """NVML failure is WARN because nvidia-smi can remain operational."""

    id = "gpu.nvidia.nvml"
    category = "gpu"
    dependencies = ("gpu.nvidia.driver",)
    required_evidence = frozenset(
        {
            "gpu.nvidia.hardware_detected",
            "gpu.nvidia.driver.available",
            "gpu.nvidia.nvml.available",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        available = _value(evidence, "gpu.nvidia.nvml.available", bool)
        error = _value(evidence, "gpu.nvidia.nvml.error", str)
        if available is None:
            status, summary = DiagnosticStatus.UNKNOWN, "NVML state is unknown"
        elif available:
            status, summary = DiagnosticStatus.PASS, "NVML is operational"
        else:
            status, summary = DiagnosticStatus.WARN, "NVML could not initialize"
        return _result(
            self,
            status,
            summary,
            causes=(error,) if error else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class PyTorchInstallationRule:
    id = "gpu.pytorch.installation"
    category = "gpu"
    dependencies = ()
    required_evidence = frozenset(
        {"gpu.pytorch.installed", "gpu.pytorch.import_success"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        installed = _value(evidence, "gpu.pytorch.installed", bool)
        imported = _value(evidence, "gpu.pytorch.import_success", bool)
        version = _value(evidence, "gpu.pytorch.version", str)
        error = _value(evidence, "gpu.pytorch.import_error", str)
        if installed is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "PyTorch installation state is unknown",
            )
        elif not installed:
            status, summary = DiagnosticStatus.WARN, "PyTorch is not installed"
        elif imported is False:
            status, summary = (
                DiagnosticStatus.FAIL,
                "PyTorch is installed but cannot be imported",
            )
        elif imported is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "PyTorch import state is unknown",
            )
        else:
            status, summary = (
                DiagnosticStatus.PASS,
                f"PyTorch {version or ''} is importable".strip(),
            )
        return _result(
            self,
            status,
            summary,
            causes=(error,) if error else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class PyTorchCudaBuildRule:
    id = "gpu.pytorch.cuda_build"
    category = "gpu"
    dependencies = ("gpu.pytorch.installation",)
    required_evidence = frozenset(
        {
            "gpu.pytorch.installed",
            "gpu.pytorch.import_success",
            "gpu.pytorch.cuda.build_version",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        build_item = evidence.get("gpu.pytorch.cuda.build_version")
        build = _value(evidence, "gpu.pytorch.cuda.build_version", str)
        if (
            build_item is None
            or build_item.availability is EvidenceAvailability.UNAVAILABLE
        ):
            status, summary = DiagnosticStatus.UNKNOWN, "PyTorch CUDA build is unknown"
        elif build is None:
            status, summary = (
                DiagnosticStatus.WARN,
                "PyTorch build does not include CUDA support",
            )
        else:
            status, summary = DiagnosticStatus.PASS, f"PyTorch CUDA build {build}"
        return _result(
            self,
            status,
            summary,
            recommendations=(
                "Verify that a CUDA-enabled PyTorch build is appropriate for this "
                "environment.",
            )
            if status is DiagnosticStatus.WARN
            else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class PyTorchCudaVisibilityRule:
    id = "gpu.pytorch.cuda_visibility"
    category = "gpu"
    dependencies = ("gpu.nvidia.driver", "gpu.pytorch.cuda_build")
    required_evidence = frozenset(
        {
            "gpu.nvidia.hardware_detected",
            "gpu.nvidia.driver.available",
            "gpu.pytorch.cuda.build_version",
            "gpu.pytorch.cuda.available",
            "gpu.pytorch.cuda.device_count",
            "gpu.cuda_visible_devices.set",
            "gpu.cuda_visible_devices.value",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        available = _value(evidence, "gpu.pytorch.cuda.available", bool)
        count = _number(evidence, "gpu.pytorch.cuda.device_count")
        visible_set = _value(evidence, "gpu.cuda_visible_devices.set", bool)
        visible_value = _nullable_string(evidence, "gpu.cuda_visible_devices.value")
        if None in (available, count):
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "CUDA device visibility is unknown",
            )
        elif available and count > 0:
            status, summary = (
                DiagnosticStatus.PASS,
                f"PyTorch sees {count} CUDA device(s)",
            )
        elif visible_set and visible_value is not None:
            status, summary = (
                DiagnosticStatus.WARN,
                "CUDA devices may be restricted by CUDA_VISIBLE_DEVICES",
            )
        else:
            status, summary = (
                DiagnosticStatus.FAIL,
                "CUDA-enabled PyTorch sees no CUDA devices",
            )
        causes = (
            (f"CUDA_VISIBLE_DEVICES={visible_value!r}",)
            if visible_set and status is DiagnosticStatus.WARN
            else ()
        )
        return _result(
            self,
            status,
            summary,
            causes=causes,
            finding_kind=FindingKind.FAILURE,
        )


class CudaAllocationRule:
    id = "gpu.pytorch.cuda_allocation"
    category = "gpu"
    dependencies = ("gpu.pytorch.cuda_visibility",)
    required_evidence = frozenset(
        {
            "gpu.pytorch.cuda.available",
            "gpu.pytorch.cuda.device_count",
            "gpu.pytorch.cuda.allocation_test.attempted",
            "gpu.pytorch.cuda.allocation_test.success",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        available = _value(evidence, "gpu.pytorch.cuda.available", bool)
        count = _number(evidence, "gpu.pytorch.cuda.device_count")
        attempted = _value(evidence, "gpu.pytorch.cuda.allocation_test.attempted", bool)
        success = _value(evidence, "gpu.pytorch.cuda.allocation_test.success", bool)
        error = _value(evidence, "gpu.pytorch.cuda.allocation_test.error", str)
        if None in (available, count, attempted) or attempted is False:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "CUDA allocation test state is unknown",
            )
        elif success:
            status, summary = DiagnosticStatus.PASS, "Tiny CUDA allocation succeeded"
        elif success is False:
            status, summary = DiagnosticStatus.FAIL, "Tiny CUDA allocation failed"
        else:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "CUDA allocation result is unknown",
            )
        return _result(self, status, summary, causes=(error,) if error else ())


class CudaComputeRule:
    id = "gpu.pytorch.cuda_compute"
    category = "gpu"
    dependencies = ("gpu.pytorch.cuda_allocation",)
    required_evidence = frozenset(
        {
            "gpu.pytorch.cuda.allocation_test.success",
            "gpu.pytorch.cuda.compute_test.attempted",
            "gpu.pytorch.cuda.compute_test.success",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        attempted = _value(evidence, "gpu.pytorch.cuda.compute_test.attempted", bool)
        success = _value(evidence, "gpu.pytorch.cuda.compute_test.success", bool)
        error = _value(evidence, "gpu.pytorch.cuda.compute_test.error", str)
        if attempted is None or attempted is False:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "CUDA computation state is unknown",
            )
        elif success:
            status, summary = DiagnosticStatus.PASS, "Tiny CUDA computation succeeded"
        elif success is False:
            status, summary = DiagnosticStatus.FAIL, "Tiny CUDA computation failed"
        else:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "CUDA computation result is unknown",
            )
        return _result(self, status, summary, causes=(error,) if error else ())


def _result(
    rule: object,
    status: DiagnosticStatus,
    summary: str,
    *,
    causes: tuple[str, ...] = (),
    recommendations: tuple[str, ...] = (),
    finding_kind: FindingKind | None = None,
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id=rule.id,  # type: ignore[attr-defined]
        category=rule.category,  # type: ignore[attr-defined]
        status=status,
        dependency_state=dependency_state_for_status(
            status, warning=DependencyState.UNSATISFIED
        ),
        finding_kind=finding_kind if status is DiagnosticStatus.WARN else None,
        summary=summary,
        evidence=tuple(sorted(rule.required_evidence)),  # type: ignore[attr-defined]
        causes=causes,
        recommendations=recommendations,
    )


def _value[T](evidence: EvidenceStore, key: str, expected: type[T]) -> T | None:
    item = evidence.get(key)
    if (
        item is None
        or item.availability is EvidenceAvailability.UNAVAILABLE
        or not isinstance(item.value, expected)
    ):
        return None
    return item.value


def _number(evidence: EvidenceStore, key: str) -> int | None:
    value = _value(evidence, key, int)
    return None if isinstance(value, bool) else value


def _nullable_string(evidence: EvidenceStore, key: str) -> str | None:
    item = evidence.get(key)
    if item is None or item.availability is EvidenceAvailability.UNAVAILABLE:
        return None
    return item.value if isinstance(item.value, str) else None
