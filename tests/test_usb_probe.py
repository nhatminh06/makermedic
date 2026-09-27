from collections.abc import Sequence
from pathlib import Path

import pytest

from makermedic.core.commands import CommandResult, CommandStatus
from makermedic.core.models import EvidenceAvailability
from makermedic.probes.usb_serial import UsbProbe


class FakeRunner:
    def __init__(self, command: CommandResult) -> None:
        self.command = command
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(args))
        return self.command


def command(
    output: str = "",
    *,
    code: int | None = 0,
    status: CommandStatus = CommandStatus.COMPLETED,
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        args=("lsusb",), status=status, return_code=code, stdout=output, stderr=stderr
    )


def add_usb(
    root: Path,
    name: str,
    *,
    vendor: str = "2341",
    product_id: str = "0043",
    manufacturer: str | None = "Arduino LLC",
    product: str | None = "USB Serial Device",
    device_class: str = "00",
) -> Path:
    device = root / name
    device.mkdir()
    device.joinpath("idVendor").write_text(vendor)
    device.joinpath("idProduct").write_text(product_id)
    device.joinpath("bDeviceClass").write_text(device_class)
    if manufacturer is not None:
        device.joinpath("manufacturer").write_text(manufacturer)
    if product is not None:
        device.joinpath("product").write_text(product)
    device.joinpath("serial").write_text("MUST-NOT-BE-COLLECTED")
    return device


def collect(probe: UsbProbe):
    return {item.key: item for item in probe.collect()}


def test_sysfs_unavailable() -> None:
    evidence = collect(UsbProbe(sysfs_root=Path("/definitely/missing")))
    assert evidence["usb.discovery_available"].value is False
    assert evidence["usb.devices"].availability is EvidenceAvailability.UNAVAILABLE


def test_zero_usb_devices(tmp_path: Path) -> None:
    evidence = collect(UsbProbe(sysfs_root=tmp_path, which=lambda _name: None))
    assert evidence["usb.discovery_available"].value is True
    assert evidence["usb.devices.count"].value == 0
    assert evidence["usb.devices"].value == []


def test_usb_fields_and_serial_number_exclusion(tmp_path: Path) -> None:
    add_usb(tmp_path, "1-1")
    evidence = collect(UsbProbe(sysfs_root=tmp_path, which=lambda _name: None))
    device = evidence["usb.devices"].value[0]
    assert device == {
        "sysfs_name": "1-1",
        "vendor_id": "2341",
        "product_id": "0043",
        "manufacturer": "Arduino LLC",
        "product": "USB Serial Device",
        "device_class": "00",
    }
    assert "serial" not in device
    assert "MUST-NOT-BE-COLLECTED" not in str(evidence)


def test_multiple_usb_devices_sorted_and_interfaces_excluded(tmp_path: Path) -> None:
    add_usb(tmp_path, "2-1", vendor="10c4", product_id="ea60")
    add_usb(tmp_path, "1-2", vendor="1a86", product_id="7523")
    interface = tmp_path / "1-2:1.0"
    interface.mkdir()
    interface.joinpath("bInterfaceClass").write_text("02")
    evidence = collect(UsbProbe(sysfs_root=tmp_path, which=lambda _name: None))
    assert [item["sysfs_name"] for item in evidence["usb.devices"].value] == [
        "1-2",
        "2-1",
    ]


def test_lsusb_absent_while_sysfs_works(tmp_path: Path) -> None:
    add_usb(tmp_path, "1-1")
    evidence = collect(UsbProbe(sysfs_root=tmp_path, which=lambda _name: None))
    assert evidence["usb.lsusb.tool_available"].value is False
    assert evidence["usb.discovery_available"].value is True


def test_lsusb_success_parses_minimal_identity(tmp_path: Path) -> None:
    runner = FakeRunner(command("Bus 001 Device 002: ID 2341:0043 Arduino Uno R3\n"))
    evidence = collect(
        UsbProbe(
            sysfs_root=tmp_path,
            which=lambda _name: "/usr/bin/lsusb",
            runner=runner,  # type: ignore[arg-type]
        )
    )
    assert evidence["usb.lsusb.success"].value is True
    assert evidence["usb.lsusb.devices"].value == [
        {
            "vendor_id": "2341",
            "product_id": "0043",
            "description": "Arduino Uno R3",
        }
    ]
    assert runner.calls == [("lsusb",)]


@pytest.mark.parametrize(
    ("result", "success", "outcome"),
    [
        (command(code=1, stderr="failed"), False, "COMPLETED"),
        (command(status=CommandStatus.TIMED_OUT, code=None), None, "TIMED_OUT"),
        (command("malformed output"), None, "MALFORMED_OUTPUT"),
    ],
)
def test_lsusb_failure_timeout_and_malformed(
    tmp_path: Path,
    result: CommandResult,
    success: bool | None,
    outcome: str,
) -> None:
    evidence = collect(
        UsbProbe(
            sysfs_root=tmp_path,
            which=lambda _name: "/usr/bin/lsusb",
            runner=FakeRunner(result),  # type: ignore[arg-type]
        )
    )
    assert evidence["usb.lsusb.success"].value is success
    assert evidence["usb.lsusb.outcome"].value == outcome
