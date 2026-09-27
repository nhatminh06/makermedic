"""Explicit composition root for production diagnostics."""

from makermedic.core.graph import DiagnosticGraph
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
from makermedic.probes.camera import CameraProbe
from makermedic.probes.gpu import (
    NvidiaHardwareProbe,
    NvidiaSmiProbe,
    NvmlProbe,
    PyTorchProbe,
)
from makermedic.probes.python import (
    PackageMetadataProbe,
    PipProbe,
    PythonEnvironmentProbe,
)
from makermedic.probes.service import ServiceProbe
from makermedic.probes.system import SystemProbe
from makermedic.probes.usb_serial import SerialProbe, UsbProbe
from makermedic.service import ServiceTarget


def build_default_registry(
    package: str | None = None,
    *,
    serial_open_test: bool = False,
    service_target: ServiceTarget | None = None,
) -> Registry:
    """Register every production probe and rule shipped by MakerMedic."""
    registry = Registry()
    registry.register_probe(SystemProbe())
    registry.register_probe(PythonEnvironmentProbe())
    registry.register_probe(PipProbe())
    registry.register_probe(NvidiaHardwareProbe())
    registry.register_probe(NvidiaSmiProbe())
    registry.register_probe(NvmlProbe())
    registry.register_probe(PyTorchProbe())
    registry.register_probe(CameraProbe())
    registry.register_probe(UsbProbe())
    registry.register_probe(SerialProbe(open_test=serial_open_test))
    if service_target is not None:
        registry.register_probe(ServiceProbe(service_target))
    registry.register_rule(SystemPlatformRule())
    registry.register_rule(MemoryAvailabilityRule())
    registry.register_rule(DiskAvailabilityRule())
    registry.register_rule(PythonVersionRule())
    registry.register_rule(VirtualEnvironmentRule())
    registry.register_rule(PipConsistencyRule())
    registry.register_rule(NvidiaHardwareRule())
    registry.register_rule(NvidiaDriverRule())
    registry.register_rule(NvmlRule())
    registry.register_rule(PyTorchInstallationRule())
    registry.register_rule(PyTorchCudaBuildRule())
    registry.register_rule(PyTorchCudaVisibilityRule())
    registry.register_rule(CudaAllocationRule())
    registry.register_rule(CudaComputeRule())
    registry.register_rule(CameraPresenceRule())
    registry.register_rule(CameraPermissionRule())
    registry.register_rule(V4L2CapabilityRule())
    registry.register_rule(CameraBusyRule())
    registry.register_rule(OpenCVInstallationRule())
    registry.register_rule(OpenCVOpenRule())
    registry.register_rule(FrameCaptureRule())
    registry.register_rule(UsbDiscoveryRule())
    registry.register_rule(UsbToolingRule())
    registry.register_rule(SerialPresenceRule())
    registry.register_rule(SerialPermissionRule())
    registry.register_rule(SerialBusyRule())
    registry.register_rule(SerialOpenRule())
    if service_target is not None:
        registry.register_rule(ServiceTargetRule())
        registry.register_rule(HostResolutionRule())
        registry.register_rule(TcpConnectivityRule())
        registry.register_rule(HttpReachabilityRule())
        registry.register_rule(HttpHealthRule())
        registry.register_rule(ListenerRule())
    if package is not None:
        registry.register_probe(PackageMetadataProbe(package))
        registry.register_rule(PackageInspectionRule())
    DiagnosticGraph(registry.rules())
    return registry
