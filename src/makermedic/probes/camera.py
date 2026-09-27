"""Linux camera, V4L2, busy-state, and optional OpenCV fact collection."""

import glob
import importlib
import importlib.util
import os
import re
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

from makermedic.core.commands import CommandRunner, CommandStatus
from makermedic.core.models import Evidence, EvidenceAvailability


class CameraProbe:
    """Collect a bounded camera pipeline snapshot without retaining frames."""

    id = "camera.environment"
    categories = ("camera",)

    def __init__(
        self,
        *,
        globber: Callable[[str], list[str]] = glob.glob,
        access: Callable[[str, int], bool] = os.access,
        stat: Callable[[str], os.stat_result] = os.stat,
        which: Callable[[str], str | None] = shutil.which,
        runner: CommandRunner | None = None,
        name_reader: Callable[[str], str | None] | None = None,
        find_spec: Callable[[str], object | None] = importlib.util.find_spec,
        importer: Callable[[str], ModuleType] = importlib.import_module,
    ) -> None:
        self._globber = globber
        self._access = access
        self._stat = stat
        self._which = which
        self._runner = runner or CommandRunner()
        self._name_reader = name_reader or _sysfs_name
        self._find_spec = find_spec
        self._importer = importer

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        try:
            paths = sorted(self._globber("/dev/video*"), key=_video_sort_key)
            devices = [self._device_record(path) for path in paths]
        except OSError:
            return _unavailable_camera_snapshot(source)

        v4l2_available = self._which("v4l2-ctl") is not None
        inspections = (
            [self._inspect_v4l2(path) for path in paths] if v4l2_available else []
        )
        candidates = _capture_candidates(devices, inspections, v4l2_available)
        selected = candidates[0] if candidates else None

        fuser_available = self._which("fuser") is not None
        busy_states = (
            [self._inspect_busy(path) for path in paths] if fuser_available else []
        )
        selected_busy = next(
            (state for state in busy_states if state["path"] == selected), None
        )

        evidence = [
            Evidence(
                key="camera.devices.discovery_available", source=source, value=True
            ),
            Evidence(key="camera.devices.discovered", source=source, value=bool(paths)),
            Evidence(key="camera.devices.count", source=source, value=len(paths)),
            Evidence(key="camera.devices", source=source, value=devices),
            Evidence(
                key="camera.v4l2.tool_available",
                source=source,
                value=v4l2_available,
            ),
            Evidence(key="camera.v4l2.inspections", source=source, value=inspections),
            Evidence(
                key="camera.v4l2.capture_candidates",
                source=source,
                value=candidates,
            ),
            Evidence(key="camera.selected_candidate", source=source, value=selected),
            Evidence(
                key="camera.busy.tool_available",
                source=source,
                value=fuser_available,
            ),
            Evidence(key="camera.busy.states", source=source, value=busy_states),
            _optional(
                "camera.selected.busy_known",
                source,
                selected_busy["busy_known"] if selected_busy else None,
            ),
            _optional(
                "camera.selected.busy",
                source,
                selected_busy["busy"] if selected_busy else None,
            ),
            _optional(
                "camera.selected.busy_process_ids",
                source,
                selected_busy["process_ids"] if selected_busy else None,
            ),
        ]
        evidence.extend(self._collect_opencv(selected, selected_busy))
        return tuple(evidence)

    def _device_record(self, path: str) -> dict[str, object]:
        readable = self._access(path, os.R_OK)
        writable = self._access(path, os.W_OK)
        record: dict[str, object] = {
            "path": path,
            "name": self._name_reader(path),
            "exists": True,
            "readable": readable,
            "writable": writable,
        }
        try:
            metadata = self._stat(path)
        except OSError as error:
            record.update(
                {
                    "stat_available": False,
                    "stat_error": _error_text(error),
                }
            )
        else:
            record.update(
                {
                    "stat_available": True,
                    "mode": oct(metadata.st_mode & 0o777),
                    "owner_uid": metadata.st_uid,
                    "owner_gid": metadata.st_gid,
                }
            )
        return record

    def _inspect_v4l2(self, path: str) -> dict[str, object]:
        result = self._runner.run(("v4l2-ctl", "--device", path, "--all"))
        base: dict[str, object] = {
            "path": path,
            "outcome": result.status.value,
            "return_code": result.return_code,
        }
        if result.status is not CommandStatus.COMPLETED or result.return_code != 0:
            return {
                **base,
                "success": False,
                "error": _concise(result.stderr or result.stdout),
                "capture": None,
                "streaming": None,
            }
        parsed = _parse_v4l2(result.stdout)
        return {**base, **parsed}

    def _inspect_busy(self, path: str) -> dict[str, object]:
        result = self._runner.run(("fuser", path))
        base: dict[str, object] = {"path": path, "process_ids": []}
        if result.status is not CommandStatus.COMPLETED:
            return {**base, "busy_known": False, "busy": None}
        if result.return_code == 1:
            return {**base, "busy_known": True, "busy": False}
        if result.return_code != 0:
            return {**base, "busy_known": False, "busy": None}
        process_ids = [
            int(value)
            for value in re.findall(r"(?<![\w/])\d+\b", result.stdout + result.stderr)
        ]
        return {
            **base,
            "busy_known": True,
            "busy": bool(process_ids),
            "process_ids": process_ids,
        }

    def _collect_opencv(
        self, selected: str | None, selected_busy: dict[str, object] | None
    ) -> tuple[Evidence, ...]:
        source = self.id
        try:
            installed = self._find_spec("cv2") is not None
        except (ImportError, ValueError):
            installed = False
        base = [Evidence(key="camera.opencv.installed", source=source, value=installed)]
        if not installed:
            return (*base, *_opencv_unavailable(source))
        try:
            cv2 = self._importer("cv2")
        except Exception as error:  # narrow optional import boundary
            return (
                *base,
                Evidence(
                    key="camera.opencv.import_success", source=source, value=False
                ),
                Evidence(
                    key="camera.opencv.import_error",
                    source=source,
                    value=_error_text(error),
                ),
                *_opencv_runtime_unavailable(source),
            )
        evidence = [
            *base,
            Evidence(key="camera.opencv.import_success", source=source, value=True),
            _unavailable("camera.opencv.import_error", source),
            Evidence(
                key="camera.opencv.version", source=source, value=str(cv2.__version__)
            ),
        ]
        busy = selected_busy and selected_busy.get("busy") is True
        if selected is None or busy:
            evidence.extend(_opencv_not_attempted(source, selected))
            return tuple(evidence)
        evidence.extend(self._opencv_smoke_test(cv2, selected))
        return tuple(evidence)

    def _opencv_smoke_test(self, cv2: Any, device: str) -> tuple[Evidence, ...]:
        source = self.id
        capture = None
        evidence: list[Evidence] = [
            Evidence(
                key="camera.opencv.open_test.attempted", source=source, value=True
            ),
            Evidence(key="camera.opencv.open_test.device", source=source, value=device),
        ]
        try:
            capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
            opened = bool(capture.isOpened())
            evidence.append(
                Evidence(
                    key="camera.opencv.open_test.success",
                    source=source,
                    value=opened,
                )
            )
            if not opened:
                evidence.extend(
                    (
                        _unavailable("camera.opencv.open_test.error", source),
                        *_frame_not_attempted(source),
                    )
                )
                return tuple(evidence)
            evidence.append(_unavailable("camera.opencv.open_test.error", source))
            evidence.append(
                Evidence(
                    key="camera.opencv.frame_test.attempted", source=source, value=True
                )
            )
            success, frame = capture.read()
            metadata = _frame_metadata(frame) if success and frame is not None else None
            frame_success = metadata is not None
            evidence.extend(_frame_result(source, frame_success, metadata))
        except Exception as error:  # narrow optional camera boundary
            if not any(
                item.key == "camera.opencv.open_test.success" for item in evidence
            ):
                evidence.extend(
                    (
                        Evidence(
                            key="camera.opencv.open_test.success",
                            source=source,
                            value=False,
                        ),
                        Evidence(
                            key="camera.opencv.open_test.error",
                            source=source,
                            value=_error_text(error),
                        ),
                        *_frame_not_attempted(source),
                    )
                )
            else:
                evidence.extend(_frame_result(source, False, None, _error_text(error)))
        finally:
            if capture is not None:
                capture.release()
        return tuple(evidence)


