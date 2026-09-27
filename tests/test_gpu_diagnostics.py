from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence, EvidenceAvailability
from makermedic.diagnostics.gpu import (
    CudaAllocationRule,
    CudaComputeRule,
    NvidiaDriverRule,
    NvidiaHardwareRule,
    NvmlRule,
    PyTorchCudaBuildRule,
    PyTorchCudaVisibilityRule,
    PyTorchInstallationRule,
)


def make_store(
    values: dict[str, object], unavailable: tuple[str, ...] = ()
) -> EvidenceStore:
    evidence = [
        Evidence(key=key, source="test", value=value) for key, value in values.items()
    ]
    evidence.extend(
        Evidence(key=key, source="test", availability=EvidenceAvailability.UNAVAILABLE)
        for key in unavailable
    )
    return EvidenceStore(evidence)


def test_hardware_rule_detected_absent_and_unknown() -> None:
    rule = NvidiaHardwareRule()
    assert (
        rule.evaluate(make_store({"gpu.nvidia.hardware_detected": True})).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(make_store({"gpu.nvidia.hardware_detected": False})).status
        is DiagnosticStatus.WARN
    )
    assert rule.evaluate(EvidenceStore()).status is DiagnosticStatus.UNKNOWN


def test_driver_rule_pass_fail_and_blocked() -> None:
    rule = NvidiaDriverRule()
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.nvidia.hardware_detected": True,
                    "gpu.nvidia.driver.available": True,
                }
            )
        ).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.nvidia.hardware_detected": True,
                    "gpu.nvidia.driver.available": False,
                }
            )
        ).status
        is DiagnosticStatus.FAIL
    )
    assert (
        rule.evaluate(make_store({"gpu.nvidia.hardware_detected": False})).status
        is DiagnosticStatus.UNKNOWN
    )


def test_nvml_rule_pass_warn_and_blocked() -> None:
    rule = NvmlRule()
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.nvidia.hardware_detected": True,
                    "gpu.nvidia.driver.available": True,
                    "gpu.nvidia.nvml.available": True,
                }
            )
        ).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.nvidia.hardware_detected": True,
                    "gpu.nvidia.driver.available": True,
                    "gpu.nvidia.nvml.available": False,
                }
            )
        ).status
        is DiagnosticStatus.WARN
    )
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.nvidia.hardware_detected": True,
                    "gpu.nvidia.driver.available": False,
                }
            )
        ).status
        is DiagnosticStatus.UNKNOWN
    )


def test_pytorch_installation_absent_import_failure_and_success() -> None:
    rule = PyTorchInstallationRule()
    assert (
        rule.evaluate(make_store({"gpu.pytorch.installed": False})).status
        is DiagnosticStatus.WARN
    )
    assert (
        rule.evaluate(
            make_store(
                {"gpu.pytorch.installed": True, "gpu.pytorch.import_success": False}
            )
        ).status
        is DiagnosticStatus.FAIL
    )
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.pytorch.installed": True,
                    "gpu.pytorch.import_success": True,
                    "gpu.pytorch.version": "2.5",
                }
            )
        ).status
        is DiagnosticStatus.PASS
    )


def test_cpu_only_build_warns_without_driver_blame() -> None:
    store = make_store(
        {
            "gpu.pytorch.installed": True,
            "gpu.pytorch.import_success": True,
            "gpu.pytorch.cuda.build_version": None,
        }
    )

    result = PyTorchCudaBuildRule().evaluate(store)

    assert result.status is DiagnosticStatus.WARN
    assert "driver" not in result.summary.casefold()


def test_cuda_build_present_passes_and_absent_torch_blocks() -> None:
    rule = PyTorchCudaBuildRule()
    assert (
        rule.evaluate(
            make_store(
                {
                    "gpu.pytorch.installed": True,
                    "gpu.pytorch.import_success": True,
                    "gpu.pytorch.cuda.build_version": "12.4",
                }
            )
        ).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(make_store({"gpu.pytorch.installed": False})).status
        is DiagnosticStatus.UNKNOWN
    )


def visibility_store(
    *, available: bool, count: int, visible: str | None = None
) -> EvidenceStore:
    return make_store(
        {
            "gpu.nvidia.hardware_detected": True,
            "gpu.nvidia.driver.available": True,
            "gpu.pytorch.cuda.build_version": "12.4",
            "gpu.pytorch.cuda.available": available,
            "gpu.pytorch.cuda.device_count": count,
            "gpu.cuda_visible_devices.set": visible is not None,
            "gpu.cuda_visible_devices.value": visible,
        }
    )


def test_cuda_visibility_pass_fail_and_restricted_warn() -> None:
    rule = PyTorchCudaVisibilityRule()
    assert (
        rule.evaluate(visibility_store(available=True, count=1)).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(visibility_store(available=False, count=0)).status
        is DiagnosticStatus.FAIL
    )
    assert (
        rule.evaluate(visibility_store(available=False, count=0, visible="")).status
        is DiagnosticStatus.WARN
    )


