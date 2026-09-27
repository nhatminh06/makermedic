"""Bounded evidence collection for one explicitly configured local service."""

import errno
import os
import socket
import ssl
import time
from collections.abc import Callable, Iterable, Sequence
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from makermedic.core.models import Evidence, EvidenceAvailability
from makermedic.service import ServiceTarget

CONNECT_TIMEOUT = 2.0
HTTP_TIMEOUT = 3.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class ServiceProbe:
    """Resolve, connect to, request, and inspect one local service target."""

    id = "service.local"
    categories = ("service",)

    def __init__(
        self,
        target: ServiceTarget,
        *,
        resolver: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
        socket_factory: Callable[..., Any] = socket.socket,
        opener: Any | None = None,
        listener_inspector: Callable[[int], dict[str, Any]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._target = target
        self._resolver = resolver
        self._socket_factory = socket_factory
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        self._listener_inspector = listener_inspector or inspect_local_listener
        self._monotonic = monotonic

    def collect(self) -> Iterable[Evidence]:
        evidence = list(self._target_evidence())
        addresses, resolution_error = self._resolve()
        evidence.extend(
            (
                Evidence(key="service.dns.attempted", source=self.id, value=True),
                Evidence(
                    key="service.dns.success",
                    source=self.id,
                    value=resolution_error is None,
                ),
                Evidence(key="service.dns.addresses", source=self.id, value=addresses),
                _optional("service.dns.error", self.id, resolution_error),
            )
        )
        tcp = (
            self._connect(addresses)
            if resolution_error is None
            else {
                "attempted": False,
                "success": None,
                "address": None,
                "error_kind": "resolution_error",
                "error": resolution_error,
            }
        )
        evidence.extend(_tcp_evidence(self.id, tcp))
        http = self._request() if tcp["success"] is True else _blocked_http()
        evidence.extend(_http_evidence(self.id, http))
        try:
            listener = self._listener_inspector(self._target.port)
        except OSError:
            listener = {
                "available": False,
                "addresses": [],
                "pid": None,
                "process_name": None,
            }
        evidence.extend(_listener_evidence(self.id, listener))
        return tuple(evidence)

    def _target_evidence(self) -> tuple[Evidence, ...]:
        target = self._target
        return tuple(
            Evidence(key=key, source=self.id, value=value)
            for key, value in (
                ("service.target.url", target.original_url),
                ("service.target.scheme", target.scheme),
                ("service.target.host", target.host),
                ("service.target.port", target.port),
                ("service.target.path", target.path),
            )
        )

    def _resolve(self) -> tuple[list[str], str | None]:
        if self._target.host != "localhost":
            return [self._target.host], None
        try:
            records = self._resolver(
                self._target.host,
                self._target.port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            return [], _error_text(error)
        addresses: list[str] = []
        for record in records:
            address = str(record[4][0])
            try:
                is_loopback = ip_address(address).is_loopback
            except ValueError:
                is_loopback = False
            if not is_loopback:
                return [], "localhost resolved to a non-loopback address"
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            return [], "host resolution returned no addresses"
        return addresses, None

    def _connect(self, addresses: list[str]) -> dict[str, object | None]:
        failures: list[tuple[str, str]] = []
        deadline = self._monotonic() + CONNECT_TIMEOUT
        for address in addresses:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                failures.append(("timeout", "overall TCP connection timeout expired"))
                break
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            connection = self._socket_factory(family, socket.SOCK_STREAM)
            try:
                connection.settimeout(remaining)
                destination = (
                    (address, self._target.port, 0, 0)
                    if family == socket.AF_INET6
                    else (address, self._target.port)
                )
                connection.connect(destination)
            except OSError as error:
                failures.append((_socket_error_kind(error), _error_text(error)))
            else:
                return {
                    "attempted": True,
                    "success": True,
                    "address": address,
                    "error_kind": None,
                    "error": None,
                }
            finally:
                connection.close()
        kind, message = failures[-1] if failures else ("other", "no address available")
        return {
            "attempted": bool(addresses),
            "success": False,
            "address": None,
            "error_kind": kind,
            "error": message,
        }

    def _request(self) -> dict[str, object | None]:
        request = Request(self._target.original_url, method="GET")
        try:
            response = self._opener.open(request, timeout=HTTP_TIMEOUT)
            with response:
                response.read(1)
                return _http_response(response.status, response.reason)
        except HTTPError as error:
            error.read(1)
            error.close()
            return _http_response(error.code, error.reason)
        except Exception as error:  # narrow urllib/TLS boundary
            return {
                "attempted": True,
                "response_received": False,
                "status_code": None,
                "reason": None,
                "error_kind": _http_error_kind(error),
                "error": _error_text(error),
            }


def inspect_local_listener(
    port: int, *, proc_root: Path = Path("/proc")
) -> dict[str, Any]:
    """Inspect only *port* in Linux procfs and return minimal ownership data."""
    listeners: list[dict[str, object]] = []
    readable = False
    for name, family in (("net/tcp", socket.AF_INET), ("net/tcp6", socket.AF_INET6)):
        try:
            lines = proc_root.joinpath(name).read_text().splitlines()[1:]
        except OSError:
            continue
        readable = True
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            encoded, encoded_port = fields[1].split(":")
            if int(encoded_port, 16) != port:
                continue
            address = _decode_proc_address(encoded, family)
            listeners.append({"address": address, "port": port, "inode": fields[9]})
    pid, process_name = _find_owner(
        proc_root, {str(item["inode"]) for item in listeners}
    )
    addresses = [{"address": item["address"], "port": port} for item in listeners]
    return {
        "available": readable,
        "addresses": addresses,
        "pid": pid,
        "process_name": process_name,
    }


def _find_owner(root: Path, inodes: set[str]) -> tuple[int | None, str | None]:
    if not inodes:
        return None, None
    try:
        processes = sorted(
            (item for item in root.iterdir() if item.name.isdigit()),
            key=lambda p: int(p.name),
        )
    except OSError:
        return None, None
    targets = {f"socket:[{inode}]" for inode in inodes}
    for process in processes:
        try:
            links = process.joinpath("fd").iterdir()
            if not any(os.readlink(link) in targets for link in links):
                continue
            name = process.joinpath("comm").read_text().strip() or None
            return int(process.name), name
        except OSError:
            continue
    return None, None


def _decode_proc_address(encoded: str, family: socket.AddressFamily) -> str:
    raw = bytes.fromhex(encoded)
    if family == socket.AF_INET:
        raw = raw[::-1]
    else:
        raw = b"".join(raw[index : index + 4][::-1] for index in range(0, 16, 4))
    return socket.inet_ntop(family, raw)


def _socket_error_kind(error: OSError) -> str:
    if isinstance(error, TimeoutError) or error.errno == errno.ETIMEDOUT:
        return "timeout"
    if error.errno == errno.ECONNREFUSED:
        return "refused"
    if error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH}:
        return "network_unreachable"
    if error.errno in {errno.EACCES, errno.EPERM}:
        return "permission_error"
    return "other"


def _http_error_kind(error: Exception) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "tls_validation_error"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    return "protocol_error"


def _http_response(status: int, reason: str | None) -> dict[str, object | None]:
    return {
        "attempted": True,
        "response_received": True,
        "status_code": status,
        "reason": reason,
        "error_kind": None,
        "error": None,
    }


def _blocked_http() -> dict[str, object | None]:
    return {
        "attempted": False,
        "response_received": False,
        "status_code": None,
        "reason": None,
        "error_kind": None,
        "error": None,
    }


def _tcp_evidence(
    source: str, values: dict[str, object | None]
) -> tuple[Evidence, ...]:
    return (
        Evidence(key="service.tcp.attempted", source=source, value=values["attempted"]),
        _optional("service.tcp.success", source, values["success"]),
        _optional("service.tcp.connected_address", source, values["address"]),
        _optional("service.tcp.error_kind", source, values["error_kind"]),
        _optional("service.tcp.error", source, values["error"]),
    )


def _http_evidence(
    source: str, values: dict[str, object | None]
) -> tuple[Evidence, ...]:
    return (
        Evidence(
            key="service.http.attempted", source=source, value=values["attempted"]
        ),
        Evidence(
            key="service.http.response_received",
            source=source,
            value=values["response_received"],
        ),
        _optional("service.http.status_code", source, values["status_code"]),
        _optional("service.http.reason", source, values["reason"]),
        _optional("service.http.error_kind", source, values["error_kind"]),
        _optional("service.http.error", source, values["error"]),
    )


def _listener_evidence(source: str, values: dict[str, Any]) -> tuple[Evidence, ...]:
    addresses = values.get("addresses", [])
    return (
        Evidence(
            key="service.listener.inspection_available",
            source=source,
            value=bool(values.get("available")),
        ),
        Evidence(key="service.listener.found", source=source, value=bool(addresses)),
        Evidence(key="service.listener.addresses", source=source, value=addresses),
        _optional("service.listener.pid", source, values.get("pid")),
        _optional("service.listener.process_name", source, values.get("process_name")),
    )


def _optional(key: str, source: str, value: Any) -> Evidence:
    return Evidence(
        key=key,
        source=source,
        value=value,
        availability=EvidenceAvailability.AVAILABLE
        if value is not None
        else EvidenceAvailability.UNAVAILABLE,
    )


def _error_text(error: BaseException) -> str:
    return str(error).strip() or type(error).__name__
