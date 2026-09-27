"""Validated runtime configuration for local HTTP service diagnostics."""

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ServiceTarget:
    """A normalized, explicitly local HTTP or HTTPS target."""

    scheme: str
    host: str
    port: int
    path: str
    original_url: str

    @classmethod
    def parse(cls, url: str) -> "ServiceTarget":
        """Parse *url*, rejecting malformed, credentialed, and non-local targets."""
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as error:
            raise ValueError(f"invalid service URL: {error}") from error
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise ValueError("service URL scheme must be http or https")
        if not parsed.hostname:
            raise ValueError("service URL must include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("service URL must not contain credentials")
        host = parsed.hostname.casefold()
        if host != "localhost":
            try:
                address = ip_address(host)
            except ValueError as error:
                raise ValueError(
                    "service target must be localhost or a loopback IP"
                ) from error
            if not address.is_loopback:
                raise ValueError("service target must be localhost or a loopback IP")
        if parsed.fragment:
            raise ValueError("service URL must not contain a fragment")
        if parsed.query:
            raise ValueError("service URL must not contain query parameters")
        if port == 0:
            raise ValueError("service URL port must be between 1 and 65535")
        normalized_port = (
            port if port is not None else (443 if scheme == "https" else 80)
        )
        path = parsed.path or "/"
        return cls(scheme, host, normalized_port, path, url)