def test_cuda_visibility_is_unknown_without_graph_prerequisites() -> None:
    rule = PyTorchCudaVisibilityRule()
    no_hardware = make_store({"gpu.nvidia.hardware_detected": False})
    bad_driver = make_store(
        {"gpu.nvidia.hardware_detected": True, "gpu.nvidia.driver.available": False}
    )
    assert rule.evaluate(no_hardware).status is DiagnosticStatus.UNKNOWN
    assert rule.evaluate(bad_driver).status is DiagnosticStatus.UNKNOWN


def test_allocation_rule_blocked_pass_fail_and_error() -> None:
    rule = CudaAllocationRule()
    blocked = make_store(
        {
            "gpu.pytorch.cuda.available": False,
            "gpu.pytorch.cuda.device_count": 0,
            "gpu.pytorch.cuda.allocation_test.attempted": False,
        }
    )
    passed = make_store(
        {
            "gpu.pytorch.cuda.available": True,
            "gpu.pytorch.cuda.device_count": 1,
            "gpu.pytorch.cuda.allocation_test.attempted": True,
            "gpu.pytorch.cuda.allocation_test.success": True,
        }
    )
    failed = make_store(
        {
            "gpu.pytorch.cuda.available": True,
            "gpu.pytorch.cuda.device_count": 1,
            "gpu.pytorch.cuda.allocation_test.attempted": True,
            "gpu.pytorch.cuda.allocation_test.success": False,
            "gpu.pytorch.cuda.allocation_test.error": "CUDA out of memory",
        }
    )
    assert rule.evaluate(blocked).status is DiagnosticStatus.UNKNOWN
    assert rule.evaluate(passed).status is DiagnosticStatus.PASS
    result = rule.evaluate(failed)
    assert result.status is DiagnosticStatus.FAIL
    assert result.causes == ("CUDA out of memory",)


def test_compute_rule_blocked_pass_and_fail() -> None:
    rule = CudaComputeRule()
    blocked = make_store({}, ("gpu.pytorch.cuda.allocation_test.success",))
    passed = make_store(
        {
            "gpu.pytorch.cuda.allocation_test.success": True,
            "gpu.pytorch.cuda.compute_test.attempted": True,
            "gpu.pytorch.cuda.compute_test.success": True,
        }
    )
    failed = make_store(
        {
            "gpu.pytorch.cuda.allocation_test.success": True,
            "gpu.pytorch.cuda.compute_test.attempted": True,
            "gpu.pytorch.cuda.compute_test.success": False,
        }
    )
    assert rule.evaluate(blocked).status is DiagnosticStatus.UNKNOWN
    assert rule.evaluate(passed).status is DiagnosticStatus.PASS
    assert rule.evaluate(failed).status is DiagnosticStatus.FAIL


def test_no_hardware_chain_has_no_failures() -> None:
    store = make_store(
        {
            "gpu.nvidia.hardware_detected": False,
            "gpu.pytorch.installed": False,
            "gpu.pytorch.cuda.allocation_test.attempted": False,
            "gpu.pytorch.cuda.compute_test.attempted": False,
        }
    )
    rules = [
        NvidiaHardwareRule(),
        NvidiaDriverRule(),
        NvmlRule(),
        PyTorchInstallationRule(),
        PyTorchCudaBuildRule(),
        PyTorchCudaVisibilityRule(),
        CudaAllocationRule(),
        CudaComputeRule(),
    ]

    assert all(
        rule.evaluate(store).status is not DiagnosticStatus.FAIL for rule in rules
    )


def test_complete_stack_passes_through_compute() -> None:
    store = make_store(
        {
            "gpu.nvidia.hardware_detected": True,
            "gpu.nvidia.hardware_count": 1,
            "gpu.nvidia.driver.available": True,
            "gpu.nvidia.nvml.available": True,
            "gpu.pytorch.installed": True,
            "gpu.pytorch.import_success": True,
            "gpu.pytorch.version": "2.5",
            "gpu.pytorch.cuda.build_version": "12.4",
            "gpu.pytorch.cuda.available": True,
            "gpu.pytorch.cuda.device_count": 1,
            "gpu.cuda_visible_devices.set": False,
            "gpu.cuda_visible_devices.value": None,
            "gpu.pytorch.cuda.allocation_test.attempted": True,
            "gpu.pytorch.cuda.allocation_test.success": True,
            "gpu.pytorch.cuda.compute_test.attempted": True,
            "gpu.pytorch.cuda.compute_test.success": True,
        }
    )
    rules = [
        NvidiaHardwareRule(),
        NvidiaDriverRule(),
        NvmlRule(),
        PyTorchInstallationRule(),
        PyTorchCudaBuildRule(),
        PyTorchCudaVisibilityRule(),
        CudaAllocationRule(),
        CudaComputeRule(),
    ]

    assert all(rule.evaluate(store).status is DiagnosticStatus.PASS for rule in rules)
