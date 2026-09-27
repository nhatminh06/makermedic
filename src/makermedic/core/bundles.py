"""Privacy-allowlisted support-bundle planning and atomic ZIP export."""

import json
import os
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from makermedic import __version__
from makermedic.core.errors import BundleOutputExistsError, BundleWriteError
from makermedic.core.models import (
    DependencyState,
    DiagnosticRun,
    DiagnosticStatus,
    Evidence,
    EvidenceAvailability,
    FindingKind,
    ResultOrigin,
    RootCauseAnalysis,
    RootFinding,
)
from makermedic.core.snapshots import DiagnosticSnapshot

BUNDLE_SCHEMA_VERSION = 1
PRIVACY_POLICY_VERSION = 1
ARCHIVE_ROOT = "makermedic-support"
CORE_FILES = ("diagnostics.json", "findings.json", "manifest.json", "summary.txt")
PRIVACY_GUARANTEES = (
    "No environment variables",
    "No credentials",
    "No image data",
    "No USB serial numbers",
    "No full process command lines",
    "No raw logs",
)


class BundlePrivacyDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = PRIVACY_POLICY_VERSION
    evidence_export_mode: Literal["allowlist"] = "allowlist"
    contains_environment_variables: Literal[False] = False
    contains_credentials: Literal[False] = False
    contains_image_data: Literal[False] = False
    contains_usb_serial_numbers: Literal[False] = False
    contains_full_process_command_lines: Literal[False] = False
    contains_raw_logs: Literal[False] = False


class BundleManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_schema_version: int = BUNDLE_SCHEMA_VERSION
    created_at: datetime
    makermedic_version: str = Field(min_length=1)
    included_categories: tuple[str, ...]
    file_inventory: tuple[str, ...]
    privacy_policy_version: int = PRIVACY_POLICY_VERSION
    source_type: Literal["live_diagnosis", "snapshot"]
    omitted_evidence_count: int = Field(ge=0)
    omitted_evidence_keys: tuple[str, ...]
    privacy: BundlePrivacyDeclaration = BundlePrivacyDeclaration()


class BundleEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    availability: EvidenceAvailability
    value: JsonValue = None


class BundleDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str
    category: str
    status: DiagnosticStatus
    dependency_state: DependencyState
    result_origin: ResultOrigin
    finding_kind: FindingKind | None
    summary: str
    blocked_by: tuple[str, ...]
    recommendations: tuple[str, ...]
    evidence_keys: tuple[str, ...]


class BundleFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str
    kind: FindingKind
    status: DiagnosticStatus
    summary: str
    affected_diagnostics: tuple[str, ...]
    recommendations: tuple[str, ...]
    evidence_refs: tuple[str, ...]


class BundleCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    evidence: tuple[BundleEvidence, ...]


