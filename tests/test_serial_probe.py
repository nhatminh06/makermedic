import os
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from makermedic.core.commands import CommandResult, CommandStatus
from makermedic.probes.usb_serial import SerialProbe


class FakeRunner:
    def __init__(self, states: dict[str, CommandResult]) -> None:
        self.states = states
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        command = tuple(args)
        self.calls.append(command)
        return self.states[command[-1]]


def fuser(
    *,
    code: int | None = 1,
    status: CommandStatus = CommandStatus.COMPLETED,
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        args=("fuser",), status=status, return_code=code, stderr=stderr
    )


def globber(paths: list[str]):
    def match(pattern: str) -> list[str]:
        prefix = "/dev/ttyUSB" if "ttyUSB" in pattern else "/dev/ttyACM"
        return [path for path in paths if path.startswith(prefix)]

    return match


def make_probe(
    paths: list[str],
    *,
    readable: tuple[str, ...] | None = None,
    writable: tuple[str, ...] | None = None,
    runner: FakeRunner | None = None,
    fuser_available: bool = False,
    tty_root: Path = Path("/missing"),
    open_test: bool = False,
    serial_factory=None,
    gids: tuple[int, ...] = (20,),
) -> SerialProbe:
    readable_set = set(paths if readable is None else readable)
    writable_set = set(paths if writable is None else writable)
    return SerialProbe(
        open_test=open_test,
        globber=globber(paths),
        access=lambda path, mode: (
            path in (readable_set if mode == os.R_OK else writable_set)
        ),
        stat=lambda _path: SimpleNamespace(st_mode=0o20660, st_uid=0, st_gid=20),
        groups=lambda: gids,
        effective_gid=lambda: 1000,
        group_name=lambda gid: "dialout" if gid == 20 else None,
        tty_sysfs_root=tty_root,
        which=lambda name: (
            "/usr/bin/fuser" if name == "fuser" and fuser_available else None
        ),
        runner=runner,  # type: ignore[arg-type]
        serial_factory=serial_factory,
    )


def collect(probe: SerialProbe):
    return {item.key: item for item in probe.collect()}


def test_no_supported_serial_devices_and_unrelated_tty_excluded() -> None:
    evidence = collect(make_probe(["/dev/ttyS0", "/dev/tty0"]))
    assert evidence["serial.devices.count"].value == 0
    assert evidence["serial.devices"].value == []


def test_serial_discovery_error_is_explicit() -> None:
    def broken_glob(_pattern: str) -> list[str]:
        raise OSError("device filesystem unavailable")

    evidence = {item.key: item for item in SerialProbe(globber=broken_glob).collect()}
    assert evidence["serial.discovery_available"].value is False
    assert evidence["serial.devices"].availability.value == "UNAVAILABLE"


@pytest.mark.parametrize("path", ["/dev/ttyUSB0", "/dev/ttyACM0"])
def test_tty_usb_and_acm_discovery(path: str) -> None:
    evidence = collect(make_probe([path]))
    assert evidence["serial.devices.count"].value == 1
    assert evidence["serial.devices"].value[0]["path"] == path


def test_multiple_noncontiguous_devices_sort_naturally() -> None:
    evidence = collect(
        make_probe(["/dev/ttyUSB10", "/dev/ttyACM2", "/dev/ttyUSB2", "/dev/ttyACM0"])
    )
    assert [item["path"] for item in evidence["serial.devices"].value] == [
        "/dev/ttyACM0",
        "/dev/ttyACM2",
        "/dev/ttyUSB2",
        "/dev/ttyUSB10",
    ]


def test_permissions_mode_ownership_and_group_membership() -> None:
    member = collect(make_probe(["/dev/ttyUSB0"], gids=(20,)))["serial.devices"].value[
        0
    ]
    nonmember = collect(make_probe(["/dev/ttyUSB0"], gids=(30,)))[
        "serial.devices"
    ].value[0]
    assert member["readable"] is True and member["writable"] is True
    assert member["mode"] == "0o660"
    assert member["owner_uid"] == 0 and member["owner_gid"] == 20
    assert member["group_name"] == "dialout"
    assert member["current_process_in_group"] is True
    assert nonmember["current_process_in_group"] is False


def test_inaccessible_and_partial_access_devices() -> None:
    denied = collect(make_probe(["/dev/ttyUSB0"], readable=(), writable=()))
    partial = collect(make_probe(["/dev/ttyUSB0"], writable=()))
    assert denied["serial.devices"].value[0]["readable"] is False
    assert denied["serial.selected_candidate"].value is None
    assert partial["serial.devices"].value[0]["readable"] is True
    assert partial["serial.devices"].value[0]["writable"] is False


