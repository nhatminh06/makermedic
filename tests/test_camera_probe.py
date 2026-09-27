import os
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from makermedic.core.commands import CommandResult, CommandStatus
from makermedic.core.models import EvidenceAvailability
from makermedic.probes.camera import CameraProbe


class FakeRunner:
    def __init__(self, v4l2=None, fuser=None) -> None:
        self.v4l2 = v4l2 or {}
        self.fuser = fuser or {}
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        command = tuple(args)
        self.calls.append(command)
        path = command[-1] if command[0] == "fuser" else command[2]
        return (self.fuser if command[0] == "fuser" else self.v4l2)[path]


def result(
    output: str = "",
    *,
    code: int | None = 0,
    status: CommandStatus = CommandStatus.COMPLETED,
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        args=("tool",), status=status, return_code=code, stdout=output, stderr=stderr
    )


V4L2_CAPTURE = """Driver Info:
    Driver name : uvcvideo
    Card type : Integrated Camera
    Capabilities :
        Video Capture
        Streaming
"""
V4L2_OUTPUT_ONLY = """Driver Info:
    Driver name : virtual
    Card type : Output Node
    Capabilities :
        Video Output
        Streaming
"""


def make_probe(
    paths: list[str],
    *,
    runner: FakeRunner | None = None,
    tools: tuple[str, ...] = (),
    readable: tuple[str, ...] | None = None,
    find_spec=lambda _name: None,
    importer=lambda _name: None,
) -> CameraProbe:
    readable_set = set(paths if readable is None else readable)
    return CameraProbe(
        globber=lambda _pattern: paths,
        access=lambda path, mode: path in readable_set if mode == os.R_OK else True,
        stat=lambda _path: SimpleNamespace(st_mode=0o20660, st_uid=1000, st_gid=985),
        which=lambda name: f"/usr/bin/{name}" if name in tools else None,
        runner=runner,  # type: ignore[arg-type]
        name_reader=lambda path: f"Camera {path[-1]}",
        find_spec=find_spec,
        importer=importer,
    )


def collect(probe: CameraProbe) -> dict[str, Any]:
    return {item.key: item for item in probe.collect()}


def test_no_video_devices_is_valid_evidence() -> None:
    evidence = collect(make_probe([]))
    assert evidence["camera.devices.discovered"].value is False
    assert evidence["camera.devices.count"].value == 0
    assert evidence["camera.devices"].value == []


def test_device_records_permissions_identity_and_mode() -> None:
    device = collect(make_probe(["/dev/video0"]))["camera.devices"].value[0]
    assert device == {
        "path": "/dev/video0",
        "name": "Camera 0",
        "exists": True,
        "readable": True,
        "writable": True,
        "stat_available": True,
        "mode": "0o660",
        "owner_uid": 1000,
        "owner_gid": 985,
    }


def test_multiple_devices_are_sorted_deterministically() -> None:
    evidence = collect(make_probe(["/dev/video10", "/dev/video2", "/dev/video0"]))
    assert [item["path"] for item in evidence["camera.devices"].value] == [
        "/dev/video0",
        "/dev/video2",
        "/dev/video10",
    ]


def test_inaccessible_device_does_not_crash_or_select() -> None:
    evidence = collect(make_probe(["/dev/video0"], readable=()))
    assert evidence["camera.devices"].value[0]["readable"] is False
    assert evidence["camera.selected_candidate"].value is None


def test_stat_error_is_preserved() -> None:
    probe = make_probe(["/dev/video0"])
    probe._stat = lambda _path: (_ for _ in ()).throw(PermissionError("denied"))  # noqa: SLF001
    device = collect(probe)["camera.devices"].value[0]
    assert device["stat_available"] is False
    assert "denied" in device["stat_error"]


def test_discovery_error_is_unavailable() -> None:
    def broken_glob(_pattern: str) -> list[str]:
        raise OSError("unavailable")

    evidence = list(CameraProbe(globber=broken_glob).collect())
    assert all(
        item.availability is EvidenceAvailability.UNAVAILABLE for item in evidence
    )


def test_v4l2_capture_streaming_and_identity_select_candidate() -> None:
    runner = FakeRunner(v4l2={"/dev/video0": result(V4L2_CAPTURE)})
    evidence = collect(make_probe(["/dev/video0"], runner=runner, tools=("v4l2-ctl",)))
    inspection = evidence["camera.v4l2.inspections"].value[0]
    assert inspection["capture"] is True
    assert inspection["streaming"] is True
    assert inspection["card"] == "Integrated Camera"
    assert evidence["camera.v4l2.capture_candidates"].value == ["/dev/video0"]


def test_non_capture_video_node_is_not_selected() -> None:
    runner = FakeRunner(v4l2={"/dev/video0": result(V4L2_OUTPUT_ONLY)})
    evidence = collect(make_probe(["/dev/video0"], runner=runner, tools=("v4l2-ctl",)))
    assert evidence["camera.v4l2.inspections"].value[0]["capture"] is False
    assert evidence["camera.selected_candidate"].value is None


def test_v4l2_absence_uses_readable_deterministic_fallback() -> None:
    evidence = collect(make_probe(["/dev/video2", "/dev/video0"]))
    assert evidence["camera.v4l2.tool_available"].value is False
    assert evidence["camera.selected_candidate"].value == "/dev/video0"


