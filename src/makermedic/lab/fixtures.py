"""Deterministic evidence fixtures; no host state is read or changed."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from makermedic.core.models import Evidence


@dataclass(frozen=True)
class LabEvidenceProbe:
    id: str
    categories: tuple[str, ...]
    values: Mapping[str, object]

    def collect(self) -> Iterable[Evidence]:
        return tuple(
            Evidence(key=key, source=self.id, value=value)
            for key, value in sorted(self.values.items())
        )


def fixture(category: str, overrides: Mapping[str, object]) -> dict[str, object]:
    values = dict(_BASELINES[category])
    values.update(overrides)
    return values


SYSTEM = {
    "system.os": "Linux",
    "system.memory.available_bytes": 4 * 1024**3,
    "system.disk.root.free_bytes": 20 * 1024**3,
}
PYTHON = {
    "python.version_info": [3, 12, 0],
    "python.in_virtualenv": True,
    "python.venv.type": "venv",
    "python.executable": "/opt/makermedic-lab/bin/python",
    "python.pip.module.available": True,
    "python.pip.module.location": "/opt/makermedic-lab/site-packages/pip",
    "python.pip.path.command": "/opt/makermedic-lab/bin/pip",
    "python.pip.path.available": True,
    "python.pip.path.location": "/opt/makermedic-lab/site-packages/pip",
    "python.package.requested": "fake-package",
    "python.package.installed": True,
    "python.package.version": "1.0",
    "python.package.metadata_location": "/opt/makermedic-lab/fake.dist-info",
}
GPU = {
    "gpu.nvidia.hardware_detected": True,
    "gpu.nvidia.hardware_count": 1,
    "gpu.nvidia.driver.available": True,
    "gpu.nvidia.driver.version": "555.0",
    "gpu.nvidia.smi.error": None,
    "gpu.nvidia.nvml.available": True,
    "gpu.nvidia.nvml.error": None,
    "gpu.pytorch.installed": True,
    "gpu.pytorch.import_success": True,
    "gpu.pytorch.version": "2.8.0",
    "gpu.pytorch.import_error": None,
    "gpu.pytorch.cuda.build_version": "12.8",
    "gpu.pytorch.cuda.available": True,
    "gpu.pytorch.cuda.device_count": 1,
    "gpu.cuda_visible_devices.set": False,
    "gpu.cuda_visible_devices.value": None,
    "gpu.pytorch.cuda.allocation_test.attempted": True,
    "gpu.pytorch.cuda.allocation_test.success": True,
    "gpu.pytorch.cuda.allocation_test.error": None,
    "gpu.pytorch.cuda.compute_test.attempted": True,
    "gpu.pytorch.cuda.compute_test.success": True,
    "gpu.pytorch.cuda.compute_test.error": None,
}
CAMERA = {
    "camera.devices.discovery_available": True,
    "camera.devices.discovered": True,
    "camera.devices.count": 1,
    "camera.devices": [{"path": "/dev/video-lab", "readable": True}],
    "camera.v4l2.tool_available": True,
    "camera.v4l2.inspections": [{"success": True}],
    "camera.v4l2.capture_candidates": ["/dev/video-lab"],
    "camera.selected_candidate": "/dev/video-lab",
    "camera.selected.busy_known": True,
    "camera.selected.busy": False,
    "camera.selected.busy_process_ids": [],
    "camera.opencv.installed": True,
    "camera.opencv.import_success": True,
    "camera.opencv.version": "4.10",
    "camera.opencv.import_error": None,
    "camera.opencv.open_test.attempted": True,
    "camera.opencv.open_test.success": True,
    "camera.opencv.open_test.error": None,
    "camera.opencv.frame_test.attempted": True,
    "camera.opencv.frame_test.success": True,
    "camera.opencv.frame_test.width": 640,
    "camera.opencv.frame_test.height": 480,
    "camera.opencv.frame_test.error": None,
}
USB = {
    "usb.discovery_available": True,
    "usb.devices.count": 1,
    "usb.lsusb.tool_available": True,
    "usb.lsusb.success": True,
    "usb.lsusb.error": None,
}
SERIAL = {
    "serial.discovery_available": True,
    "serial.devices.count": 1,
    "serial.devices": [
        {
            "path": "/dev/ttyLAB0",
            "readable": True,
            "writable": True,
            "group_name": "dialout",
        }
    ],
    "serial.selected_candidate": "/dev/ttyLAB0",
    "serial.selected.busy_known": True,
    "serial.selected.busy": False,
    "serial.selected.busy_process_ids": [],
    "serial.open_test.requested": True,
    "serial.open_test.attempted": True,
    "serial.open_test.success": True,
    "serial.open_test.error": None,
}
SERVICE = {
    "service.target.url": "http://127.0.0.1:43123/health",
    "service.dns.attempted": True,
    "service.dns.success": True,
    "service.dns.addresses": ["127.0.0.1"],
    "service.dns.error": None,
    "service.tcp.attempted": True,
    "service.tcp.success": True,
    "service.tcp.connected_address": "127.0.0.1",
    "service.tcp.error_kind": None,
    "service.tcp.error": None,
    "service.http.attempted": True,
    "service.http.response_received": True,
    "service.http.status_code": 200,
    "service.http.error_kind": None,
    "service.http.error": None,
    "service.listener.inspection_available": True,
    "service.listener.found": True,
    "service.listener.addresses": [{"address": "127.0.0.1", "port": 43123}],
    "service.listener.pid": 4242,
    "service.listener.process_name": "lab-service",
}

_BASELINES = {
    "system": SYSTEM,
    "python": PYTHON,
    "gpu": GPU,
    "camera": CAMERA,
    "usb": USB,
    "serial": SERIAL,
    "service": SERVICE,
}
