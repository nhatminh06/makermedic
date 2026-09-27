import pytest

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence
from makermedic.diagnostics.service import (
    HostResolutionRule,
    HttpHealthRule,
    HttpReachabilityRule,
    ListenerRule,
    TcpConnectivityRule,
)


def store(**values) -> EvidenceStore:
    return EvidenceStore(
        Evidence(key=".".join(key.split("_", 2)), source="test", value=value)
        for key, value in values.items()
    )


def test_resolution_failure_blocks_tcp_and_http() -> None:
    evidence = store(
        service_dns_attempted=True,
        service_dns_success=False,
        service_tcp_success=None,
        service_http_response_received=False,
    )
    assert HostResolutionRule().evaluate(evidence).status is DiagnosticStatus.FAIL
    assert TcpConnectivityRule().evaluate(evidence).status is DiagnosticStatus.UNKNOWN
    assert HttpReachabilityRule().evaluate(evidence).status is DiagnosticStatus.FAIL
    assert HttpHealthRule().evaluate(evidence).status is DiagnosticStatus.UNKNOWN


@pytest.mark.parametrize("kind", ["refused", "timeout", "network_unreachable"])
def test_tcp_failure_is_fail(kind: str) -> None:
    evidence = store(
        service_dns_success=True, service_tcp_success=False, service_tcp_error_kind=kind
    )
    result = TcpConnectivityRule().evaluate(evidence)
    assert result.status is DiagnosticStatus.FAIL
    assert "tcp" in result.summary.casefold()


@pytest.mark.parametrize(
    ("code", "health"),
    [
        (200, DiagnosticStatus.PASS),
        (204, DiagnosticStatus.PASS),
        (302, DiagnosticStatus.WARN),
        (404, DiagnosticStatus.WARN),
        (500, DiagnosticStatus.FAIL),
    ],
)
def test_http_reachability_and_health_are_separate(code, health) -> None:
    evidence = store(
        service_tcp_success=True,
        service_http_response_received=True,
        service_http_status_code=code,
    )
    assert HttpReachabilityRule().evaluate(evidence).status is DiagnosticStatus.PASS
    assert HttpHealthRule().evaluate(evidence).status is health


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "::1", "::"])
def test_listener_bindings_are_pass_not_conflict(address: str) -> None:
    evidence = store(
        service_listener_inspection_available=True,
        service_listener_found=True,
        service_listener_addresses=[{"address": address, "port": 8000}],
        service_tcp_success=True,
    )
    result = ListenerRule().evaluate(evidence)
    assert result.status is DiagnosticStatus.PASS
    assert address in result.summary


def test_absent_listener_warns_without_duplicate_failure() -> None:
    evidence = store(
        service_listener_inspection_available=True,
        service_listener_found=False,
        service_tcp_success=False,
    )
    assert ListenerRule().evaluate(evidence).status is DiagnosticStatus.WARN


def test_listener_unavailable_is_unknown() -> None:
    evidence = store(service_listener_inspection_available=False)
    assert ListenerRule().evaluate(evidence).status is DiagnosticStatus.UNKNOWN