class BundlePlan(BaseModel):
    """Validated logical bundle content shared by preview and export."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: BundleManifest
    diagnostics: tuple[BundleDiagnostic, ...]
    findings: tuple[BundleFinding, ...]
    category_files: tuple[BundleCategory, ...]
    summary: str
    exported_evidence: tuple[str, ...]
    omitted_evidence: tuple[str, ...]


_SIMPLE_ALLOWED = frozenset(
    {
        # System
        "system.os",
        "system.platform",
        "system.kernel",
        "system.architecture",
        "system.cpu.logical_count",
        "system.cpu.physical_count",
        "system.memory.total_bytes",
        "system.memory.available_bytes",
        "system.memory.percent_used",
        "system.disk.root.total_bytes",
        "system.disk.root.free_bytes",
        "system.disk.root.percent_used",
        # Python (paths are intentionally omitted)
        "python.version",
        "python.version_info",
        "python.implementation",
        "python.in_virtualenv",
        "python.venv.type",
        "python.pip.module.available",
        "python.pip.module.version",
        "python.pip.path.available",
        "python.pip.path.version",
        "python.package.requested",
        "python.package.installed",
        "python.package.version",
        # GPU
        "gpu.nvidia.hardware_detected",
        "gpu.nvidia.hardware_count",
        "gpu.nvidia.smi.available",
        "gpu.nvidia.driver.available",
        "gpu.nvidia.driver.version",
        "gpu.nvidia.smi.outcome",
        "gpu.nvidia.smi.return_code",
        "gpu.nvidia.driver.device_count",
        "gpu.nvidia.nvml.binding_available",
        "gpu.nvidia.nvml.available",
        "gpu.nvidia.nvml.device_count",
        "gpu.nvidia.nvml.device_names",
        "gpu.pytorch.installed",
        "gpu.pytorch.import_success",
        "gpu.pytorch.version",
        "gpu.pytorch.cuda.build_version",
        "gpu.pytorch.cuda.available",
        "gpu.pytorch.cuda.device_count",
        "gpu.pytorch.cuda.allocation_test.attempted",
        "gpu.pytorch.cuda.allocation_test.success",
        "gpu.pytorch.cuda.compute_test.attempted",
        "gpu.pytorch.cuda.compute_test.success",
        # Camera
        "camera.devices.discovery_available",
        "camera.devices.discovered",
        "camera.devices.count",
        "camera.v4l2.tool_available",
        "camera.v4l2.capture_candidates",
        "camera.selected_candidate",
        "camera.busy.tool_available",
        "camera.selected.busy_known",
        "camera.selected.busy",
        "camera.opencv.installed",
        "camera.opencv.import_success",
        "camera.opencv.version",
        "camera.opencv.open_test.attempted",
        "camera.opencv.open_test.device",
        "camera.opencv.open_test.success",
        "camera.opencv.frame_test.attempted",
        "camera.opencv.frame_test.success",
        "camera.opencv.frame_test.width",
        "camera.opencv.frame_test.height",
        "camera.opencv.frame_test.channels",
        # USB
        "usb.discovery_available",
        "usb.devices.count",
        "usb.lsusb.tool_available",
        "usb.lsusb.success",
        "usb.lsusb.outcome",
        # Serial
        "serial.discovery_available",
        "serial.devices.count",
        "serial.busy.tool_available",
        "serial.selected_candidate",
        "serial.selected.busy_known",
        "serial.selected.busy",
        "serial.open_test.requested",
        "serial.open_test.attempted",
        "serial.open_test.success",
        "serial.open_test.device",
        # Service: only an already-validated local target reaches these probes.
        "service.target.scheme",
        "service.target.host",
        "service.target.port",
        "service.target.path",
        "service.dns.attempted",
        "service.dns.success",
        "service.dns.addresses",
        "service.tcp.attempted",
        "service.tcp.success",
        "service.tcp.connected_address",
        "service.tcp.error_kind",
        "service.http.attempted",
        "service.http.response_received",
        "service.http.status_code",
        "service.http.reason",
        "service.http.error_kind",
        "service.listener.inspection_available",
        "service.listener.found",
        "service.listener.pid",
        "service.listener.process_name",
    }
)

_STRUCTURED_FIELDS: dict[str, frozenset[str]] = {
    "gpu.nvidia.hardware_devices": frozenset({"pci_address"}),
    "gpu.nvidia.driver.devices": frozenset(
        {
            "index",
            "name",
            "driver_version",
            "memory_total_mib",
            "memory_used_mib",
            "utilization_percent",
            "temperature_celsius",
        }
    ),
    "gpu.pytorch.cuda.devices": frozenset({"index", "name"}),
    "camera.devices": frozenset(
        {
            "path",
            "name",
            "exists",
            "readable",
            "writable",
            "stat_available",
            "mode",
        }
    ),
    "camera.v4l2.inspections": frozenset(
        {
            "path",
            "outcome",
            "return_code",
            "success",
            "driver",
            "card",
            "capture",
            "streaming",
        }
    ),
    "camera.busy.states": frozenset({"path", "busy_known", "busy"}),
    "usb.devices": frozenset(
        {
            "sysfs_name",
            "vendor_id",
            "product_id",
            "manufacturer",
            "product",
            "device_class",
        }
    ),
    "usb.lsusb.devices": frozenset({"vendor_id", "product_id", "description"}),
    "serial.devices": frozenset(
        {
            "path",
            "readable",
            "writable",
            "stat_available",
            "mode",
            "group_name",
            "current_process_in_group",
            "usb",
        }
    ),
    "serial.busy.states": frozenset({"path", "busy_known", "busy"}),
    "service.listener.addresses": frozenset({"address", "port"}),
}
_USB_IDENTITY_FIELDS = frozenset({"vendor_id", "product_id", "manufacturer", "product"})


class EvidenceExportPolicy:
    """Explicit evidence-key and nested-field allowlist."""

    def export(self, evidence: Evidence) -> BundleEvidence | None:
        if evidence.key in _SIMPLE_ALLOWED:
            value = evidence.value
        elif evidence.key in _STRUCTURED_FIELDS:
            value = _filter_records(evidence.value, _STRUCTURED_FIELDS[evidence.key])
            if evidence.key == "serial.devices" and isinstance(value, list):
                value = [
                    {
                        **item,
                        **(
                            {"usb": _filter_mapping(item["usb"], _USB_IDENTITY_FIELDS)}
                            if isinstance(item.get("usb"), dict)
                            else {}
                        ),
                    }
                    for item in value
                ]
        else:
            return None
        return BundleEvidence(
            key=evidence.key,
            availability=evidence.availability,
            value=value
            if evidence.availability is EvidenceAvailability.AVAILABLE
            else None,
        )


class BundleBuilder:
    def __init__(self, policy: EvidenceExportPolicy | None = None) -> None:
        self._policy = policy or EvidenceExportPolicy()

    def from_run(self, run: DiagnosticRun) -> BundlePlan:
        categories = tuple(sorted({result.category for result in run.results}))
        exported: list[BundleEvidence] = []
        omitted: list[str] = []
        for evidence in sorted(run.evidence, key=lambda item: item.key):
            safe = self._policy.export(evidence)
            if safe is None:
                omitted.append(evidence.key)
            else:
                exported.append(safe)
        category_files = tuple(
            BundleCategory(
                category=category,
                evidence=tuple(
                    item for item in exported if _category(item.key) == category
                ),
            )
            for category in categories
            if any(_category(item.key) == category for item in exported)
        )
        return self._plan(
            created_at=run.timestamp,
            source_type="live_diagnosis",
            categories=categories,
            diagnostics=_diagnostics_from_run(run),
            analysis=run.root_cause_analysis,
            category_files=category_files,
            omitted=tuple(sorted(omitted)),
        )

    def from_snapshot(self, snapshot: DiagnosticSnapshot) -> BundlePlan:
        categories = tuple(sorted({item.category for item in snapshot.diagnostics}))
        diagnostics = tuple(
            BundleDiagnostic(
                diagnostic_id=item.diagnostic_id,
                category=item.category,
                status=item.status,
                dependency_state=item.dependency_state,
                result_origin=item.result_origin,
                finding_kind=item.finding_kind,
                summary=item.summary,
                blocked_by=item.blocked_by,
                recommendations=item.recommendations,
                evidence_keys=item.evidence_refs,
            )
            for item in sorted(
                snapshot.diagnostics, key=lambda value: value.diagnostic_id
            )
        )
        return self._plan(
            created_at=snapshot.created_at,
            source_type="snapshot",
            categories=categories,
            diagnostics=diagnostics,
            analysis=snapshot.root_cause_analysis,
            category_files=(),
            omitted=(),
            makermedic_version=snapshot.makermedic_version,
        )

    def _plan(
        self,
        *,
        created_at: datetime,
        source_type: Literal["live_diagnosis", "snapshot"],
        categories: tuple[str, ...],
        diagnostics: tuple[BundleDiagnostic, ...],
        analysis: RootCauseAnalysis | None,
        category_files: tuple[BundleCategory, ...],
        omitted: tuple[str, ...],
        makermedic_version: str = __version__,
    ) -> BundlePlan:
        findings = _findings(analysis)
        inventory = tuple(
            sorted((*CORE_FILES, *(f"{item.category}.json" for item in category_files)))
        )
        manifest = BundleManifest(
            created_at=created_at,
            makermedic_version=makermedic_version,
            included_categories=categories,
            file_inventory=inventory,
            source_type=source_type,
            omitted_evidence_count=len(omitted),
            omitted_evidence_keys=omitted,
        )
        return BundlePlan(
            manifest=manifest,
            diagnostics=diagnostics,
            findings=findings,
            category_files=category_files,
            summary=_summary(manifest, diagnostics, findings),
            exported_evidence=tuple(
                item.key for group in category_files for item in group.evidence
            ),
            omitted_evidence=omitted,
        )


def render_bundle_files(plan: BundlePlan) -> dict[str, bytes]:
    """Render the single validated plan into its exact archive members."""
    files: dict[str, bytes] = {
        "manifest.json": _json_bytes(plan.manifest),
        "diagnostics.json": _json_bytes(list(plan.diagnostics)),
        "findings.json": _json_bytes(list(plan.findings)),
        "summary.txt": plan.summary.encode("utf-8"),
    }
    for category in plan.category_files:
        files[f"{category.category}.json"] = _json_bytes(category)
    if tuple(sorted(files)) != plan.manifest.file_inventory:
        raise ValueError("bundle plan inventory does not match rendered files")
    return files


def export_bundle(plan: BundlePlan, path: Path, *, force: bool = False) -> None:
    """Write a complete same-directory temporary ZIP, then publish atomically."""
    destination = path.expanduser()
    if destination.exists() and not force:
        raise BundleOutputExistsError(f"bundle already exists: {destination}")
    files = render_bundle_files(plan)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
    except OSError as error:
        raise BundleWriteError(f"could not create bundle: {destination}") from error
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name in sorted(files):
                archive.writestr(f"{ARCHIVE_ROOT}/{name}", files[name])
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, destination)
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise BundleOutputExistsError(
                    f"bundle already exists: {destination}"
                ) from error
            temporary.unlink()
    except BundleOutputExistsError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise BundleWriteError(f"could not write bundle: {destination}") from error
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _filter_records(value: JsonValue, fields: frozenset[str]) -> JsonValue:
    if not isinstance(value, list):
        return []
    return [_filter_mapping(item, fields) for item in value if isinstance(item, dict)]


def _filter_mapping(
    value: dict[str, Any], fields: frozenset[str]
) -> dict[str, JsonValue]:
    return {key: item for key, item in value.items() if key in fields}


def _category(key: str) -> str:
    return key.split(".", 1)[0]


def _diagnostics_from_run(run: DiagnosticRun) -> tuple[BundleDiagnostic, ...]:
    return tuple(
        BundleDiagnostic(
            diagnostic_id=item.diagnostic_id,
            category=item.category,
            status=item.status,
            dependency_state=item.dependency_state,
            result_origin=item.origin,
            finding_kind=item.finding_kind,
            summary=item.summary,
            blocked_by=item.blocked_by,
            recommendations=item.recommendations,
            evidence_keys=item.evidence,
        )
        for item in sorted(run.results, key=lambda value: value.diagnostic_id)
    )


def _findings(analysis: RootCauseAnalysis | None) -> tuple[BundleFinding, ...]:
    if analysis is None:
        return ()
    source: tuple[RootFinding, ...] = (
        *analysis.actionable_findings,
        *analysis.unresolved_findings,
        *analysis.optional_absences,
        *analysis.supporting_findings,
    )
    return tuple(
        BundleFinding(
            diagnostic_id=item.diagnostic_id,
            kind=item.kind,
            status=item.status,
            summary=item.summary,
            affected_diagnostics=item.affected_diagnostics,
            recommendations=item.recommendations,
            evidence_refs=item.evidence_refs,
        )
        for item in sorted(source, key=lambda value: value.diagnostic_id)
    )


def _summary(
    manifest: BundleManifest,
    diagnostics: tuple[BundleDiagnostic, ...],
    findings: tuple[BundleFinding, ...],
) -> str:
    counts = Counter(item.status for item in diagnostics)
    lines = [
        "MakerMedic Support Bundle",
        "",
        f"Generated: {manifest.created_at.isoformat()}",
        f"MakerMedic version: {manifest.makermedic_version}",
        f"Categories: {', '.join(manifest.included_categories) or 'none'}",
        "",
        "Diagnostic Summary",
        "------------------",
    ]
    lines.extend(f"{status.value}: {counts[status]}" for status in DiagnosticStatus)
    lines.extend(["", "Root Findings", "-------------"])
    if findings:
        for finding in findings:
            lines.extend(
                ["", finding.kind.value.replace("_", " "), f"- {finding.summary}"]
            )
    else:
        lines.append("None")
    recommendations = tuple(
        dict.fromkeys(
            (
                *(rec for finding in findings for rec in finding.recommendations),
                *(
                    rec
                    for diagnostic in diagnostics
                    for rec in diagnostic.recommendations
                ),
            )
        )
    )
    lines.extend(["", "Recommendations", "---------------"])
    lines.extend(f"- {item}" for item in recommendations)
    if not recommendations:
        lines.append("None")
    if manifest.source_type == "snapshot":
        lines.extend(
            [
                "",
                "Evidence values are absent because this bundle was built "
                "from a snapshot.",
            ]
        )
    return "\n".join(lines) + "\n"


def _json_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = [item.model_dump(mode="json") for item in value]
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
