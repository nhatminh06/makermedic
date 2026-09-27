from datetime import UTC, datetime

from makermedic.composition import build_default_registry
from makermedic.core.analysis import RootCauseAnalyzer
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
)
from makermedic.service import ServiceTarget


def diagnostic(
    diagnostic_id: str,
    category: str,
    status: DiagnosticStatus,
    *,
    state: DependencyState | None = None,
    kind: FindingKind | None = None,
    blocked_by: tuple[str, ...] = (),
) -> DiagnosticResult:
    return DiagnosticResult(
        diagnostic_id=diagnostic_id,
        category=category,
        status=status,
        dependency_state=state,
        finding_kind=kind,
        origin=ResultOrigin.DEPENDENCY_BLOCKED
        if blocked_by
        else ResultOrigin.EVALUATED,
        summary=diagnostic_id,
        blocked_by=blocked_by,
    )


def analyze(results, *, service=False):
    registry = build_default_registry(
        service_target=ServiceTarget.parse("http://localhost:8000/health")
        if service
        else None
    )
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=tuple(results),
    )
    return RootCauseAnalyzer().analyze(run, DiagnosticGraph(registry.rules()))


def test_gpu_fixture_reduces_to_driver_and_pytorch_findings() -> None:
    analysis = analyze(
        (
            diagnostic("gpu.nvidia.hardware", "gpu", DiagnosticStatus.PASS),
            diagnostic("gpu.nvidia.driver", "gpu", DiagnosticStatus.FAIL),
            diagnostic(
                "gpu.nvidia.nvml",
                "gpu",
                DiagnosticStatus.BLOCKED,
                blocked_by=("gpu.nvidia.driver",),
            ),
            diagnostic(
                "gpu.pytorch.installation",
                "gpu",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.MISSING_CAPABILITY,
            ),
            diagnostic(
                "gpu.pytorch.cuda_build",
                "gpu",
                DiagnosticStatus.BLOCKED,
                blocked_by=("gpu.pytorch.installation",),
            ),
            diagnostic(
                "gpu.pytorch.cuda_visibility",
                "gpu",
                DiagnosticStatus.BLOCKED,
                blocked_by=("gpu.nvidia.driver", "gpu.pytorch.cuda_build"),
            ),
            diagnostic(
                "gpu.pytorch.cuda_allocation",
                "gpu",
                DiagnosticStatus.BLOCKED,
                blocked_by=("gpu.pytorch.cuda_visibility",),
            ),
            diagnostic(
                "gpu.pytorch.cuda_compute",
                "gpu",
                DiagnosticStatus.BLOCKED,
                blocked_by=("gpu.pytorch.cuda_allocation",),
            ),
        )
    )
    assert [item.diagnostic_id for item in analysis.actionable_findings] == [
        "gpu.nvidia.driver",
        "gpu.pytorch.installation",
    ]
    assert analysis.actionable_findings[0].affected_diagnostics == (
        "gpu.nvidia.nvml",
        "gpu.pytorch.cuda_visibility",
        "gpu.pytorch.cuda_allocation",
        "gpu.pytorch.cuda_compute",
    )
    assert analysis.actionable_findings[1].affected_diagnostics == (
        "gpu.pytorch.cuda_build",
        "gpu.pytorch.cuda_visibility",
        "gpu.pytorch.cuda_allocation",
        "gpu.pytorch.cuda_compute",
    )


def test_camera_and_serial_absence_are_optional_findings() -> None:
    camera = analyze(
        (
            diagnostic(
                "camera.presence",
                "camera",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.OPTIONAL_ABSENCE,
            ),
            diagnostic(
                "camera.permissions",
                "camera",
                DiagnosticStatus.BLOCKED,
                blocked_by=("camera.presence",),
            ),
            diagnostic(
                "camera.busy",
                "camera",
                DiagnosticStatus.BLOCKED,
                blocked_by=("camera.presence",),
            ),
        )
    )
    serial = analyze(
        (
            diagnostic(
                "serial.presence",
                "serial",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.OPTIONAL_ABSENCE,
            ),
            diagnostic(
                "serial.permissions",
                "serial",
                DiagnosticStatus.BLOCKED,
                blocked_by=("serial.presence",),
            ),
            diagnostic(
                "serial.busy",
                "serial",
                DiagnosticStatus.BLOCKED,
                blocked_by=("serial.presence",),
            ),
            diagnostic(
                "serial.open",
                "serial",
                DiagnosticStatus.BLOCKED,
                blocked_by=("serial.permissions", "serial.busy"),
            ),
        )
    )
    assert [item.diagnostic_id for item in camera.optional_absences] == [
        "camera.presence"
    ]
    assert [item.diagnostic_id for item in serial.optional_absences] == [
        "serial.presence"
    ]


def test_service_http_200_has_no_findings_and_500_has_health_failure() -> None:
    satisfied = (
        "service.target",
        "service.host_resolution",
        "service.tcp_connectivity",
        "service.http_reachability",
        "service.listener",
    )
    healthy = analyze(
        tuple(diagnostic(item, "service", DiagnosticStatus.PASS) for item in satisfied)
        + (diagnostic("service.http_health", "service", DiagnosticStatus.PASS),),
        service=True,
    )
    failed = analyze(
        tuple(diagnostic(item, "service", DiagnosticStatus.PASS) for item in satisfied)
        + (diagnostic("service.http_health", "service", DiagnosticStatus.FAIL),),
        service=True,
    )
    assert healthy.actionable_findings == ()
    assert [item.diagnostic_id for item in failed.actionable_findings] == [
        "service.http_health"
    ]


def test_connection_refused_is_primary_and_listener_is_supporting() -> None:
    analysis = analyze(
        (
            diagnostic("service.target", "service", DiagnosticStatus.PASS),
            diagnostic("service.host_resolution", "service", DiagnosticStatus.PASS),
            diagnostic("service.tcp_connectivity", "service", DiagnosticStatus.FAIL),
            diagnostic(
                "service.http_reachability",
                "service",
                DiagnosticStatus.BLOCKED,
                blocked_by=("service.tcp_connectivity",),
            ),
            diagnostic(
                "service.http_health",
                "service",
                DiagnosticStatus.BLOCKED,
                blocked_by=("service.http_reachability",),
            ),
            diagnostic(
                "service.listener",
                "service",
                DiagnosticStatus.WARN,
                state=DependencyState.UNSATISFIED,
                kind=FindingKind.SUPPORTING,
            ),
        ),
        service=True,
    )
    assert [item.diagnostic_id for item in analysis.actionable_findings] == [
        "service.tcp_connectivity"
    ]
    assert [item.diagnostic_id for item in analysis.supporting_findings] == [
        "service.listener"
    ]
