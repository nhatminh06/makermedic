"""Linux USB and USB-serial evidence collection."""

import glob
import grp
import os
import re
import shutil
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from makermedic.core.commands import CommandRunner, CommandStatus
from makermedic.core.models import Evidence, EvidenceAvailability


class UsbProbe:
    """Discover physical USB devices through sysfs and optionally cross-check lsusb."""

    id = "usb.discovery"
    categories = ("usb",)

    def __init__(
        self,
        *,
        sysfs_root: Path = Path("/sys/bus/usb/devices"),
        which: Callable[[str], str | None] = shutil.which,
        runner: CommandRunner | None = None,
    ) -> None:
        self._sysfs_root = sysfs_root
        self._which = which
        self._runner = runner or CommandRunner()

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        try:
            devices = [
                device
                for entry in sorted(
                    self._sysfs_root.iterdir(), key=lambda path: path.name
                )
                if (device := _usb_device(entry)) is not None
            ]
            discovery_available = True
        except OSError:
            devices = None
            discovery_available = False

        tool_available = self._which("lsusb") is not None
        if tool_available:
            command = self._runner.run(("lsusb",))
            lsusb = _lsusb_snapshot(command)
        else:
            lsusb = {
                "success": None,
                "devices": None,
                "outcome": "NOT_FOUND",
                "error": None,
            }
        return (
            Evidence(
                key="usb.discovery_available",
                source=source,
                value=discovery_available,
            ),
            _optional(
                "usb.devices.count",
                source,
                len(devices) if devices is not None else None,
            ),
            _optional("usb.devices", source, devices),
            Evidence(
                key="usb.lsusb.tool_available", source=source, value=tool_available
            ),
            _optional("usb.lsusb.success", source, lsusb["success"]),
            _optional("usb.lsusb.devices", source, lsusb["devices"]),
            Evidence(key="usb.lsusb.outcome", source=source, value=lsusb["outcome"]),
            _optional("usb.lsusb.error", source, lsusb["error"]),
        )


