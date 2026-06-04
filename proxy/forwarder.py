"""Forward parsed HTTP requests to upstream origin servers."""

from __future__ import annotations

from dataclasses import dataclass

from proxy.parser import ProxyRequest


HOP_BY_HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
}


@dataclass
class ForwardedResponse:
    raw: bytes
    status_code: int
    headers: dict[str, str]

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def body_size(self) -> int:
        return len(self.body)

    @property
    def body(self) -> bytes:
        separator = self.raw.find(b"\r\n\r\n")
        if separator == -1:
            return b""
        return self.raw[separator + 4:]


class HTTPForwarder:
    """Simple HTTP/1.0 forwarding client."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def forward(self, request: ProxyRequest) -> ForwardedResponse:
        import asyncio

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(request.host, request.port),
            timeout=self.timeout,
        )
        try:
            writer.write(self._build_upstream_request(request))
            await writer.drain()

            raw = await asyncio.wait_for(reader.read(-1), timeout=self.timeout)
            status_code, headers = parse_response_head(raw)
            return ForwardedResponse(raw=raw, status_code=status_code, headers=headers)
        finally:
            writer.close()
            await writer.wait_closed()

    def _build_upstream_request(self, request: ProxyRequest) -> bytes:
        lines = [f"{request.method} {request.origin_form_target} HTTP/1.1"]
        headers = dict(request.headers)
        headers["host"] = headers.get("host") or self._host_header(request)
        headers["connection"] = "close"

        for name, value in headers.items():
            if name in HOP_BY_HOP_HEADERS and name != "connection":
                continue
            canonical = "-".join(part.capitalize() for part in name.split("-"))
            lines.append(f"{canonical}: {value}")

        return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + request.body

    @staticmethod
    def _host_header(request: ProxyRequest) -> str:
        default_port = 443 if request.scheme == "https" else 80
        if request.port == default_port:
            return request.host
        return f"{request.host}:{request.port}"


def parse_response_head(raw: bytes) -> tuple[int, dict[str, str]]:
    head, _, _ = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    status_code = 502
    if lines:
        parts = lines[0].split(" ", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            status_code = int(parts[1])

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return status_code, headers
