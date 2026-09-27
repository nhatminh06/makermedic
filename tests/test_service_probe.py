import errno
import socket
import ssl
from pathlib import Path
from urllib.error import URLError

import pytest

from makermedic.probes.service import ServiceProbe, inspect_local_listener
from makermedic.service import ServiceTarget


class FakeSocket:
    def __init__(self, outcome=None) -> None:
        self.outcome = outcome
        self.closed = False
        self.destination = None

    def settimeout(self, timeout) -> None:
        self.timeout = timeout

    def connect(self, destination) -> None:
        self.destination = destination
        if self.outcome:
            raise self.outcome

    def close(self) -> None:
        self.closed = True


class SocketFactory:
    def __init__(self, outcomes) -> None:
        self.outcomes = iter(outcomes)
        self.sockets = []

    def __call__(self, *_args):
        value = FakeSocket(next(self.outcomes))
        self.sockets.append(value)
        return value


class FakeResponse:
    def __init__(self, status=200, reason="OK", body=b"response") -> None:
        self.status = status
        self.reason = reason
        self.body = body
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class FakeOpener:
    def __init__(self, value) -> None:
        self.value = value
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def resolver(*addresses):
    return lambda *_args: [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 8000, 0, 0) if ":" in address else (address, 8000),
        )
        for address in addresses
    ]


def collect(
    *,
    resolver_fn=None,
    sockets=None,
    http=None,
    listener=None,
    url="http://localhost:8000/health",
):
    probe = ServiceProbe(
        ServiceTarget.parse(url),
        resolver=resolver_fn or resolver("127.0.0.1"),
        socket_factory=sockets or SocketFactory([None]),
        opener=http or FakeOpener(FakeResponse()),
        listener_inspector=listener
        or (
            lambda _port: {
                "available": True,
                "addresses": [],
                "pid": None,
                "process_name": None,
            }
        ),
    )
    return {item.key: item for item in probe.collect()}


def test_resolution_multiple_ipv4_ipv6_and_successful_fallback() -> None:
    sockets = SocketFactory([OSError(errno.ECONNREFUSED, "refused"), None])
    evidence = collect(resolver_fn=resolver("::1", "127.0.0.1"), sockets=sockets)
    assert evidence["service.dns.addresses"].value == ["::1", "127.0.0.1"]
    assert evidence["service.tcp.success"].value is True
    assert evidence["service.tcp.connected_address"].value == "127.0.0.1"
    assert all(item.closed for item in sockets.sockets)


def test_resolution_failure_blocks_connections() -> None:
    def fail(*_args):
        raise socket.gaierror(-2, "not known")

    sockets = SocketFactory([])
    evidence = collect(resolver_fn=fail, sockets=sockets)
    assert evidence["service.dns.success"].value is False
    assert evidence["service.tcp.attempted"].value is False
    assert evidence["service.tcp.error_kind"].value == "resolution_error"
    assert evidence["service.http.attempted"].value is False
    assert sockets.sockets == []


def test_localhost_resolving_outside_loopback_is_rejected() -> None:
    evidence = collect(resolver_fn=resolver("203.0.113.10"), sockets=SocketFactory([]))
    assert evidence["service.dns.success"].value is False
    assert "non-loopback" in evidence["service.dns.error"].value
    assert evidence["service.tcp.attempted"].value is False


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "refused"), "refused"),
        (TimeoutError(errno.ETIMEDOUT, "timed out"), "timeout"),
        (OSError(errno.ENETUNREACH, "unreachable"), "network_unreachable"),
        (PermissionError(errno.EACCES, "denied"), "permission_error"),
        (OSError(errno.EIO, "other"), "other"),
    ],
)
def test_tcp_failures_are_classified_and_socket_closed(error, kind) -> None:
    sockets = SocketFactory([error])
    evidence = collect(sockets=sockets)
    assert evidence["service.tcp.success"].value is False
    assert evidence["service.tcp.error_kind"].value == kind
    assert sockets.sockets[0].closed is True
    assert evidence["service.http.attempted"].value is False


