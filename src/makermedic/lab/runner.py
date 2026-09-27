"""Scenario execution through the production engine, graph, and analyzer."""

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from makermedic.core.analysis import RootCauseAnalyzer
from makermedic.core.engine import DiagnosticEngine
from makermedic.core.errors import UnknownScenarioError
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    RootCauseAnalysis,
)
from makermedic.lab.fixtures import LabEvidenceProbe, fixture
from makermedic.lab.models import (
    ActualDiagnostic,
    ActualFinding,
    FaultScenario,
    LabReport,
    ScenarioResult,
)
from makermedic.lab.registry import (
    ScenarioRegistry,
    build_rule_registry,
    build_scenario_registry,
)
from makermedic.probes.service import ServiceProbe
from makermedic.service import ServiceTarget

_OVERRIDES: dict[str, dict[str, object]] = {
    "system-low-memory": {"system.memory.available_bytes": 256 * 1024**2},
    "system-memory-warning": {"system.memory.available_bytes": 768 * 1024**2},
    "system-low-disk": {"system.disk.root.free_bytes": 512 * 1024**2},
    "system-disk-warning": {"system.disk.root.free_bytes": 2 * 1024**3},
    "system-non-linux": {"system.os": "FakeOS"},
    "python-old-version": {"python.version_info": [3, 11, 9]},
    "python-no-virtualenv": {"python.in_virtualenv": False, "python.venv.type": "none"},
    "python-pip-path-missing": {"python.pip.path.available": False},
    "python-pip-mismatch": {"python.pip.path.location": "/opt/other-python/pip"},
    "python-package-missing": {
        "python.package.installed": False,
        "python.package.version": None,
    },
    "gpu-hardware-absent": {
        "gpu.nvidia.hardware_detected": False,
        "gpu.nvidia.hardware_count": 0,
    },
    "gpu-driver-unavailable": {"gpu.nvidia.driver.available": False},
    "gpu-nvml-unavailable": {"gpu.nvidia.nvml.available": False},
    "gpu-pytorch-missing": {
        "gpu.pytorch.installed": False,
        "gpu.pytorch.import_success": False,
    },
    "gpu-pytorch-cpu-only": {"gpu.pytorch.cuda.build_version": None},
    "gpu-cuda-hidden": {
        "gpu.pytorch.cuda.available": False,
        "gpu.pytorch.cuda.device_count": 0,
        "gpu.cuda_visible_devices.set": True,
        "gpu.cuda_visible_devices.value": "",
    },
    "gpu-allocation-failure": {"gpu.pytorch.cuda.allocation_test.success": False},
    "gpu-compute-failure": {"gpu.pytorch.cuda.compute_test.success": False},
    "camera-absent": {
        "camera.devices.discovered": False,
        "camera.devices.count": 0,
        "camera.devices": [],
        "camera.selected_candidate": None,
    },
    "camera-permission-denied": {
        "camera.devices": [{"path": "/dev/video-lab", "readable": False}]
    },
    "camera-busy": {
        "camera.selected.busy": True,
        "camera.selected.busy_process_ids": [4242],
    },
    "camera-opencv-missing": {
        "camera.opencv.installed": False,
        "camera.opencv.import_success": False,
    },
    "camera-open-failure": {"camera.opencv.open_test.success": False},
    "camera-frame-failure": {"camera.opencv.frame_test.success": False},
    "camera-healthy": {},
    "usb-none": {"usb.devices.count": 0},
    "usb-lsusb-unavailable": {
        "usb.lsusb.tool_available": False,
        "usb.lsusb.success": None,
    },
    "serial-absent": {
        "serial.devices.count": 0,
        "serial.devices": [],
        "serial.selected_candidate": None,
    },
    "serial-permission-denied": {
        "serial.devices": [
            {
                "path": "/dev/ttyLAB0",
                "readable": False,
                "writable": False,
                "group_name": "dialout",
            }
        ]
    },
    "serial-busy": {
        "serial.selected.busy": True,
        "serial.selected.busy_process_ids": [4242],
    },
    "serial-open-failure": {"serial.open_test.success": False},
    "serial-healthy-no-open": {
        "serial.open_test.requested": False,
        "serial.open_test.attempted": False,
        "serial.open_test.success": None,
    },
    "service-resolution-failure": {
        "service.dns.success": False,
        "service.dns.addresses": [],
        "service.dns.error": "simulated resolution failure",
        "service.tcp.success": False,
        "service.listener.found": False,
        "service.listener.addresses": [],
    },
    "service-connection-refused": {
        "service.tcp.success": False,
        "service.tcp.connected_address": None,
        "service.tcp.error_kind": "refused",
        "service.tcp.error": "simulated refusal",
        "service.listener.found": False,
        "service.listener.addresses": [],
    },
    "service-timeout": {
        "service.tcp.success": False,
        "service.tcp.connected_address": None,
        "service.tcp.error_kind": "timeout",
        "service.tcp.error": "simulated timeout",
        "service.listener.found": False,
        "service.listener.addresses": [],
    },
    "service-http-404": {"service.http.status_code": 404},
    "service-http-500": {"service.http.status_code": 500},
    "service-http-200": {},
}


class LabRunner:
    def __init__(self, registry: ScenarioRegistry | None = None) -> None:
        self.registry = registry or build_scenario_registry()

    def run(self, scenario_id: str) -> ScenarioResult:
        try:
            scenario = self.registry.get(scenario_id)
        except KeyError as error:
            raise UnknownScenarioError(str(error).strip("'")) from error
        if scenario.fixture_id == "service-live-http-500":
            with _live_service(500) as target:
                run = _execute(scenario.category, ServiceProbe(target))
        else:
            values = fixture(scenario.category, _OVERRIDES[scenario.fixture_id])
            probe = LabEvidenceProbe(
                id=f"lab.{scenario.id}", categories=(scenario.category,), values=values
            )
            run = _execute(scenario.category, probe)
        return match_scenario(scenario, run)

    def run_all(self) -> LabReport:
        results = tuple(self.run(item.id) for item in self.registry.all())
        counts = Counter(item.category for item in self.registry.all())
        passed = sum(item.passed for item in results)
        return LabReport(
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            category_counts=dict(sorted(counts.items())),
            scenario_results=results,
        )