def test_usb_parent_correlation_excludes_serial_number(tmp_path: Path) -> None:
    usb = tmp_path / "devices" / "1-1"
    tty_device = usb / "1-1:1.0" / "tty" / "ttyACM0"
    tty_device.mkdir(parents=True)
    usb.joinpath("idVendor").write_text("2341")
    usb.joinpath("idProduct").write_text("0043")
    usb.joinpath("manufacturer").write_text("Arduino LLC")
    usb.joinpath("product").write_text("Uno")
    usb.joinpath("serial").write_text("SECRET-SERIAL")
    tty_root = tmp_path / "class" / "tty" / "ttyACM0"
    tty_root.mkdir(parents=True)
    tty_root.joinpath("device").symlink_to(tty_device, target_is_directory=True)

    identity = collect(
        make_probe(["/dev/ttyACM0"], tty_root=tmp_path / "class" / "tty")
    )["serial.devices"].value[0]["usb"]
    assert identity["vendor_id"] == "2341"
    assert identity["product_id"] == "0043"
    assert identity["manufacturer"] == "Arduino LLC"
    assert identity["product"] == "Uno"
    assert "serial" not in identity
    assert "SECRET-SERIAL" not in str(identity)


def test_no_usb_parent_is_safe() -> None:
    device = collect(make_probe(["/dev/ttyUSB0"]))["serial.devices"].value[0]
    assert device["usb"] is None


@pytest.mark.parametrize(
    ("state", "known", "busy", "pids"),
    [
        (fuser(code=1), True, False, []),
        (fuser(code=0, stderr="/dev/ttyUSB0: 1234m"), True, True, [1234]),
        (fuser(status=CommandStatus.TIMED_OUT, code=None), False, None, []),
    ],
)
def test_busy_free_and_unknown(
    state: CommandResult, known: bool, busy: bool | None, pids: list[int]
) -> None:
    runner = FakeRunner({"/dev/ttyUSB0": state})
    evidence = collect(
        make_probe(["/dev/ttyUSB0"], runner=runner, fuser_available=True)
    )
    assert evidence["serial.busy.states"].value[0]["busy_known"] is known
    assert evidence["serial.busy.states"].value[0]["busy"] is busy
    assert evidence["serial.busy.states"].value[0]["process_ids"] == pids
    assert all(call[0] != "kill" for call in runner.calls)


def test_fuser_unavailable_records_unknown_selected_busy_state() -> None:
    evidence = collect(make_probe(["/dev/ttyUSB0"]))
    assert evidence["serial.busy.tool_available"].value is False
    assert evidence["serial.selected.busy_known"].value is None


def test_selection_prefers_free_then_deterministic_unknown_and_avoids_busy() -> None:
    states = {
        "/dev/ttyACM0": fuser(code=0, stderr="/dev/ttyACM0: 99"),
        "/dev/ttyUSB0": fuser(code=1),
        "/dev/ttyUSB1": fuser(status=CommandStatus.TIMED_OUT, code=None),
    }
    evidence = collect(
        make_probe(list(states), runner=FakeRunner(states), fuser_available=True)
    )
    assert evidence["serial.selected_candidate"].value == "/dev/ttyUSB0"


class FakeSerial:
    def __init__(self, open_error: Exception | None = None) -> None:
        self.open_error = open_error
        self.is_open = False
        self.closed = 0
        self.opened_settings: dict[str, Any] = {}
        self.writes = 0
        self.reads = 0

    def open(self) -> None:
        self.opened_settings = {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "write_timeout": self.write_timeout,
            "dtr": self.dtr,
            "rts": self.rts,
        }
        if self.open_error:
            raise self.open_error
        self.is_open = True

    def close(self) -> None:
        self.is_open = False
        self.closed += 1


def test_open_test_not_requested() -> None:
    evidence = collect(make_probe(["/dev/ttyUSB0"]))
    assert evidence["serial.open_test.requested"].value is False
    assert evidence["serial.open_test.attempted"].value is False


@pytest.mark.parametrize("error", [None, TimeoutError("open timed out")])
def test_opt_in_open_success_or_failure_always_closes_without_io(
    error: Exception | None,
) -> None:
    port = FakeSerial(error)
    evidence = collect(
        make_probe(
            ["/dev/ttyUSB0"],
            open_test=True,
            serial_factory=lambda: port,
        )
    )
    assert evidence["serial.open_test.attempted"].value is True
    assert evidence["serial.open_test.success"].value is (error is None)
    assert port.opened_settings == {
        "port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "timeout": 0,
        "write_timeout": 0,
        "dtr": False,
        "rts": False,
    }
    assert port.closed == 1
    assert port.writes == 0 and port.reads == 0
