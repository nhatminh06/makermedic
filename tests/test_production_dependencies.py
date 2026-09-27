from makermedic.composition import build_default_registry
from makermedic.core.evidence import EvidenceStore
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DependencyState,
    DiagnosticStatus,
    Evidence,
    FindingKind,
)
from makermedic.diagnostics.camera import (
    CameraBusyRule,
    CameraPresenceRule,
    OpenCVInstallationRule,
)
from makermedic.diagnostics.gpu import NvidiaHardwareRule, PyTorchInstallationRule
from makermedic.diagnostics.service import HttpHealthRule
from makermedic.diagnostics.usb_serial import SerialBusyRule, SerialPresenceRule
from makermedic.service import ServiceTarget


def evidence(**values) -> EvidenceStore:
    return EvidenceStore(
        Evidence(key=key.replace("__", "."), source="test", value=value)
        for key, value in values.items()
    )


def test_production_gpu_dependencies() -> None:
    graph = DiagnosticGraph(build_default_registry().rules())
    assert graph.dependencies_of("gpu.nvidia.driver") == ("gpu.nvidia.hardware",)
    assert graph.dependencies_of("gpu.nvidia.nvml") == ("gpu.nvidia.driver",)
    assert graph.dependencies_of("gpu.pytorch.cuda_build") == (
        "gpu.pytorch.installation",
    )
    assert graph.dependencies_of("gpu.pytorch.cuda_visibility") == (
        "gpu.nvidia.driver",
        "gpu.pytorch.cuda_build",
    )
    assert graph.dependencies_of("gpu.pytorch.cuda_allocation") == (
        "gpu.pytorch.cuda_visibility",
    )
    assert graph.dependencies_of("gpu.pytorch.cuda_compute") == (
        "gpu.pytorch.cuda_allocation",
    )


def test_production_camera_dependencies() -> None:
    graph = DiagnosticGraph(build_default_registry().rules())
    assert graph.dependencies_of("camera.permissions") == ("camera.presence",)
    assert graph.dependencies_of("camera.v4l2.capability") == ("camera.presence",)
    assert graph.dependencies_of("camera.busy") == ("camera.presence",)
    assert graph.dependencies_of("camera.opencv.open") == (
        "camera.permissions",
        "camera.busy",
        "camera.opencv.installation",
    )
    assert graph.dependencies_of("camera.opencv.frame_capture") == (
        "camera.opencv.open",
    )


def test_production_usb_and_serial_dependencies() -> None:
    graph = DiagnosticGraph(build_default_registry().rules())
    assert graph.dependencies_of("usb.discovery") == ()
    assert graph.dependencies_of("usb.tooling") == ()
    assert graph.dependencies_of("serial.permissions") == ("serial.presence",)
    assert graph.dependencies_of("serial.busy") == ("serial.presence",)
    assert graph.dependencies_of("serial.open") == (
        "serial.permissions",
        "serial.busy",
    )


def test_production_service_dependencies_exist_only_when_configured() -> None:
    default = DiagnosticGraph(build_default_registry().rules())
    assert "service.target" not in default.topological_order()
    configured = DiagnosticGraph(
        build_default_registry(
            service_target=ServiceTarget.parse("http://localhost:8000/health")
        ).rules()
    )
    assert configured.dependencies_of("service.host_resolution") == ("service.target",)
    assert configured.dependencies_of("service.tcp_connectivity") == (
        "service.host_resolution",
    )
    assert configured.dependencies_of("service.http_reachability") == (
        "service.tcp_connectivity",
    )
    assert configured.dependencies_of("service.http_health") == (
        "service.http_reachability",
    )
    assert configured.dependencies_of("service.listener") == ("service.target",)


def test_system_and_python_rules_are_independent() -> None:
    graph = DiagnosticGraph(build_default_registry("pydantic").rules())
    for diagnostic_id in graph.topological_order():
        if diagnostic_id.startswith(("system.", "python.")):
            assert graph.dependencies_of(diagnostic_id) == ()


def test_absent_capability_warnings_are_unsatisfied() -> None:
    cases = (
        NvidiaHardwareRule().evaluate(
            evidence(
                gpu__nvidia__hardware_detected=False,
                gpu__nvidia__hardware_count=0,
            )
        ),
        PyTorchInstallationRule().evaluate(evidence(gpu__pytorch__installed=False)),
        CameraPresenceRule().evaluate(
            evidence(
                camera__devices__discovery_available=True,
                camera__devices__discovered=False,
            )
        ),
        SerialPresenceRule().evaluate(
            evidence(serial__discovery_available=True, serial__devices__count=0)
        ),
    )
    assert all(result.status is DiagnosticStatus.WARN for result in cases)
    assert all(
        result.dependency_state is DependencyState.UNSATISFIED for result in cases
    )
    assert [result.finding_kind for result in cases] == [
        FindingKind.OPTIONAL_ABSENCE,
        FindingKind.MISSING_CAPABILITY,
        FindingKind.OPTIONAL_ABSENCE,
        FindingKind.OPTIONAL_ABSENCE,
    ]


def test_busy_warnings_are_unsatisfied() -> None:
    camera = CameraBusyRule().evaluate(
        evidence(
            camera__selected_candidate="/dev/video0",
            camera__selected__busy_known=True,
            camera__selected__busy=True,
            camera__selected__busy_process_ids=[10],
        )
    )
    serial = SerialBusyRule().evaluate(
        evidence(
            serial__selected_candidate="/dev/ttyUSB0",
            serial__selected__busy_known=True,
            serial__selected__busy=True,
            serial__selected__busy_process_ids=[10],
        )
    )
    assert camera.dependency_state is DependencyState.UNSATISFIED
    assert serial.dependency_state is DependencyState.UNSATISFIED
    assert camera.finding_kind is FindingKind.FAILURE
    assert serial.finding_kind is FindingKind.FAILURE


def test_opencv_absent_and_http_404_have_deliberate_warn_semantics() -> None:
    opencv = OpenCVInstallationRule().evaluate(
        evidence(camera__opencv__installed=False)
    )
    health = HttpHealthRule().evaluate(
        evidence(
            service__http__response_received=True,
            service__http__status_code=404,
        )
    )
    assert opencv.dependency_state is DependencyState.UNSATISFIED
    assert health.dependency_state is DependencyState.SATISFIED
