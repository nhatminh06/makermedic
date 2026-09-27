"""Explicit built-in scenario registry and production-rule composition."""

from makermedic.core.errors import DuplicateRegistrationError
from makermedic.core.models import (
    DependencyState as DS,
)
from makermedic.core.models import (
    DiagnosticStatus as S,
)
from makermedic.core.models import (
    FindingKind as K,
)
from makermedic.core.models import (
    ResultOrigin as O,
)
from makermedic.core.registry import Registry
from makermedic.diagnostics.camera import (
    CameraBusyRule,
    CameraPermissionRule,
    CameraPresenceRule,
    FrameCaptureRule,
    OpenCVInstallationRule,
    OpenCVOpenRule,
    V4L2CapabilityRule,
)
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
from makermedic.diagnostics.python import (
    PackageInspectionRule,
    PipConsistencyRule,
    PythonVersionRule,
    VirtualEnvironmentRule,
)
from makermedic.diagnostics.service import (
    HostResolutionRule,
    HttpHealthRule,
    HttpReachabilityRule,
    ListenerRule,
    ServiceTargetRule,
    TcpConnectivityRule,
)
from makermedic.diagnostics.system import (
    DiskAvailabilityRule,
    MemoryAvailabilityRule,
    SystemPlatformRule,
)
from makermedic.diagnostics.usb_serial import (
    SerialBusyRule,
    SerialOpenRule,
    SerialPermissionRule,
    SerialPresenceRule,
    UsbDiscoveryRule,
    UsbToolingRule,
)
from makermedic.lab.models import (
    ExpectedDiagnostic,
    ExpectedFinding,
    FaultScenario,
    SafetyLevel,
)


