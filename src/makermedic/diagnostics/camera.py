"""Deterministic rules for Linux camera and optional OpenCV evidence."""

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


class CameraPresenceRule:
    id = "camera.presence"
    category = "camera"
    dependencies = ()
    required_evidence = frozenset(
        {"camera.devices.discovery_available", "camera.devices.discovered"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        discovery = _value(evidence, "camera.devices.discovery_available", bool)
        discovered = _value(evidence, "camera.devices.discovered", bool)
        count = _number(evidence, "camera.devices.count")
        if discovery is None or discovered is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Camera discovery is unavailable",
            )
        elif discovered:
            status, summary = (
                DiagnosticStatus.PASS,
                f"Linux video device detected ({count or 1})",
            )
        else:
            status, summary = DiagnosticStatus.WARN, "No Linux video device detected"
        return _result(
            self,
            status,
            summary,
            recommendations=("This is normal on systems without a connected camera.",)
            if status is DiagnosticStatus.WARN
            else (),
            finding_kind=FindingKind.OPTIONAL_ABSENCE,
        )


class CameraPermissionRule:
    id = "camera.permissions"
    category = "camera"
    dependencies = ("camera.presence",)
    required_evidence = frozenset({"camera.devices.discovered", "camera.devices"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        devices = _list(evidence, "camera.devices")
        if devices is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Camera permission state is unknown",
            )
        elif any(device.get("readable") is True for device in devices):
            status, summary = DiagnosticStatus.PASS, "A video device is readable"
        else:
            status, summary = (
                DiagnosticStatus.FAIL,
                "No discovered video device is readable",
            )
        return _result(
            self,
            status,
            summary,
            recommendations=(
                "Review the selected video-device permissions and group access.",
            )
            if status is DiagnosticStatus.FAIL
            else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class V4L2CapabilityRule:
    id = "camera.v4l2.capability"
    category = "camera"
    dependencies = ("camera.presence",)
    required_evidence = frozenset(
        {
            "camera.devices.discovered",
            "camera.v4l2.tool_available",
            "camera.v4l2.inspections",
            "camera.v4l2.capture_candidates",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        tool = _value(evidence, "camera.v4l2.tool_available", bool)
        inspections = _list(evidence, "camera.v4l2.inspections")
        candidates = _list(evidence, "camera.v4l2.capture_candidates")
        if tool is False:
            status, summary = DiagnosticStatus.WARN, "v4l2-ctl is unavailable"
        elif tool is None or inspections is None or candidates is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "V4L2 capability state is unknown",
            )
        elif candidates:
            status, summary = (
                DiagnosticStatus.PASS,
                "A V4L2 capture-capable device is available",
            )
        elif any(item.get("success") is True for item in inspections):
            status, summary = (
                DiagnosticStatus.WARN,
                "No video node advertises capture capability",
            )
        else:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "V4L2 inspection did not succeed",
            )
        return _result(
            self,
            status,
            summary,
            recommendations=("Install v4l-utils for optional capability inspection.",)
            if tool is False and status is DiagnosticStatus.WARN
            else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class CameraBusyRule:
    id = "camera.busy"
    category = "camera"
    dependencies = ("camera.presence",)
    required_evidence = frozenset(
        {
            "camera.selected_candidate",
            "camera.selected.busy_known",
            "camera.selected.busy",
            "camera.selected.busy_process_ids",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        candidate = _value(evidence, "camera.selected_candidate", str)
        known = _value(evidence, "camera.selected.busy_known", bool)
        busy = _value(evidence, "camera.selected.busy", bool)
        pids = _list(evidence, "camera.selected.busy_process_ids")
        if candidate is None or known is None or busy is None:
            status, summary = DiagnosticStatus.UNKNOWN, "Camera busy state is unknown"
        elif busy:
            status, summary = DiagnosticStatus.WARN, "Selected camera is in use"
        else:
            status, summary = DiagnosticStatus.PASS, "Selected camera is not in use"
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


class OpenCVInstallationRule:
    id = "camera.opencv.installation"
    category = "camera"
    dependencies = ()
    required_evidence = frozenset(
        {"camera.opencv.installed", "camera.opencv.import_success"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        installed = _value(evidence, "camera.opencv.installed", bool)
        imported = _value(evidence, "camera.opencv.import_success", bool)
        version = _value(evidence, "camera.opencv.version", str)
        error = _value(evidence, "camera.opencv.import_error", str)
        if installed is None:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "OpenCV installation state is unknown",
            )
        elif not installed:
            status, summary = DiagnosticStatus.WARN, "OpenCV is not installed"
        elif imported is False:
            status, summary = (
                DiagnosticStatus.FAIL,
                "OpenCV is installed but cannot be imported",
            )
        elif imported is None:
            status, summary = DiagnosticStatus.UNKNOWN, "OpenCV import state is unknown"
        else:
            status, summary = (
                DiagnosticStatus.PASS,
                f"OpenCV {version or ''} is importable".strip(),
            )
        return _result(
            self,
            status,
            summary,
            causes=(error,) if error else (),
            finding_kind=FindingKind.MISSING_CAPABILITY,
        )


class OpenCVOpenRule:
    id = "camera.opencv.open"
    category = "camera"
    dependencies = (
        "camera.permissions",
        "camera.busy",
        "camera.opencv.installation",
    )
    required_evidence = frozenset(
        {
            "camera.selected_candidate",
            "camera.selected.busy",
            "camera.opencv.import_success",
            "camera.opencv.open_test.attempted",
            "camera.opencv.open_test.success",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        candidate = _value(evidence, "camera.selected_candidate", str)
        attempted = _value(evidence, "camera.opencv.open_test.attempted", bool)
        success = _value(evidence, "camera.opencv.open_test.success", bool)
        error = _value(evidence, "camera.opencv.open_test.error", str)
        if candidate is None or attempted is None or attempted is False:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "OpenCV camera open state is unknown",
            )
        elif success:
            status, summary = DiagnosticStatus.PASS, "OpenCV opened the selected camera"
        elif success is False:
            status, summary = (
                DiagnosticStatus.FAIL,
                "OpenCV could not open the selected camera",
            )
        else:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "OpenCV camera open result is unknown",
            )
        return _result(self, status, summary, causes=(error,) if error else ())


class FrameCaptureRule:
    id = "camera.opencv.frame_capture"
    category = "camera"
    dependencies = ("camera.opencv.open",)
    required_evidence = frozenset(
        {
            "camera.opencv.open_test.success",
            "camera.opencv.frame_test.attempted",
            "camera.opencv.frame_test.success",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        attempted = _value(evidence, "camera.opencv.frame_test.attempted", bool)
        success = _value(evidence, "camera.opencv.frame_test.success", bool)
        width = _number(evidence, "camera.opencv.frame_test.width")
        height = _number(evidence, "camera.opencv.frame_test.height")
        error = _value(evidence, "camera.opencv.frame_test.error", str)
        if attempted is None or attempted is False:
            status, summary = DiagnosticStatus.UNKNOWN, "Frame capture state is unknown"
        elif success:
            status, summary = (
                DiagnosticStatus.PASS,
                f"Captured one frame ({width} x {height})",
            )
        elif success is False:
            status, summary = (
                DiagnosticStatus.FAIL,
                "Camera opened but frame capture failed",
            )
        else:
            status, summary = (
                DiagnosticStatus.UNKNOWN,
                "Frame capture result is unknown",
            )
        return _result(self, status, summary, causes=(error,) if error else ())


def _result(
    rule: Any,
    status: DiagnosticStatus,
    summary: str,
    *,
    causes: tuple[str, ...] = (),
    recommendations: tuple[str, ...] = (),
    finding_kind: FindingKind | None = None,
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id=rule.id,
        category=rule.category,
        status=status,
        dependency_state=dependency_state_for_status(
            status, warning=DependencyState.UNSATISFIED
        ),
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
