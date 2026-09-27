import pytest

from makermedic.service import ServiceTarget


@pytest.mark.parametrize(
    ("url", "scheme", "host", "port", "path"),
    [
        ("http://localhost/health", "http", "localhost", 80, "/health"),
        ("https://localhost", "https", "localhost", 443, "/"),
        ("http://127.0.0.1:8080/a", "http", "127.0.0.1", 8080, "/a"),
        ("http://[::1]:9000/health", "http", "::1", 9000, "/health"),
        ("http://127.2.3.4", "http", "127.2.3.4", 80, "/"),
    ],
)
def test_valid_service_targets(url, scheme, host, port, path) -> None:
    target = ServiceTarget.parse(url)
    assert (target.scheme, target.host, target.port, target.path) == (
        scheme,
        host,
        port,
        path,
    )
    assert target.original_url == url


@pytest.mark.parametrize(
    "url",
    [
        "localhost:8000",
        "ftp://localhost/a",
        "http://",
        "http://example.com",
        "http://192.168.1.2",
        "http://8.8.8.8",
        "http://user:secret@localhost/",
        "http://localhost:99999",
        "http://localhost:0",
        "http://localhost/#fragment",
        "http://localhost/?token=secret",
    ],
)
def test_invalid_or_unsafe_service_targets(url: str) -> None:
    with pytest.raises(ValueError):
        ServiceTarget.parse(url)