class ScenarioRegistry:
    def __init__(self, scenarios: tuple[FaultScenario, ...] = ()) -> None:
        self._items: dict[str, FaultScenario] = {}
        for scenario in scenarios:
            self.register(scenario)

    def register(self, scenario: FaultScenario) -> None:
        if scenario.id in self._items:
            raise DuplicateRegistrationError(f"duplicate scenario ID: {scenario.id}")
        self._items[scenario.id] = scenario

    def all(self) -> tuple[FaultScenario, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def get(self, scenario_id: str) -> FaultScenario:
        try:
            return self._items[scenario_id]
        except KeyError as error:
            raise KeyError(f"unknown lab scenario: {scenario_id}") from error


def _d(
    diagnostic_id: str,
    status: S,
    state: DS | None = None,
    origin: O | None = None,
    blocked_by: tuple[str, ...] | None = None,
) -> ExpectedDiagnostic:
    return ExpectedDiagnostic(
        diagnostic_id=diagnostic_id,
        status=status,
        dependency_state=state,
        result_origin=origin,
        blocked_by=blocked_by,
    )


def _f(diagnostic_id: str, kind: K) -> ExpectedFinding:
    return ExpectedFinding(diagnostic_id=diagnostic_id, kind=kind)


def _s(
    scenario_id: str,
    category: str,
    description: str,
    diagnostics: tuple[ExpectedDiagnostic, ...],
    findings: tuple[ExpectedFinding, ...] = (),
    *,
    safety: SafetyLevel = SafetyLevel.SIMULATED,
) -> FaultScenario:
    return FaultScenario(
        id=scenario_id,
        title=scenario_id.replace("-", " ").title(),
        description=description,
        category=category,
        safety_level=safety,
        fixture_id=scenario_id,
        expected_diagnostics=diagnostics,
        expected_findings=findings,
        expected_exit_code=1
        if any(item.status is S.FAIL for item in diagnostics)
        else 0,
        tags=(category,),
    )


def build_scenario_registry() -> ScenarioRegistry:
    scenarios = (
        _s(
            "system-low-memory",
            "system",
            "Critically low simulated memory.",
            (_d("system.memory.available", S.FAIL),),
            (_f("system.memory.available", K.FAILURE),),
        ),
        _s(
            "system-memory-warning",
            "system",
            "Low simulated memory.",
            (_d("system.memory.available", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "system-low-disk",
            "system",
            "Critically low simulated root disk space.",
            (_d("system.disk.root.available", S.FAIL),),
            (_f("system.disk.root.available", K.FAILURE),),
        ),
        _s(
            "system-disk-warning",
            "system",
            "Low simulated root disk space.",
            (_d("system.disk.root.available", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "system-non-linux",
            "system",
            "A simulated non-Linux platform.",
            (_d("system.platform.support", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "python-old-version",
            "python",
            "Unsupported simulated Python version.",
            (_d("python.version.support", S.FAIL),),
            (_f("python.version.support", K.FAILURE),),
        ),
        _s(
            "python-no-virtualenv",
            "python",
            "Python runs outside an isolated environment.",
            (_d("python.virtual_environment", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "python-pip-path-missing",
            "python",
            "Python-bound pip works but PATH pip is absent.",
            (_d("python.pip.consistency", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "python-pip-mismatch",
            "python",
            "PATH pip belongs to another environment.",
            (_d("python.pip.consistency", S.WARN, DS.SATISFIED),),
        ),
        _s(
            "python-package-missing",
            "python",
            "Requested distribution metadata is absent.",
            (_d("python.package.inspection", S.WARN, DS.UNSATISFIED),),
            (_f("python.package.inspection", K.MISSING_CAPABILITY),),
        ),
        _s(
            "gpu-hardware-absent",
            "gpu",
            "No simulated NVIDIA hardware.",
            (
                _d("gpu.nvidia.hardware", S.WARN, DS.UNSATISFIED),
                _d(
                    "gpu.nvidia.driver",
                    S.BLOCKED,
                    DS.UNSATISFIED,
                    O.DEPENDENCY_BLOCKED,
                    ("gpu.nvidia.hardware",),
                ),
            ),
            (_f("gpu.nvidia.hardware", K.OPTIONAL_ABSENCE),),
        ),
        _s(
            "gpu-driver-unavailable",
            "gpu",
            "Hardware is visible but the driver cannot communicate.",
            (
                _d("gpu.nvidia.driver", S.FAIL),
                _d("gpu.nvidia.nvml", S.BLOCKED, blocked_by=("gpu.nvidia.driver",)),
                _d(
                    "gpu.pytorch.cuda_visibility",
                    S.BLOCKED,
                    blocked_by=("gpu.nvidia.driver",),
                ),
            ),
            (_f("gpu.nvidia.driver", K.FAILURE),),
        ),
        _s(
            "gpu-nvml-unavailable",
            "gpu",
            "Driver works but NVML cannot initialize.",
            (_d("gpu.nvidia.nvml", S.WARN, DS.UNSATISFIED),),
            (_f("gpu.nvidia.nvml", K.MISSING_CAPABILITY),),
        ),
        _s(
            "gpu-pytorch-missing",
            "gpu",
            "PyTorch is absent.",
            (
                _d("gpu.pytorch.installation", S.WARN, DS.UNSATISFIED),
                _d(
                    "gpu.pytorch.cuda_build",
                    S.BLOCKED,
                    blocked_by=("gpu.pytorch.installation",),
                ),
            ),
            (_f("gpu.pytorch.installation", K.MISSING_CAPABILITY),),
        ),
        _s(
            "gpu-pytorch-cpu-only",
            "gpu",
            "PyTorch has no CUDA build.",
            (_d("gpu.pytorch.cuda_build", S.WARN, DS.UNSATISFIED),),
            (_f("gpu.pytorch.cuda_build", K.MISSING_CAPABILITY),),
        ),
        _s(
            "gpu-cuda-hidden",
            "gpu",
            "CUDA visibility is restricted by simulated environment evidence.",
            (_d("gpu.pytorch.cuda_visibility", S.WARN, DS.UNSATISFIED),),
            (_f("gpu.pytorch.cuda_visibility", K.FAILURE),),
        ),
        _s(
            "gpu-allocation-failure",
            "gpu",
            "A simulated tiny CUDA allocation fails.",
            (
                _d("gpu.pytorch.cuda_allocation", S.FAIL),
                _d(
                    "gpu.pytorch.cuda_compute",
                    S.BLOCKED,
                    blocked_by=("gpu.pytorch.cuda_allocation",),
                ),
            ),
            (_f("gpu.pytorch.cuda_allocation", K.FAILURE),),
        ),
        _s(
            "gpu-compute-failure",
            "gpu",
            "A simulated tiny CUDA computation fails.",
            (_d("gpu.pytorch.cuda_compute", S.FAIL),),
            (_f("gpu.pytorch.cuda_compute", K.FAILURE),),
        ),
        _s(
            "camera-absent",
            "camera",
            "No simulated video device.",
            (
                _d("camera.presence", S.WARN, DS.UNSATISFIED),
                _d("camera.permissions", S.BLOCKED, blocked_by=("camera.presence",)),
            ),
            (_f("camera.presence", K.OPTIONAL_ABSENCE),),
        ),
        _s(
            "camera-permission-denied",
            "camera",
            "Camera exists but is unreadable.",
            (
                _d("camera.permissions", S.FAIL),
                _d("camera.opencv.open", S.BLOCKED, blocked_by=("camera.permissions",)),
            ),
            (_f("camera.permissions", K.FAILURE),),
        ),
        _s(
            "camera-busy",
            "camera",
            "Selected camera is busy.",
            (
                _d("camera.busy", S.WARN, DS.UNSATISFIED),
                _d("camera.opencv.open", S.BLOCKED, blocked_by=("camera.busy",)),
            ),
            (_f("camera.busy", K.FAILURE),),
        ),
        _s(
            "camera-opencv-missing",
            "camera",
            "OpenCV is absent.",
            (
                _d("camera.opencv.installation", S.WARN, DS.UNSATISFIED),
                _d(
                    "camera.opencv.open",
                    S.BLOCKED,
                    blocked_by=("camera.opencv.installation",),
                ),
            ),
            (_f("camera.opencv.installation", K.MISSING_CAPABILITY),),
        ),
        _s(
            "camera-open-failure",
            "camera",
            "OpenCV cannot open the selected simulated camera.",
            (
                _d("camera.opencv.open", S.FAIL),
                _d(
                    "camera.opencv.frame_capture",
                    S.BLOCKED,
                    blocked_by=("camera.opencv.open",),
                ),
            ),
            (_f("camera.opencv.open", K.FAILURE),),
        ),
        _s(
            "camera-frame-failure",
            "camera",
            "Opening succeeds but simulated frame capture fails.",
            (_d("camera.opencv.frame_capture", S.FAIL),),
            (_f("camera.opencv.frame_capture", K.FAILURE),),
        ),
        _s(
            "camera-healthy",
            "camera",
            "All simulated camera checks pass.",
            (_d("camera.opencv.frame_capture", S.PASS),),
        ),
        _s(
            "usb-none",
            "usb",
            "No simulated USB devices.",
            (_d("usb.discovery", S.WARN, DS.UNSATISFIED),),
            (_f("usb.discovery", K.OPTIONAL_ABSENCE),),
        ),
        _s(
            "usb-lsusb-unavailable",
            "usb",
            "Sysfs works while optional lsusb is absent.",
            (_d("usb.discovery", S.PASS), _d("usb.tooling", S.WARN, DS.SATISFIED)),
        ),
        _s(
            "serial-absent",
            "serial",
            "No supported simulated serial device.",
            (
                _d("serial.presence", S.WARN, DS.UNSATISFIED),
                _d("serial.permissions", S.BLOCKED, blocked_by=("serial.presence",)),
            ),
            (_f("serial.presence", K.OPTIONAL_ABSENCE),),
        ),
        _s(
            "serial-permission-denied",
            "serial",
            "Serial device exists but is inaccessible.",
            (
                _d("serial.permissions", S.FAIL),
                _d("serial.open", S.BLOCKED, blocked_by=("serial.permissions",)),
            ),
            (_f("serial.permissions", K.FAILURE),),
        ),
        _s(
            "serial-busy",
            "serial",
            "Selected simulated serial port is busy.",
            (
                _d("serial.busy", S.WARN, DS.UNSATISFIED),
                _d("serial.open", S.BLOCKED, blocked_by=("serial.busy",)),
            ),
            (_f("serial.busy", K.FAILURE),),
        ),
        _s(
            "serial-open-failure",
            "serial",
            "Opted-in simulated serial open fails without device access.",
            (_d("serial.open", S.FAIL),),
            (_f("serial.open", K.FAILURE),),
        ),
        _s(
            "serial-healthy-no-open",
            "serial",
            "Serial device is healthy and active open is not requested.",
            (
                _d("serial.permissions", S.PASS),
                _d("serial.busy", S.PASS),
                _d("serial.open", S.BLOCKED, DS.UNSATISFIED, O.EVALUATED),
            ),
        ),
        _s(
            "service-resolution-failure",
            "service",
            "Simulated loopback host resolution fails.",
            (
                _d("service.host_resolution", S.FAIL),
                _d(
                    "service.tcp_connectivity",
                    S.BLOCKED,
                    blocked_by=("service.host_resolution",),
                ),
            ),
            (_f("service.host_resolution", K.FAILURE),),
        ),
        _s(
            "service-connection-refused",
            "service",
            "Simulated loopback TCP connection is refused.",
            (
                _d("service.tcp_connectivity", S.FAIL),
                _d(
                    "service.http_reachability",
                    S.BLOCKED,
                    blocked_by=("service.tcp_connectivity",),
                ),
            ),
            (_f("service.tcp_connectivity", K.FAILURE),),
        ),
        _s(
            "service-timeout",
            "service",
            "Simulated loopback TCP connection times out.",
            (_d("service.tcp_connectivity", S.FAIL),),
            (_f("service.tcp_connectivity", K.FAILURE),),
        ),
        _s(
            "service-http-404",
            "service",
            "Simulated endpoint returns HTTP 404.",
            (
                _d("service.http_reachability", S.PASS),
                _d("service.http_health", S.WARN, DS.SATISFIED),
            ),
        ),
        _s(
            "service-http-500",
            "service",
            "Simulated endpoint returns HTTP 500.",
            (_d("service.http_health", S.FAIL),),
            (_f("service.http_health", K.FAILURE),),
        ),
        _s(
            "service-http-200",
            "service",
            "Simulated endpoint returns HTTP 200.",
            (_d("service.http_health", S.PASS),),
        ),
        _s(
            "service-live-http-500",
            "service",
            "A temporary loopback HTTP server returns 500.",
            (_d("service.http_health", S.FAIL),),
            (_f("service.http_health", K.FAILURE),),
            safety=SafetyLevel.TEMPORARY_LOCAL,
        ),
    )
    return ScenarioRegistry(scenarios)


def build_rule_registry(category: str) -> Registry:
    rules = {
        "system": (
            SystemPlatformRule(),
            MemoryAvailabilityRule(),
            DiskAvailabilityRule(),
        ),
        "python": (
            PythonVersionRule(),
            VirtualEnvironmentRule(),
            PipConsistencyRule(),
            PackageInspectionRule(),
        ),
        "gpu": (
            NvidiaHardwareRule(),
            NvidiaDriverRule(),
            NvmlRule(),
            PyTorchInstallationRule(),
            PyTorchCudaBuildRule(),
            PyTorchCudaVisibilityRule(),
            CudaAllocationRule(),
            CudaComputeRule(),
        ),
        "camera": (
            CameraPresenceRule(),
            CameraPermissionRule(),
            V4L2CapabilityRule(),
            CameraBusyRule(),
            OpenCVInstallationRule(),
            OpenCVOpenRule(),
            FrameCaptureRule(),
        ),
        "usb": (UsbDiscoveryRule(), UsbToolingRule()),
        "serial": (
            SerialPresenceRule(),
            SerialPermissionRule(),
            SerialBusyRule(),
            SerialOpenRule(),
        ),
        "service": (
            ServiceTargetRule(),
            HostResolutionRule(),
            TcpConnectivityRule(),
            HttpReachabilityRule(),
            HttpHealthRule(),
            ListenerRule(),
        ),
    }
    registry = Registry()
    for rule in rules[category]:
        registry.register_rule(rule)
    return registry
