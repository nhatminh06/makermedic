from makermedic.composition import build_default_registry
from makermedic.service import ServiceTarget


def test_system_production_components_are_registered() -> None:
    registry = build_default_registry()

    assert [probe.id for probe in registry.probes("system")] == ["system.basic"]
    assert [rule.id for rule in registry.rules("system")] == [
        "system.platform.support",
        "system.memory.available",
        "system.disk.root.available",
    ]


def test_python_production_components_are_registered() -> None:
    registry = build_default_registry()

    assert [probe.id for probe in registry.probes("python")] == [
        "python.environment",
        "python.pip",
    ]
    assert [rule.id for rule in registry.rules("python")] == [
        "python.version.support",
        "python.virtual_environment",
        "python.pip.consistency",
    ]


def test_package_components_are_registered_only_when_requested() -> None:
    registry = build_default_registry("pydantic")

    assert "python.package" in [probe.id for probe in registry.probes("python")]
    assert "python.package.inspection" in [rule.id for rule in registry.rules("python")]


def test_gpu_production_components_are_registered() -> None:
    registry = build_default_registry()

    assert [probe.id for probe in registry.probes("gpu")] == [
        "gpu.nvidia.hardware",
        "gpu.nvidia.smi",
        "gpu.nvidia.nvml",
        "gpu.pytorch",
    ]
    assert [rule.id for rule in registry.rules("gpu")] == [
        "gpu.nvidia.hardware",
        "gpu.nvidia.driver",
        "gpu.nvidia.nvml",
        "gpu.pytorch.installation",
        "gpu.pytorch.cuda_build",
        "gpu.pytorch.cuda_visibility",
        "gpu.pytorch.cuda_allocation",
        "gpu.pytorch.cuda_compute",
    ]


def test_gpu_filter_does_not_select_system_or_python_components() -> None:
    registry = build_default_registry()

    assert all("gpu" in probe.categories for probe in registry.probes("gpu"))
    assert all(rule.category == "gpu" for rule in registry.rules("gpu"))


def test_camera_production_components_are_registered_and_filtered() -> None:
    registry = build_default_registry()
    assert [probe.id for probe in registry.probes("camera")] == ["camera.environment"]
    assert [rule.id for rule in registry.rules("camera")] == [
        "camera.presence",
        "camera.permissions",
        "camera.v4l2.capability",
        "camera.busy",
        "camera.opencv.installation",
        "camera.opencv.open",
        "camera.opencv.frame_capture",
    ]
    assert all("camera" in probe.categories for probe in registry.probes("camera"))


def test_usb_and_serial_production_components_are_registered_and_filtered() -> None:
    registry = build_default_registry()
    assert [probe.id for probe in registry.probes("usb")] == ["usb.discovery"]
    assert [rule.id for rule in registry.rules("usb")] == [
        "usb.discovery",
        "usb.tooling",
    ]
    assert [probe.id for probe in registry.probes("serial")] == ["serial.discovery"]
    assert [rule.id for rule in registry.rules("serial")] == [
        "serial.presence",
        "serial.permissions",
        "serial.busy",
        "serial.open",
    ]


def test_serial_open_opt_in_reaches_production_probe() -> None:
    registry = build_default_registry(serial_open_test=True)
    probe = registry.probes("serial")[0]
    assert probe._open_test is True  # noqa: SLF001


def test_service_components_are_registered_only_with_explicit_target() -> None:
    default = build_default_registry()
    assert "service" not in default.categories

    target = ServiceTarget.parse("http://localhost:8000/health")
    registry = build_default_registry(service_target=target)
    assert [probe.id for probe in registry.probes("service")] == ["service.local"]
    assert [rule.id for rule in registry.rules("service")] == [
        "service.target",
        "service.host_resolution",
        "service.tcp_connectivity",
        "service.http_reachability",
        "service.http_health",
        "service.listener",
    ]
    assert registry.probes("system")
