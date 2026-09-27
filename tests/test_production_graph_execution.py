from conftest import FakeProbe

from makermedic.core.engine import DiagnosticEngine
from makermedic.core.models import DependencyState, DiagnosticStatus, Evidence
from makermedic.core.registry import Registry
from makermedic.diagnostics.camera import (
    CameraBusyRule,
    CameraPermissionRule,
    CameraPresenceRule,
    FrameCaptureRule,
    OpenCVInstallationRule,
    OpenCVOpenRule,
)
from makermedic.diagnostics.gpu import (
    NvidiaDriverRule,
    NvidiaHardwareRule,
    NvmlRule,
    PyTorchCudaBuildRule,
    PyTorchCudaVisibilityRule,
    PyTorchInstallationRule,
)
from makermedic.diagnostics.service import (
    HostResolutionRule,
    HttpHealthRule,
    HttpReachabilityRule,
    ListenerRule,
    ServiceTargetRule,
    TcpConnectivityRule,
)
from makermedic.diagnostics.usb_serial import (
    SerialBusyRule,
    SerialOpenRule,
    SerialPermissionRule,
    SerialPresenceRule,
)


def execute(rules, values):
    registry = Registry()
    registry.register_probe(
        FakeProbe(
            id="probe.production-chain",
            categories=tuple({rule.category for rule in rules}),
            items=tuple(
                Evidence(key=key, source="probe.production-chain", value=value)
                for key, value in values.items()
            ),
        )
    )
    for rule in rules:
        registry.register_rule(rule)
    return {
        item.diagnostic_id: item for item in DiagnosticEngine(registry).run().results
    }


def test_gpu_absence_blocks_real_downstream_chain_and_records_immediate_ids() -> None:
    results = execute(
        (
            NvidiaHardwareRule(),
            NvidiaDriverRule(),
            NvmlRule(),
            PyTorchInstallationRule(),
            PyTorchCudaBuildRule(),
            PyTorchCudaVisibilityRule(),
        ),
        {
            "gpu.nvidia.hardware_detected": False,
            "gpu.nvidia.hardware_count": 0,
            "gpu.pytorch.installed": False,
        },
    )
    assert (
        results["gpu.nvidia.hardware"].dependency_state is DependencyState.UNSATISFIED
    )
    assert results["gpu.nvidia.driver"].blocked_by == ("gpu.nvidia.hardware",)
    assert results["gpu.nvidia.nvml"].blocked_by == ("gpu.nvidia.driver",)
    assert results["gpu.pytorch.cuda_build"].blocked_by == ("gpu.pytorch.installation",)
    assert results["gpu.pytorch.cuda_visibility"].blocked_by == (
        "gpu.nvidia.driver",
        "gpu.pytorch.cuda_build",
    )


def test_no_camera_blocks_real_downstream_chain() -> None:
    results = execute(
        (
            CameraPresenceRule(),
            CameraPermissionRule(),
            CameraBusyRule(),
            OpenCVInstallationRule(),
            OpenCVOpenRule(),
            FrameCaptureRule(),
        ),
        {
            "camera.devices.discovery_available": True,
            "camera.devices.discovered": False,
            "camera.devices.count": 0,
            "camera.opencv.installed": False,
        },
    )
    assert results["camera.permissions"].blocked_by == ("camera.presence",)
    assert results["camera.busy"].blocked_by == ("camera.presence",)
    assert results["camera.opencv.open"].blocked_by == (
        "camera.permissions",
        "camera.busy",
        "camera.opencv.installation",
    )
    assert results["camera.opencv.frame_capture"].blocked_by == ("camera.opencv.open",)


def test_no_serial_device_blocks_checks_without_enabling_open_test() -> None:
    results = execute(
        (
            SerialPresenceRule(),
            SerialPermissionRule(),
            SerialBusyRule(),
            SerialOpenRule(),
        ),
        {
            "serial.discovery_available": True,
            "serial.devices.count": 0,
            "serial.open_test.requested": False,
        },
    )
    assert results["serial.permissions"].blocked_by == ("serial.presence",)
    assert results["serial.busy"].blocked_by == ("serial.presence",)
    assert results["serial.open"].blocked_by == (
        "serial.permissions",
        "serial.busy",
    )


def service_rules():
    return (
        ServiceTargetRule(),
        HostResolutionRule(),
        TcpConnectivityRule(),
        HttpReachabilityRule(),
        HttpHealthRule(),
        ListenerRule(),
    )


def test_service_resolution_failure_blocks_transport_but_not_listener() -> None:
    results = execute(
        service_rules(),
        {
            "service.target.url": "http://localhost:8000/health",
            "service.dns.attempted": True,
            "service.dns.success": False,
            "service.listener.inspection_available": True,
            "service.listener.found": False,
        },
    )
    assert results["service.host_resolution"].status is DiagnosticStatus.FAIL
    assert results["service.tcp_connectivity"].blocked_by == (
        "service.host_resolution",
    )
    assert results["service.http_reachability"].blocked_by == (
        "service.tcp_connectivity",
    )
    assert results["service.http_health"].blocked_by == ("service.http_reachability",)
    assert results["service.listener"].status is DiagnosticStatus.WARN


def test_service_404_and_500_keep_reachability_satisfied() -> None:
    base = {
        "service.target.url": "http://localhost:8000/health",
        "service.dns.attempted": True,
        "service.dns.success": True,
        "service.dns.addresses": ["127.0.0.1"],
        "service.tcp.success": True,
        "service.tcp.connected_address": "127.0.0.1",
        "service.http.response_received": True,
        "service.listener.inspection_available": True,
        "service.listener.found": True,
        "service.listener.addresses": [{"address": "127.0.0.1", "port": 8000}],
    }
    for status, expected in (
        (404, DiagnosticStatus.WARN),
        (500, DiagnosticStatus.FAIL),
    ):
        results = execute(service_rules(), {**base, "service.http.status_code": status})
        assert results["service.http_reachability"].status is DiagnosticStatus.PASS
        assert (
            results["service.http_reachability"].dependency_state
            is DependencyState.SATISFIED
        )
        assert results["service.http_health"].status is expected