def _parse_v4l2(output: str) -> dict[str, object]:
    driver = _field(output, "Driver name")
    card = _field(output, "Card type")
    capture = bool(
        re.search(r"^\s*Video Capture(?: Multiplanar)?\s*$", output, re.MULTILINE)
    )
    streaming = bool(re.search(r"^\s*Streaming\s*$", output, re.MULTILINE))
    recognizable = any((driver, card, capture, streaming))
    return {
        "success": True,
        "malformed": not recognizable,
        "driver": driver,
        "card": card,
        "capture": capture,
        "streaming": streaming,
    }


def _capture_candidates(
    devices: list[dict[str, object]],
    inspections: list[dict[str, object]],
    tool_available: bool,
) -> list[str]:
    readable = {str(device["path"]) for device in devices if device["readable"]}
    if not tool_available:
        return sorted(readable, key=_video_sort_key)
    return [
        str(item["path"])
        for item in inspections
        if item.get("success") is True
        and item.get("capture") is True
        and item["path"] in readable
    ]


def _frame_metadata(frame: object) -> dict[str, int] | None:
    shape = getattr(frame, "shape", None)
    if not isinstance(shape, tuple) or len(shape) not in {2, 3}:
        return None
    if not all(isinstance(value, int) and value > 0 for value in shape):
        return None
    height, width = shape[:2]
    channels = shape[2] if len(shape) == 3 else 1
    return {"width": width, "height": height, "channels": channels}