def _execute(category: str, probe) -> DiagnosticRun:
    registry = build_rule_registry(category)
    registry.register_probe(probe)
    run = DiagnosticEngine(registry).run(category=category)
    analysis = RootCauseAnalyzer().analyze(run, DiagnosticGraph(registry.rules()))
    return run.model_copy(update={"root_cause_analysis": analysis})


def match_scenario(scenario: FaultScenario, run: DiagnosticRun) -> ScenarioResult:
    """Match stable enum/ID contracts and reject hidden severe regressions."""
    actual_by_id = {item.diagnostic_id: item for item in run.results}
    diagnostic_checks: list[str] = []
    errors: list[str] = []
    expected_ids = {item.diagnostic_id for item in scenario.expected_diagnostics}
    for expected in scenario.expected_diagnostics:
        actual = actual_by_id.get(expected.diagnostic_id)
        if actual is None:
            errors.append(f"missing diagnostic: {expected.diagnostic_id}")
            continue
        fields = (
            ("status", expected.status, actual.status),
            ("dependency_state", expected.dependency_state, actual.dependency_state),
            ("result_origin", expected.result_origin, actual.origin),
            ("blocked_by", expected.blocked_by, actual.blocked_by),
        )
        mismatched = False
        for name, wanted, observed in fields:
            if wanted is not None and wanted != observed:
                mismatched = True
                errors.append(
                    f"{expected.diagnostic_id} {name}: "
                    f"expected {wanted}, actual {observed}"
                )
        if not mismatched:
            diagnostic_checks.append(expected.diagnostic_id)

    unexpected_diagnostics = tuple(
        item.diagnostic_id
        for item in run.results
        if item.diagnostic_id not in expected_ids
        and item.status in {DiagnosticStatus.FAIL, DiagnosticStatus.UNKNOWN}
    )
    errors.extend(
        f"unexpected {actual_by_id[item].status}: {item}"
        for item in unexpected_diagnostics
    )

    analysis = run.root_cause_analysis or RootCauseAnalysis(healthy_count=0)
    findings = (
        *analysis.actionable_findings,
        *analysis.unresolved_findings,
        *analysis.optional_absences,
        *analysis.supporting_findings,
    )
    finding_by_id = {item.diagnostic_id: item for item in findings}
    finding_checks: list[str] = []
    expected_finding_ids = {item.diagnostic_id for item in scenario.expected_findings}
    for expected in scenario.expected_findings:
        actual = finding_by_id.get(expected.diagnostic_id)
        if actual is None:
            errors.append(f"missing root finding: {expected.diagnostic_id}")
            continue
        mismatched = False
        if expected.kind is not None and expected.kind is not actual.kind:
            mismatched = True
            errors.append(
                f"{expected.diagnostic_id} finding kind: "
                f"expected {expected.kind}, actual {actual.kind}"
            )
        if (
            expected.affected_diagnostics is not None
            and expected.affected_diagnostics != actual.affected_diagnostics
        ):
            mismatched = True
            errors.append(f"{expected.diagnostic_id} affected diagnostics differ")
        if not mismatched:
            finding_checks.append(expected.diagnostic_id)
    unexpected_findings = tuple(
        item.diagnostic_id
        for item in findings
        if item.diagnostic_id not in expected_finding_ids
        and item.kind
        in {FindingKind.FAILURE, FindingKind.MISSING_CAPABILITY, FindingKind.UNCERTAIN}
    )
    errors.extend(
        f"unexpected actionable finding: {item}" for item in unexpected_findings
    )
    actual_exit = int(any(item.status is DiagnosticStatus.FAIL for item in run.results))
    if actual_exit != scenario.expected_exit_code:
        errors.append(
            f"diagnostic exit: expected {scenario.expected_exit_code}, "
            f"actual {actual_exit}"
        )
    return ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        safety_level=scenario.safety_level,
        passed=not errors,
        expected_diagnostics=scenario.expected_diagnostics,
        expected_findings=scenario.expected_findings,
        actual_diagnostics=tuple(
            ActualDiagnostic(
                diagnostic_id=item.diagnostic_id,
                status=item.status,
                dependency_state=item.dependency_state,
                result_origin=item.origin,
                blocked_by=item.blocked_by,
            )
            for item in run.results
        ),
        actual_findings=tuple(
            ActualFinding(
                diagnostic_id=item.diagnostic_id,
                kind=item.kind,
                affected_diagnostics=item.affected_diagnostics,
            )
            for item in findings
        ),
        diagnostic_checks=tuple(diagnostic_checks),
        finding_checks=tuple(finding_checks),
        unexpected_diagnostics=unexpected_diagnostics,
        unexpected_findings=unexpected_findings,
        errors=tuple(errors),
        expected_exit_code=scenario.expected_exit_code,
        actual_exit_code=actual_exit,
    )


class _StatusHandler(BaseHTTPRequestHandler):
    status = 500

    def do_GET(self) -> None:
        self.send_response(self.status)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _live_service(status: int) -> Iterator[ServiceTarget]:
    handler = type("LabStatusHandler", (_StatusHandler,), {"status": status})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, name="makermedic-lab-http")
    thread.start()
    try:
        port = server.server_port
        yield ServiceTarget.parse(f"http://127.0.0.1:{port}/health")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
