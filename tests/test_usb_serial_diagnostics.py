from typing import Any

import pytest

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence
from makermedic.diagnostics.usb_serial import (
    SerialBusyRule,
    SerialOpenRule,
    SerialPermissionRule,
    SerialPresenceRule,
    UsbDiscoveryRule,
    UsbToolingRule,
)


def store(values: dict[str, Any]) -> EvidenceStore:
    return EvidenceStore(
        Evidence(key=key, source="test", value=value) for key, value in values.items()
    )


@pytest.mark.parametrize(
    ("available", "count", "expected"),
    [
        (True, 2, DiagnosticStatus.PASS),
        (True, 0, DiagnosticStatus.WARN),
        (False, None, DiagnosticStatus.UNKNOWN),
    ],
)
def test_usb_discovery(
    available: bool, count: int | None, expected: DiagnosticStatus
) -> None:
    assert (
        UsbDiscoveryRule()
        .evaluate(
            store({"usb.discovery_available": available, "usb.devices.count": count})
        )
        .status
        is expected
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {
                "usb.discovery_available": True,
                "usb.lsusb.tool_available": True,
                "usb.lsusb.success": True,
            },
            DiagnosticStatus.PASS,
        ),
        (
            {"usb.discovery_available": True, "usb.lsusb.tool_available": False},
            DiagnosticStatus.WARN,
        ),
        (
            {"usb.discovery_available": False, "usb.lsusb.tool_available": False},
            DiagnosticStatus.UNKNOWN,
        ),
        (
            {
                "usb.discovery_available": True,
                "usb.lsusb.tool_available": True,
                "usb.lsusb.success": False,
            },
            DiagnosticStatus.WARN,
        ),
    ],
)
def test_usb_tooling(values: dict[str, Any], expected: DiagnosticStatus) -> None:
    assert UsbToolingRule().evaluate(store(values)).status is expected


@pytest.mark.parametrize(
    ("available", "count", "expected"),
    [
        (True, 1, DiagnosticStatus.PASS),
        (True, 0, DiagnosticStatus.WARN),
        (False, None, DiagnosticStatus.UNKNOWN),
    ],
)
def test_serial_presence(
    available: bool, count: int | None, expected: DiagnosticStatus
) -> None:
    result = SerialPresenceRule().evaluate(
        store(
            {
                "serial.discovery_available": available,
                "serial.devices.count": count,
            }
        )
    )
    assert result.status is expected
    assert "driver" not in result.summary.casefold()


def test_serial_permissions_pass_fail_and_blocked_with_group_recommendation() -> None:
    rule = SerialPermissionRule()
    passed = {
        "serial.devices.count": 1,
        "serial.devices": [{"readable": True, "writable": True}],
    }
    failed = {
        "serial.devices.count": 1,
        "serial.devices": [{"readable": True, "writable": False, "group_name": "uucp"}],
    }
    blocked = {"serial.devices.count": 0, "serial.devices": []}
    assert rule.evaluate(store(passed)).status is DiagnosticStatus.PASS
    result = rule.evaluate(store(failed))
    assert result.status is DiagnosticStatus.FAIL
    assert "uucp" in result.recommendations[0]
    assert rule.evaluate(store(blocked)).status is DiagnosticStatus.UNKNOWN


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, DiagnosticStatus.UNKNOWN),
        (
            {
                "serial.selected_candidate": "/dev/ttyUSB0",
                "serial.selected.busy_known": True,
                "serial.selected.busy": False,
                "serial.selected.busy_process_ids": [],
            },
            DiagnosticStatus.PASS,
        ),
        (
            {
                "serial.selected_candidate": "/dev/ttyUSB0",
                "serial.selected.busy_known": True,
                "serial.selected.busy": True,
                "serial.selected.busy_process_ids": [42],
            },
            DiagnosticStatus.WARN,
        ),
        (
            {
                "serial.selected_candidate": "/dev/ttyUSB0",
                "serial.selected.busy_known": False,
            },
            DiagnosticStatus.UNKNOWN,
        ),
    ],
)
def test_serial_busy(values: dict[str, Any], expected: DiagnosticStatus) -> None:
    assert SerialBusyRule().evaluate(store(values)).status is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"serial.open_test.requested": False}, DiagnosticStatus.BLOCKED),
        (
            {
                "serial.open_test.requested": True,
                "serial.open_test.attempted": False,
            },
            DiagnosticStatus.BLOCKED,
        ),
        (
            {
                "serial.selected_candidate": "/dev/ttyUSB0",
                "serial.open_test.requested": True,
                "serial.open_test.attempted": True,
                "serial.open_test.success": True,
            },
            DiagnosticStatus.PASS,
        ),
        (
            {
                "serial.selected_candidate": "/dev/ttyUSB0",
                "serial.open_test.requested": True,
                "serial.open_test.attempted": True,
                "serial.open_test.success": False,
                "serial.open_test.error": "permission denied",
            },
            DiagnosticStatus.FAIL,
        ),
    ],
)
def test_serial_open(values: dict[str, Any], expected: DiagnosticStatus) -> None:
    assert SerialOpenRule().evaluate(store(values)).status is expected


def test_no_usb_or_serial_devices_has_no_fail_cascade() -> None:
    evidence = store(
        {
            "usb.discovery_available": True,
            "usb.devices.count": 0,
            "usb.lsusb.tool_available": False,
            "serial.discovery_available": True,
            "serial.devices.count": 0,
            "serial.devices": [],
            "serial.open_test.requested": False,
        }
    )
    rules = [
        UsbDiscoveryRule(),
        UsbToolingRule(),
        SerialPresenceRule(),
        SerialPermissionRule(),
        SerialBusyRule(),
        SerialOpenRule(),
    ]
    assert all(
        rule.evaluate(evidence).status is not DiagnosticStatus.FAIL for rule in rules
    )


def test_busy_port_warns_and_open_is_blocked() -> None:
    evidence = store(
        {
            "serial.selected_candidate": "/dev/ttyUSB0",
            "serial.selected.busy_known": True,
            "serial.selected.busy": True,
            "serial.selected.busy_process_ids": [42],
            "serial.open_test.requested": True,
            "serial.open_test.attempted": False,
        }
    )
    assert SerialBusyRule().evaluate(evidence).status is DiagnosticStatus.WARN
    assert SerialOpenRule().evaluate(evidence).status is DiagnosticStatus.BLOCKED
