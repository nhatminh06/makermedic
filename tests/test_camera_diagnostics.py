from typing import Any

import pytest

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence
from makermedic.diagnostics.camera import (
    CameraBusyRule,
    CameraPermissionRule,
    CameraPresenceRule,
    FrameCaptureRule,
    OpenCVInstallationRule,
    OpenCVOpenRule,
    V4L2CapabilityRule,
)


def store(values: dict[str, Any]) -> EvidenceStore:
    return EvidenceStore(
        Evidence(key=key, source="test", value=value) for key, value in values.items()
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {
                "camera.devices.discovery_available": True,
                "camera.devices.discovered": True,
                "camera.devices.count": 1,
            },
            DiagnosticStatus.PASS,
        ),
        (
            {
                "camera.devices.discovery_available": True,
                "camera.devices.discovered": False,
            },
            DiagnosticStatus.WARN,
        ),
        ({}, DiagnosticStatus.UNKNOWN),
    ],
)
def test_camera_presence(values: dict[str, Any], expected: DiagnosticStatus) -> None:
    assert CameraPresenceRule().evaluate(store(values)).status is expected


def test_camera_permissions_pass_fail_and_blocked() -> None:
    rule = CameraPermissionRule()
    readable = {
        "camera.devices.discovered": True,
        "camera.devices": [{"readable": True}],
    }
    denied = {
        "camera.devices.discovered": True,
        "camera.devices": [{"readable": False}],
    }
    absent = {"camera.devices.discovered": False}
    assert rule.evaluate(store(readable)).status is DiagnosticStatus.PASS
    assert rule.evaluate(store(denied)).status is DiagnosticStatus.FAIL
    assert rule.evaluate(store(absent)).status is DiagnosticStatus.UNKNOWN


def test_v4l2_capability_pass_warn_unknown_and_blocked() -> None:
    rule = V4L2CapabilityRule()
    base = {"camera.devices.discovered": True}
    assert (
        rule.evaluate(store({**base, "camera.v4l2.tool_available": False})).status
        is DiagnosticStatus.WARN
    )
    assert (
        rule.evaluate(
            store(
                {
                    **base,
                    "camera.v4l2.tool_available": True,
                    "camera.v4l2.inspections": [{"success": True}],
                    "camera.v4l2.capture_candidates": ["/dev/video0"],
                }
            )
        ).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(
            store(
                {
                    **base,
                    "camera.v4l2.tool_available": True,
                    "camera.v4l2.inspections": [{"success": True}],
                    "camera.v4l2.capture_candidates": [],
                }
            )
        ).status
        is DiagnosticStatus.WARN
    )
    assert (
        rule.evaluate(
            store(
                {
                    **base,
                    "camera.v4l2.tool_available": True,
                    "camera.v4l2.inspections": [{"success": False}],
                    "camera.v4l2.capture_candidates": [],
                }
            )
        ).status
        is DiagnosticStatus.UNKNOWN
    )
    assert (
        rule.evaluate(store({"camera.devices.discovered": False})).status
        is DiagnosticStatus.UNKNOWN
    )


@pytest.mark.parametrize(
    ("known", "busy", "expected"),
    [
        (True, False, DiagnosticStatus.PASS),
        (True, True, DiagnosticStatus.WARN),
        (False, None, DiagnosticStatus.UNKNOWN),
    ],
)
def test_camera_busy_rule(
    known: bool, busy: bool | None, expected: DiagnosticStatus
) -> None:
    result = CameraBusyRule().evaluate(
        store(
            {
                "camera.selected_candidate": "/dev/video0",
                "camera.selected.busy_known": known,
                "camera.selected.busy": busy,
                "camera.selected.busy_process_ids": [42] if busy else [],
            }
        )
    )
    assert result.status is expected
    if busy:
        assert "42" in result.causes[0]


def test_busy_rule_without_candidate_is_unknown_without_graph_context() -> None:
    assert CameraBusyRule().evaluate(EvidenceStore()).status is DiagnosticStatus.UNKNOWN


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"camera.opencv.installed": False}, DiagnosticStatus.WARN),
        (
            {
                "camera.opencv.installed": True,
                "camera.opencv.import_success": False,
                "camera.opencv.import_error": "broken import",
            },
            DiagnosticStatus.FAIL,
        ),
        (
            {
                "camera.opencv.installed": True,
                "camera.opencv.import_success": True,
                "camera.opencv.version": "4.10",
            },
            DiagnosticStatus.PASS,
        ),
    ],
)
def test_opencv_installation(
    values: dict[str, Any], expected: DiagnosticStatus
) -> None:
    assert OpenCVInstallationRule().evaluate(store(values)).status is expected