class SerialProbe:
    """Discover supported serial nodes and optionally perform a cautious open."""

    id = "serial.discovery"
    categories = ("serial",)

    def __init__(
        self,
        *,
        open_test: bool = False,
        globber: Callable[[str], list[str]] = glob.glob,
        access: Callable[[str, int], bool] = os.access,
        stat: Callable[[str], os.stat_result] = os.stat,
        groups: Callable[[], Sequence[int]] = os.getgroups,
        effective_gid: Callable[[], int] = os.getegid,
        group_name: Callable[[int], str | None] | None = None,
        tty_sysfs_root: Path = Path("/sys/class/tty"),
        which: Callable[[str], str | None] = shutil.which,
        runner: CommandRunner | None = None,
        serial_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._open_test = open_test
        self._globber = globber
        self._access = access
        self._stat = stat
        self._groups = groups
        self._effective_gid = effective_gid
        self._group_name = group_name or _group_name
        self._tty_sysfs_root = tty_sysfs_root
        self._which = which
        self._runner = runner or CommandRunner()
        self._serial_factory = serial_factory or _serial_factory

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        try:
            paths = sorted(
                set(self._globber("/dev/ttyUSB*") + self._globber("/dev/ttyACM*")),
                key=_serial_sort_key,
            )
            devices = [self._device_record(path) for path in paths]
            discovery_available = True
        except OSError:
            paths = []
            devices = None
            discovery_available = False

        fuser_available = self._which("fuser") is not None
        busy_states = (
            [self._busy_state(path) for path in paths] if fuser_available else []
        )
        selected = _select_serial_candidate(devices or [], busy_states)
        selected_busy = next(
            (state for state in busy_states if state["path"] == selected), None
        )
        evidence = [
            Evidence(
                key="serial.discovery_available",
                source=source,
                value=discovery_available,
            ),
            _optional(
                "serial.devices.count",
                source,
                len(devices) if devices is not None else None,
            ),
            _optional("serial.devices", source, devices),
            Evidence(
                key="serial.busy.tool_available",
                source=source,
                value=fuser_available,
            ),
            Evidence(key="serial.busy.states", source=source, value=busy_states),
            Evidence(key="serial.selected_candidate", source=source, value=selected),
            _optional(
                "serial.selected.busy_known",
                source,
                selected_busy["busy_known"] if selected_busy else None,
            ),
            _optional(
                "serial.selected.busy",
                source,
                selected_busy["busy"] if selected_busy else None,
            ),
            _optional(
                "serial.selected.busy_process_ids",
                source,
                selected_busy["process_ids"] if selected_busy else None,
            ),
        ]
        evidence.extend(self._open_serial(selected))
        return tuple(evidence)

    def _device_record(self, path: str) -> dict[str, object]:
        record: dict[str, object] = {
            "path": path,
            "readable": self._access(path, os.R_OK),
            "writable": self._access(path, os.W_OK),
            "usb": _tty_usb_identity(self._tty_sysfs_root, Path(path).name),
        }
        try:
            metadata = self._stat(path)
        except OSError as error:
            record.update({"stat_available": False, "stat_error": _error_text(error)})
        else:
            gids = set(self._groups()) | {self._effective_gid()}
            record.update(
                {
                    "stat_available": True,
                    "mode": oct(metadata.st_mode & 0o777),
                    "owner_uid": metadata.st_uid,
                    "owner_gid": metadata.st_gid,
                    "group_name": self._group_name(metadata.st_gid),
                    "current_process_in_group": metadata.st_gid in gids,
                }
            )
        return record

    def _busy_state(self, path: str) -> dict[str, object]:
        command = self._runner.run(("fuser", path))
        base: dict[str, object] = {"path": path, "process_ids": []}
        if command.status is not CommandStatus.COMPLETED:
            return {**base, "busy_known": False, "busy": None}
        if command.return_code == 1:
            return {**base, "busy_known": True, "busy": False}
        if command.return_code != 0:
            return {**base, "busy_known": False, "busy": None}
        pids = [
            int(value)
            for value in re.findall(
                r"(?<![\w/])\d+(?=[A-Za-z]*\b)", command.stdout + command.stderr
            )
        ]
        return {**base, "busy_known": True, "busy": bool(pids), "process_ids": pids}

    def _open_serial(self, selected: str | None) -> tuple[Evidence, ...]:
        source = self.id
        base = [
            Evidence(
                key="serial.open_test.requested", source=source, value=self._open_test
            )
        ]
        if not self._open_test or selected is None:
            return (
                *base,
                Evidence(key="serial.open_test.attempted", source=source, value=False),
                _unavailable("serial.open_test.success", source),
                Evidence(key="serial.open_test.device", source=source, value=selected),
                _unavailable("serial.open_test.error", source),
            )
        port = None
        try:
            port = self._serial_factory()
            port.port = selected
            port.baudrate = 9600
            port.timeout = 0
            port.write_timeout = 0
            port.dtr = False
            port.rts = False
            port.open()
        except Exception as error:  # narrow pyserial/device boundary
            success = False
            message = _error_text(error)
        else:
            success = True
            message = None
        finally:
            if port is not None:
                port.close()
        return (
            *base,
            Evidence(key="serial.open_test.attempted", source=source, value=True),
            Evidence(key="serial.open_test.success", source=source, value=success),
            Evidence(key="serial.open_test.device", source=source, value=selected),
            _optional("serial.open_test.error", source, message),
        )


def _usb_device(entry: Path) -> dict[str, object] | None:
    vendor = _read(entry / "idVendor")
    product = _read(entry / "idProduct")
    if vendor is None or product is None:
        return None
    return {
        "sysfs_name": entry.name,
        "vendor_id": vendor.casefold(),
        "product_id": product.casefold(),
        "manufacturer": _read(entry / "manufacturer"),
        "product": _read(entry / "product"),
        "device_class": _read(entry / "bDeviceClass"),
    }


def _lsusb_snapshot(command: Any) -> dict[str, object | None]:
    if command.status is not CommandStatus.COMPLETED:
        return {
            "success": None,
            "devices": None,
            "outcome": command.status.value,
            "error": _concise(command.stderr or command.stdout) or None,
        }
    if command.return_code != 0:
        return {
            "success": False,
            "devices": None,
            "outcome": command.status.value,
            "error": _concise(command.stderr or command.stdout) or None,
        }
    devices = []
    pattern = re.compile(
        r"^Bus \d+ Device \d+: ID (?P<vid>[0-9a-fA-F]{4}):"
        r"(?P<pid>[0-9a-fA-F]{4})(?: (?P<description>.*))?$"
    )
    for line in command.stdout.splitlines():
        match = pattern.fullmatch(line.strip())
        if match is None:
            return {
                "success": None,
                "devices": None,
                "outcome": "MALFORMED_OUTPUT",
                "error": None,
            }
        devices.append(
            {
                "vendor_id": match.group("vid").casefold(),
                "product_id": match.group("pid").casefold(),
                "description": match.group("description") or None,
            }
        )
    return {
        "success": True,
        "devices": devices,
        "outcome": command.status.value,
        "error": None,
    }


def _tty_usb_identity(root: Path, tty_name: str) -> dict[str, object] | None:
    try:
        current = root.joinpath(tty_name, "device").resolve(strict=True)
    except OSError:
        return None
    for parent in (current, *current.parents):
        device = _usb_device(parent)
        if device is not None:
            device.pop("sysfs_name", None)
            device.pop("device_class", None)
            return device
    return None


def _select_serial_candidate(
    devices: list[dict[str, object]], busy_states: list[dict[str, object]]
) -> str | None:
    busy_by_path = {str(item["path"]): item for item in busy_states}
    candidates = []
    for device in devices:
        path = str(device["path"])
        if not (device.get("readable") is True and device.get("writable") is True):
            continue
        state = busy_by_path.get(path)
        if state and state.get("busy") is True:
            continue
        rank = 0 if state and state.get("busy_known") is True else 1
        candidates.append((rank, _serial_sort_key(path), path))
    return min(candidates)[2] if candidates else None


def _serial_factory() -> Any:
    import serial

    return serial.Serial(port=None)


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def _group_name(gid: int) -> str | None:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return None


def _serial_sort_key(path: str) -> tuple[str, int, str]:
    match = re.search(r"(tty(?:ACM|USB))(\d+)$", path)
    if match is None:
        return path, 2**31, path
    return match.group(1), int(match.group(2)), path


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