def _frame_result(
    source: str,
    success: bool,
    metadata: dict[str, int] | None,
    error: str | None = None,
) -> tuple[Evidence, ...]:
    return (
        Evidence(key="camera.opencv.frame_test.success", source=source, value=success),
        _optional("camera.opencv.frame_test.error", source, error),
        _optional(
            "camera.opencv.frame_test.width",
            source,
            metadata["width"] if metadata else None,
        ),
        _optional(
            "camera.opencv.frame_test.height",
            source,
            metadata["height"] if metadata else None,
        ),
        _optional(
            "camera.opencv.frame_test.channels",
            source,
            metadata["channels"] if metadata else None,
        ),
    )


def _opencv_unavailable(source: str) -> tuple[Evidence, ...]:
    return (
        _unavailable("camera.opencv.import_success", source),
        _unavailable("camera.opencv.import_error", source),
        *_opencv_runtime_unavailable(source),
    )


def _opencv_runtime_unavailable(source: str) -> tuple[Evidence, ...]:
    return (
        _unavailable("camera.opencv.version", source),
        *_opencv_not_attempted(source, None),
    )


def _opencv_not_attempted(source: str, device: str | None) -> tuple[Evidence, ...]:
    return (
        Evidence(key="camera.opencv.open_test.attempted", source=source, value=False),
        _unavailable("camera.opencv.open_test.success", source),
        Evidence(key="camera.opencv.open_test.device", source=source, value=device),
        _unavailable("camera.opencv.open_test.error", source),
        *_frame_not_attempted(source),
    )


def _frame_not_attempted(source: str) -> tuple[Evidence, ...]:
    return (
        Evidence(key="camera.opencv.frame_test.attempted", source=source, value=False),
        _unavailable("camera.opencv.frame_test.success", source),
        _unavailable("camera.opencv.frame_test.error", source),
        _unavailable("camera.opencv.frame_test.width", source),
        _unavailable("camera.opencv.frame_test.height", source),
        _unavailable("camera.opencv.frame_test.channels", source),
    )


def _unavailable_camera_snapshot(source: str) -> tuple[Evidence, ...]:
    keys = (
        "camera.devices.discovery_available",
        "camera.devices.discovered",
        "camera.devices.count",
        "camera.devices",
        "camera.v4l2.tool_available",
        "camera.v4l2.inspections",
        "camera.v4l2.capture_candidates",
        "camera.selected_candidate",
        "camera.busy.tool_available",
        "camera.busy.states",
        "camera.selected.busy_known",
        "camera.selected.busy",
        "camera.selected.busy_process_ids",
    )
    return tuple(_unavailable(key, source) for key in keys)


def _sysfs_name(device: str) -> str | None:
    try:
        return (
            Path("/sys/class/video4linux", Path(device).name, "name")
            .read_text()
            .strip()
        )
    except OSError:
        return None


def _field(output: str, label: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.+)$", output, re.MULTILINE)
    return match.group(1).strip() if match else None


def _video_sort_key(path: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", path)
    return (int(match.group(1)) if match else 2**31, path)


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