def open_values(*, attempted: bool, success: bool | None, busy: bool = False):
    return {
        "camera.selected_candidate": "/dev/video0",
        "camera.selected.busy": busy,
        "camera.opencv.import_success": True,
        "camera.opencv.open_test.attempted": attempted,
        "camera.opencv.open_test.success": success,
    }


def test_opencv_open_pass_fail_and_busy_blocked() -> None:
    rule = OpenCVOpenRule()
    assert (
        rule.evaluate(store(open_values(attempted=True, success=True))).status
        is DiagnosticStatus.PASS
    )
    assert (
        rule.evaluate(store(open_values(attempted=True, success=False))).status
        is DiagnosticStatus.FAIL
    )
    assert (
        rule.evaluate(
            store(open_values(attempted=False, success=None, busy=True))
        ).status
        is DiagnosticStatus.UNKNOWN
    )


def test_permission_failure_blocks_open_and_frame_chain() -> None:
    evidence = store(
        {
            "camera.devices.discovered": True,
            "camera.devices": [{"readable": False}],
            "camera.opencv.import_success": True,
            "camera.opencv.open_test.attempted": False,
            "camera.opencv.frame_test.attempted": False,
        }
    )
    assert CameraPermissionRule().evaluate(evidence).status is DiagnosticStatus.FAIL
    assert OpenCVOpenRule().evaluate(evidence).status is DiagnosticStatus.UNKNOWN
    assert FrameCaptureRule().evaluate(evidence).status is DiagnosticStatus.UNKNOWN


def test_frame_capture_pass_fail_and_open_blocked() -> None:
    rule = FrameCaptureRule()
    passed = {
        "camera.opencv.open_test.success": True,
        "camera.opencv.frame_test.attempted": True,
        "camera.opencv.frame_test.success": True,
        "camera.opencv.frame_test.width": 640,
        "camera.opencv.frame_test.height": 480,
    }
    failed = {**passed, "camera.opencv.frame_test.success": False}
    blocked = {
        "camera.opencv.open_test.success": False,
        "camera.opencv.frame_test.attempted": False,
    }
    assert rule.evaluate(store(passed)).status is DiagnosticStatus.PASS
    assert rule.evaluate(store(failed)).status is DiagnosticStatus.FAIL
    assert rule.evaluate(store(blocked)).status is DiagnosticStatus.UNKNOWN


def test_no_camera_chain_has_no_failures() -> None:
    evidence = store(
        {
            "camera.devices.discovery_available": True,
            "camera.devices.discovered": False,
            "camera.opencv.installed": False,
            "camera.opencv.open_test.attempted": False,
            "camera.opencv.frame_test.attempted": False,
        }
    )
    rules = [
        CameraPresenceRule(),
        CameraPermissionRule(),
        V4L2CapabilityRule(),
        CameraBusyRule(),
        OpenCVInstallationRule(),
        OpenCVOpenRule(),
        FrameCaptureRule(),
    ]
    assert all(
        rule.evaluate(evidence).status is not DiagnosticStatus.FAIL for rule in rules
    )


def test_healthy_chain_passes_through_frame_capture() -> None:
    evidence = store(
        {
            "camera.devices.discovery_available": True,
            "camera.devices.discovered": True,
            "camera.devices.count": 1,
            "camera.devices": [{"readable": True}],
            "camera.v4l2.tool_available": True,
            "camera.v4l2.inspections": [{"success": True}],
            "camera.v4l2.capture_candidates": ["/dev/video0"],
            "camera.selected_candidate": "/dev/video0",
            "camera.selected.busy_known": True,
            "camera.selected.busy": False,
            "camera.selected.busy_process_ids": [],
            "camera.opencv.installed": True,
            "camera.opencv.import_success": True,
            "camera.opencv.version": "4.10",
            "camera.opencv.open_test.attempted": True,
            "camera.opencv.open_test.success": True,
            "camera.opencv.frame_test.attempted": True,
            "camera.opencv.frame_test.success": True,
            "camera.opencv.frame_test.width": 640,
            "camera.opencv.frame_test.height": 480,
        }
    )
    rules = [
        CameraPresenceRule(),
        CameraPermissionRule(),
        V4L2CapabilityRule(),
        CameraBusyRule(),
        OpenCVInstallationRule(),
        OpenCVOpenRule(),
        FrameCaptureRule(),
    ]
    assert all(
        rule.evaluate(evidence).status is DiagnosticStatus.PASS for rule in rules
    )