@pytest.mark.parametrize("status", [200, 204, 301, 302, 404, 500])
def test_http_response_status_and_bounded_read(status: int) -> None:
    response = FakeResponse(status=status)
    opener = FakeOpener(response)
    evidence = collect(http=opener)
    assert evidence["service.http.response_received"].value is True
    assert evidence["service.http.status_code"].value == status
    assert response.read_sizes == [1]
    request = opener.calls[0][0]
    assert request.get_method() == "GET"
    assert request.header_items() == []


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (URLError(TimeoutError("timed out")), "timeout"),
        (
            URLError(ssl.SSLCertVerificationError("bad certificate")),
            "tls_validation_error",
        ),
        (URLError("protocol failed"), "protocol_error"),
    ],
)
def test_http_failures_are_classified(error, kind) -> None:
    evidence = collect(http=FakeOpener(error))
    assert evidence["service.http.response_received"].value is False
    assert evidence["service.http.error_kind"].value == kind


def test_literal_loopback_does_not_use_dns() -> None:
    def unexpected(*_args):
        raise AssertionError("resolver called")

    evidence = collect(url="http://127.0.0.1:8000", resolver_fn=unexpected)
    assert evidence["service.dns.addresses"].value == ["127.0.0.1"]


def test_listener_evidence_has_minimal_fields() -> None:
    evidence = collect(
        listener=lambda _port: {
            "available": True,
            "addresses": [{"address": "0.0.0.0", "port": 8000}],
            "pid": 12,
            "process_name": "python",
        }
    )
    assert evidence["service.listener.found"].value is True
    assert evidence["service.listener.pid"].value == 12
    assert evidence["service.listener.process_name"].value == "python"
    assert "command" not in str(evidence["service.listener.addresses"].value)


def test_proc_listener_inspection_ipv4_and_owner(tmp_path: Path) -> None:
    (tmp_path / "net").mkdir()
    header = "sl local_address rem_address st tx rx tr tm retr uid timeout inode\n"
    row = " 0: 0100007F:1F40 00000000:0000 0A 0:0 0:0 00:0 0 0 4242\n"
    (tmp_path / "net/tcp").write_text(header + row)
    (tmp_path / "net/tcp6").write_text(header)
    process = tmp_path / "123" / "fd"
    process.mkdir(parents=True)
    (tmp_path / "123/comm").write_text("python\n")
    (process / "4").symlink_to("socket:[4242]")
    result = inspect_local_listener(8000, proc_root=tmp_path)
    assert result == {
        "available": True,
        "addresses": [{"address": "127.0.0.1", "port": 8000}],
        "pid": 123,
        "process_name": "python",
    }


def test_proc_listener_inspection_ipv4_wildcard_and_ipv6(tmp_path: Path) -> None:
    (tmp_path / "net").mkdir()
    header = "sl local_address rem_address st tx rx tr tm retr uid timeout inode\n"
    (tmp_path / "net/tcp").write_text(
        header + " 0: 00000000:1F40 00000000:0000 0A 0:0 0:0 00:0 0 0 1\n"
    )
    (tmp_path / "net/tcp6").write_text(
        header + " 0: 00000000000000000000000001000000:1F40 "
        "00000000000000000000000000000000:0000 0A 0:0 0:0 00:0 0 0 2\n"
    )
    result = inspect_local_listener(8000, proc_root=tmp_path)
    assert result["addresses"] == [
        {"address": "0.0.0.0", "port": 8000},
        {"address": "::1", "port": 8000},
    ]
    assert result["pid"] is None
    assert result["process_name"] is None


def test_listener_inspection_unavailable(tmp_path: Path) -> None:
    result = inspect_local_listener(8000, proc_root=tmp_path)
    assert result["available"] is False
    assert result["addresses"] == []
