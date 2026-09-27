"""Deterministic interpretation of local service evidence."""

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


class ServiceTargetRule:
    id = "service.target"
    category = "service"
    dependencies = ()
    required_evidence = frozenset({"service.target.url"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        url = _value(evidence, "service.target.url", str)
        return (
            _result(self, DiagnosticStatus.PASS, f"Local service target: {url}")
            if url
            else _result(
                self, DiagnosticStatus.UNKNOWN, "Service target is unavailable"
            )
        )


class HostResolutionRule:
    id = "service.host_resolution"
    category = "service"
    dependencies = ("service.target",)
    required_evidence = frozenset(
        {
            "service.dns.attempted",
            "service.dns.success",
            "service.dns.addresses",
            "service.dns.error",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        attempted = _value(evidence, "service.dns.attempted", bool)
        success = _value(evidence, "service.dns.success", bool)
        addresses = _value(evidence, "service.dns.addresses", list)
        error = _value(evidence, "service.dns.error", str)
        if attempted is not True:
            return _result(
                self, DiagnosticStatus.UNKNOWN, "Host resolution was not attempted"
            )
        if success:
            return _result(
                self,
                DiagnosticStatus.PASS,
                f"Host resolved: {', '.join(addresses or [])}",
            )
        return _result(
            self,
            DiagnosticStatus.FAIL,
            "Host resolution failed",
            causes=(error,) if error else (),
        )


class TcpConnectivityRule:
    id = "service.tcp_connectivity"
    category = "service"
    dependencies = ("service.host_resolution",)
    required_evidence = frozenset(
        {
            "service.dns.success",
            "service.tcp.attempted",
            "service.tcp.success",
            "service.tcp.connected_address",
            "service.tcp.error_kind",
            "service.tcp.error",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        success = _value(evidence, "service.tcp.success", bool)
        kind = _value(evidence, "service.tcp.error_kind", str)
        error = _value(evidence, "service.tcp.error", str)
        if success:
            address = _value(evidence, "service.tcp.connected_address", str)
            return _result(
                self, DiagnosticStatus.PASS, f"TCP connection succeeded ({address})"
            )
        summaries = {
            "refused": "TCP connection was refused",
            "timeout": "TCP connection timed out",
            "network_unreachable": "TCP network was unreachable",
            "permission_error": "TCP connection was denied by the operating system",
        }
        if success is False:
            return _result(
                self,
                DiagnosticStatus.FAIL,
                summaries.get(kind, "TCP connection failed"),
                causes=(error,) if error else (),
            )
        return _result(self, DiagnosticStatus.UNKNOWN, "TCP connectivity is unknown")


class HttpReachabilityRule:
    id = "service.http_reachability"
    category = "service"
    dependencies = ("service.tcp_connectivity",)
    required_evidence = frozenset(
        {
            "service.tcp.success",
            "service.http.attempted",
            "service.http.response_received",
            "service.http.status_code",
            "service.http.error_kind",
            "service.http.error",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        if _value(evidence, "service.http.response_received", bool):
            status = _number(evidence, "service.http.status_code")
            return _result(
                self, DiagnosticStatus.PASS, f"HTTP server responded ({status})"
            )
        error = _value(evidence, "service.http.error", str)
        return _result(
            self,
            DiagnosticStatus.FAIL,
            "HTTP request failed after TCP connected",
            causes=(error,) if error else (),
        )


class HttpHealthRule:
    id = "service.http_health"
    category = "service"
    dependencies = ("service.http_reachability",)
    required_evidence = frozenset(
        {"service.http.response_received", "service.http.status_code"}
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        status = _number(evidence, "service.http.status_code")
        if status is None:
            return _result(
                self, DiagnosticStatus.UNKNOWN, "HTTP response status is unavailable"
            )
        if 200 <= status < 300:
            return _result(
                self, DiagnosticStatus.PASS, f"HTTP health status is {status}"
            )
        if 300 <= status < 500:
            return _result(
                self,
                DiagnosticStatus.WARN,
                f"HTTP endpoint returned status {status}",
                warning_state=DependencyState.SATISFIED,
            )
        if 500 <= status < 600:
            return _result(
                self,
                DiagnosticStatus.FAIL,
                f"HTTP endpoint reported server error {status}",
            )
        return _result(
            self,
            DiagnosticStatus.WARN,
            f"HTTP endpoint returned unusual status {status}",
            warning_state=DependencyState.SATISFIED,
        )


class ListenerRule:
    id = "service.listener"
    category = "service"
    dependencies = ("service.target",)
    required_evidence = frozenset(
        {
            "service.listener.inspection_available",
            "service.listener.found",
            "service.listener.addresses",
            "service.listener.pid",
            "service.listener.process_name",
            "service.tcp.success",
            "service.tcp.error_kind",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        if _value(evidence, "service.listener.inspection_available", bool) is not True:
            return _result(
                self,
                DiagnosticStatus.UNKNOWN,
                "Local listener inspection is unavailable",
            )
        found = _value(evidence, "service.listener.found", bool)
        if found:
            addresses = _value(evidence, "service.listener.addresses", list) or []
            bindings = ", ".join(
                f"{item['address']}:{item['port']}" for item in addresses
            )
            process = _value(evidence, "service.listener.process_name", str)
            pid = _number(evidence, "service.listener.pid")
            owner = f"; {process} (PID {pid})" if process and pid is not None else ""
            return _result(
                self,
                DiagnosticStatus.PASS,
                f"Local listener found ({bindings}){owner}",
            )
        if _value(evidence, "service.tcp.success", bool) is True:
            return _result(
                self,
                DiagnosticStatus.UNKNOWN,
                "Listener inspection disagrees with successful TCP connection",
            )
        return _result(
            self,
            DiagnosticStatus.WARN,
            "No local listener detected on the target port",
            finding_kind=FindingKind.SUPPORTING,
        )


def _result(
    rule: Any,
    status: DiagnosticStatus,
    summary: str,
    *,
    causes: tuple[str, ...] = (),
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
