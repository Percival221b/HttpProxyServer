"""HTTP proxy request parser."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


MAX_HEADER_SIZE = 64 * 1024


class HTTPParseError(ValueError):
    """Raised when a client request cannot be parsed."""


@dataclass
class ProxyRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: bytes = b""

    @property
    def is_connect(self) -> bool:
        return self.method.upper() == "CONNECT"

    @property
    def host(self) -> str:
        if self.is_connect:
            return split_host_port(self.target, default_port=443)[0]

        parsed = urlsplit(self.target)
        if parsed.hostname:
            return parsed.hostname

        host_header = self.headers.get("host", "")
        if not host_header:
            raise HTTPParseError("missing Host header")
        return split_host_port(host_header, default_port=80)[0]

    @property
    def port(self) -> int:
        if self.is_connect:
            return split_host_port(self.target, default_port=443)[1]

        parsed = urlsplit(self.target)
        if parsed.port:
            return parsed.port
        if parsed.scheme == "https":
            return 443

        host_header = self.headers.get("host", "")
        if host_header:
            return split_host_port(host_header, default_port=80)[1]
        return 80

    @property
    def scheme(self) -> str:
        if self.is_connect:
            return "https"
        parsed = urlsplit(self.target)
        return parsed.scheme or "http"

    @property
    def url(self) -> str:
        if self.is_connect:
            return f"https://{self.target}"

        parsed = urlsplit(self.target)
        if parsed.scheme and parsed.netloc:
            return urlunsplit((
                parsed.scheme,
                parsed.netloc,
                parsed.path or "/",
                parsed.query,
                "",
            ))

        host_header = self.headers.get("host")
        if not host_header:
            raise HTTPParseError("missing Host header")
        path = self.target or "/"
        if not path.startswith("/"):
            path = "/" + path
        return f"http://{host_header}{path}"

    @property
    def origin_form_target(self) -> str:
        if self.is_connect:
            return self.target

        parsed = urlsplit(self.target)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            return path
        return self.target or "/"


async def read_http_request(reader) -> ProxyRequest:
    """Read and parse one HTTP request from an asyncio StreamReader."""
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    if len(header_bytes) > MAX_HEADER_SIZE:
        raise HTTPParseError("request headers too large")

    head = header_bytes.decode("iso-8859-1")
    lines = head.split("\r\n")
    if not lines or not lines[0]:
        raise HTTPParseError("empty request line")

    try:
        method, target, version = lines[0].split(" ", 2)
    except ValueError as exc:
        raise HTTPParseError("invalid request line") from exc

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise HTTPParseError(f"invalid header line: {line}")
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", "0") or "0")
    body = await reader.readexactly(content_length) if content_length > 0 else b""
    return ProxyRequest(method=method, target=target, version=version, headers=headers, body=body)


def split_host_port(value: str, default_port: int) -> tuple[str, int]:
    """Split host[:port], including bracketed IPv6 host syntax."""
    value = value.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, default_port

    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        return host, int(port)
    return value, default_port
