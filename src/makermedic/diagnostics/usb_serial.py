"""Deterministic USB and serial diagnostic rules."""

from typing import Any

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticStatus,
    EvidenceAvailability,
    FindingKind,
    dependency_state_for_status,
)


class UsbDiscoveryRule:
    id = "usb.discovery"
    category = "usb"
    dependencies = ()
    required_evidence = frozenset({"usb.discovery_available", "usb.devices.count"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        discovery = _value(evidence, "usb.discovery_available", bool)
        count = _number(evidence, "usb.devices.count")
        if discovery is None or not discovery or count is None:
            status, summary = DiagnosticStatus.UNKNOWN, "USB discovery is unavailable"
        elif count > 0:
            status, summary = DiagnosticStatus.PASS, f"USB devices detected ({count})"
        else:
            status, summary = DiagnosticStatus.WARN, "No USB devices detected"
        return _result(self, status, summary, finding_kind=FindingKind.OPTIONAL_ABSENCE)


class UsbToolingRule:
    id = "usb.tooling"
    category = "usb"
    dependencies = ()
    required_evidence = frozenset(
        {"usb.discovery_available", "usb.lsusb.tool_available", "usb.lsusb.success"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        discovery = _value(evidence, "usb.discovery_available", bool)
        tool = _value(evidence, "usb.lsusb.tool_available", bool)
        success = _value(evidence, "usb.lsusb.success", bool)
        error = _value(evidence, "usb.lsusb.error", str)
        if tool is False and discovery is True:
            status, summary = (
                DiagnosticStatus.WARN,
                "lsusb is unavailable; sysfs discovery works",
            )
        elif tool is False and discovery is not True:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "USB tooling and sysfs discovery are unavailable",
            )
        elif success is True:
            status, summary = DiagnosticStatus.PASS, "lsusb cross-check succeeded"
        elif success is False:
            status, summary = DiagnosticStatus.WARN, "lsusb cross-check failed"
        else:
            status, summary = DiagnosticStatus.UNKNOWN, "lsusb result is unknown"
        return _result(
            self,
            status,
            summary,
            causes=(error,) if error else (),
            warning_state=DependencyState.SATISFIED,
        )


class SerialPresenceRule:
    id = "serial.presence"
    category = "serial"
    dependencies = ()
    required_evidence = frozenset(
        {"serial.discovery_available", "serial.devices.count"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        discovery = _value(evidence, "serial.discovery_available", bool)
        count = _number(evidence, "serial.devices.count")
        if discovery is None or not discovery or count is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Serial discovery is unavailable",
            )
        elif count > 0:
            status, summary = (
                DiagnosticStatus.PASS,
                f"Supported serial devices detected ({count})",
            )
        else:
            status, summary = (
                DiagnosticStatus.WARN,
                "No supported USB serial device detected",
            )
        return _result(
            self,
            status,
            summary,
            recommendations=(
                "This is normal when no development board or USB-UART adapter is "
                "connected.",
            )
            if status is DiagnosticStatus.WARN
            else (),
            finding_kind=FindingKind.OPTIONAL_ABSENCE,
        )


class SerialPermissionRule:
    id = "serial.permissions"
    category = "serial"
    dependencies = ("serial.presence",)
    required_evidence = frozenset({"serial.devices.count", "serial.devices"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        devices = _list(evidence, "serial.devices")
        if not devices:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Serial permission state is unknown",
            )
        elif any(
            device.get("readable") is True and device.get("writable") is True
            for device in devices
        ):
            status, summary = (
                DiagnosticStatus.PASS,
                "A serial device is readable and writable",
            )
        else:
            status, summary = (
                DiagnosticStatus.FAIL,
                "No serial device is fully accessible",
            )
        groups = sorted(
            {
                str(device["group_name"])
                for device in devices or []
                if device.get("group_name")
            }
        )
        recommendation = (
            "Review device permissions and detected group access "
            f"({', '.join(groups)})."
            if groups
            else "Review the serial device permissions and owning group."
        )
        return _result(
            self,
            status,
            summary,
            recommendations=(recommendation,)
            if status is DiagnosticStatus.FAIL
            else (),
        )


class SerialBusyRule:
    id = "serial.busy"
    category = "serial"
    dependencies = ("serial.presence",)
    required_evidence = frozenset(
        {
            "serial.selected_candidate",
            "serial.selected.busy_known",
            "serial.selected.busy",
            "serial.selected.busy_process_ids",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        selected = _value(evidence, "serial.selected_candidate", str)
        known = _value(evidence, "serial.selected.busy_known", bool)
        busy = _value(evidence, "serial.selected.busy", bool)
        pids = _list(evidence, "serial.selected.busy_process_ids")
        if selected is None or known is None or busy is None:
            status, summary = DiagnosticStatus.UNKNOWN, "Serial busy state is unknown"
        elif busy:
            status, summary = DiagnosticStatus.WARN, "Selected serial port is in use"
        else:
            status, summary = DiagnosticStatus.PASS, "Selected serial port is free"
        causes = (
            (f"Process IDs: {', '.join(str(pid) for pid in pids)}",)
            if busy and pids
            else ()
        )
        return _result(
            self,
            status,
            summary,
            causes=causes,
            finding_kind=FindingKind.FAILURE,
        )


class SerialOpenRule:
    id = "serial.open"
    category = "serial"
    dependencies = ("serial.permissions", "serial.busy")
    required_evidence = frozenset(
        {
            "serial.selected_candidate",
            "serial.open_test.requested",
            "serial.open_test.attempted",
            "serial.open_test.success",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        selected = _value(evidence, "serial.selected_candidate", str)
        requested = _value(evidence, "serial.open_test.requested", bool)
        attempted = _value(evidence, "serial.open_test.attempted", bool)
        success = _value(evidence, "serial.open_test.success", bool)
        error = _value(evidence, "serial.open_test.error", str)
        if requested is False:
            status, summary = (
                DiagnosticStatus.BLOCKED,
                "Serial open test was not requested",
            )
        elif selected is None or attempted is False:
            status, summary = (
                DiagnosticStatus.BLOCKED,
                "Serial open test has no safe candidate",
            )
        elif requested is None or attempted is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Serial open-test state is unknown",
            )
        elif success:
            status, summary = (
                DiagnosticStatus.PASS,
                "Serial port opened and closed successfully",
            )
        elif success is False:
            status, summary = DiagnosticStatus.FAIL, "Serial port open failed"
        else:
            status, summary = DiagnosticStatus.UNKNOWN, "Serial open result is unknown"
        return _result(self, status, summary, causes=(error,) if error else ())


def _result(
    rule: Any,
    status: DiagnosticStatus,
    summary: str,
    *,
    causes: tuple[str, ...] = (),
    recommendations: tuple[str, ...] = (),
    warning_state: DependencyState = DependencyState.UNSATISFIED,
    finding_kind: FindingKind | None = None,
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id=rule.id,
        category=rule.category,
        status=status,
        dependency_state=dependency_state_for_status(status, warning=warning_state),
        finding_kind=finding_kind if status is DiagnosticStatus.WARN else None,
        summary=summary,
        evidence=tuple(sorted(rule.required_evidence)),
        causes=causes,
        recommendations=recommendations,
    )


def _value[T](evidence: EvidenceStore, key: str, expected: type[T]) -> T | None:
    item = evidence.get(key)
    if (
        item is None
        or item.availability is EvidenceAvailability.UNAVAILABLE
        or not isinstance(item.value, expected)
    ):
        return None
    return item.value


def _number(evidence: EvidenceStore, key: str) -> int | None:
    value = _value(evidence, key, int)
    return None if isinstance(value, bool) else value


def _list(evidence: EvidenceStore, key: str) -> list[Any] | None:
    return _value(evidence, key, list)