@pytest.mark.parametrize(
    ("command_result", "success", "malformed"),
    [
        (result("unrecognized"), True, True),
        (result(code=4, stderr="cannot open"), False, None),
        (result(status=CommandStatus.TIMED_OUT, code=None), False, None),
    ],
)
def test_v4l2_malformed_failure_and_timeout(
    command_result: CommandResult, success: bool, malformed: bool | None
) -> None:
    runner = FakeRunner(v4l2={"/dev/video0": command_result})
    inspection = collect(
        make_probe(["/dev/video0"], runner=runner, tools=("v4l2-ctl",))
    )["camera.v4l2.inspections"].value[0]
    assert inspection["success"] is success
    if malformed is not None:
        assert inspection["malformed"] is malformed


@pytest.mark.parametrize(
    ("fuser_result", "known", "busy", "pids"),
    [
        (result(code=1), True, False, []),
        (result(stderr="/dev/video0: 1234 5678"), True, True, [1234, 5678]),
        (result(status=CommandStatus.TIMED_OUT, code=None), False, None, []),
    ],
)
def test_busy_state_free_busy_and_unavailable(
    fuser_result: CommandResult, known: bool, busy: bool | None, pids: list[int]
) -> None:
    runner = FakeRunner(fuser={"/dev/video0": fuser_result})
    evidence = collect(make_probe(["/dev/video0"], runner=runner, tools=("fuser",)))
    assert evidence["camera.selected.busy_known"].value is known
    assert evidence["camera.selected.busy"].value is busy
    assert evidence["camera.selected.busy_process_ids"].value == pids
    assert all(call[0] != "kill" for call in runner.calls)


class FakeFrame:
    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


class FakeCapture:
    def __init__(self, opened=True, read_success=True, frame=None) -> None:
        self.opened = opened
        self.read_success = read_success
        self.frame = frame
        self.releases = 0

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        return self.read_success, self.frame

    def release(self) -> None:
        self.releases += 1


class FakeCV2:
    __version__ = "4.10.0"
    CAP_V4L2 = 200

    def __init__(self, capture: FakeCapture) -> None:
        self.capture = capture
        self.opened_path = None

    def VideoCapture(self, path: str, backend: int) -> FakeCapture:
        assert backend == self.CAP_V4L2
        self.opened_path = path
        return self.capture


def opencv_probe(capture: FakeCapture):
    cv2 = FakeCV2(capture)
    probe = make_probe(
        ["/dev/video0"],
        find_spec=lambda _name: object(),
        importer=lambda _name: cv2,
    )
    return collect(probe), cv2


def test_opencv_absent_and_import_failure() -> None:
    assert collect(make_probe([]))["camera.opencv.installed"].value is False

    def broken_import(_name: str):
        raise ImportError("broken cv2")

    evidence = collect(
        make_probe(
            ["/dev/video0"],
            find_spec=lambda _name: object(),
            importer=broken_import,
        )
    )
    assert evidence["camera.opencv.import_success"].value is False
    assert "broken cv2" in evidence["camera.opencv.import_error"].value


def test_open_and_one_frame_success_records_metadata_and_releases() -> None:
    capture = FakeCapture(frame=FakeFrame((720, 1280, 3)))
    evidence, cv2 = opencv_probe(capture)
    assert evidence["camera.opencv.version"].value == "4.10.0"
    assert evidence["camera.opencv.open_test.success"].value is True
    assert evidence["camera.opencv.open_test.device"].value == "/dev/video0"
    assert evidence["camera.opencv.frame_test.success"].value is True
    assert evidence["camera.opencv.frame_test.width"].value == 1280
    assert evidence["camera.opencv.frame_test.height"].value == 720
    assert evidence["camera.opencv.frame_test.channels"].value == 3
    assert cv2.opened_path == "/dev/video0"
    assert capture.releases == 1
    assert not any(key.endswith("pixels") for key in evidence)


@pytest.mark.parametrize(
    ("capture", "open_success", "frame_success"),
    [
        (FakeCapture(opened=False), False, None),
        (FakeCapture(read_success=False), True, False),
        (FakeCapture(read_success=True, frame=None), True, False),
        (FakeCapture(frame=FakeFrame((0, 640, 3))), True, False),
    ],
)
def test_open_and_frame_failures_release(
    capture: FakeCapture, open_success: bool, frame_success: bool | None
) -> None:
    evidence, _cv2 = opencv_probe(capture)
    assert evidence["camera.opencv.open_test.success"].value is open_success
    if frame_success is not None:
        assert evidence["camera.opencv.frame_test.success"].value is frame_success
    assert capture.releases == 1


def test_busy_camera_blocks_open_without_creating_capture() -> None:
    capture = FakeCapture(frame=FakeFrame((10, 10, 3)))
    cv2 = FakeCV2(capture)
    runner = FakeRunner(fuser={"/dev/video0": result(stderr="/dev/video0: 42")})
    evidence = collect(
        make_probe(
            ["/dev/video0"],
            runner=runner,
            tools=("fuser",),
            find_spec=lambda _name: object(),
            importer=lambda _name: cv2,
        )
    )
    assert evidence["camera.opencv.open_test.attempted"].value is False
    assert cv2.opened_path is None
