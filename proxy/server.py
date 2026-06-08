"""Async HTTP/HTTPS proxy server."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

from cache import CacheEntry, CacheManager, get_cache_manager
from config import settings
from database.database import init_db, insert_access_log, insert_cache_record
from logger import AccessLogger
from proxy.connect_tunnel import ConnectTunnel
from proxy.forwarder import HOP_BY_HOP_HEADERS, HTTPForwarder
from proxy.header_modifier import get_header_modifier
from proxy.parser import HTTPParseError, ProxyRequest, read_http_request
from security import get_access_control


CONDITIONAL_REQUEST_HEADERS = {
    "if-match",
    "if-none-match",
    "if-modified-since",
    "if-unmodified-since",
    "if-range",
}


class ProxyServer:
    """Main proxy server that coordinates parsing, security, cache and forwarding."""

    def __init__(
        self,
        host: str = settings.PROXY_HOST,
        port: int = settings.PROXY_PORT,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.cache = cache_manager or get_cache_manager()
        self.forwarder = HTTPForwarder()
        self.header_modifier = get_header_modifier()
        self.tunnel = ConnectTunnel()
        self.access_control = get_access_control()
        self.access_logger = AccessLogger(settings.ACCESS_LOG_PATH)
        self._server: asyncio.AbstractServer | None = None
        self._rules_loaded = False

    async def start(self) -> None:
        """Start accepting proxy connections."""
        await init_db()
        if not self._rules_loaded:
            await self.access_control.load_rules()
            self._rules_loaded = True
        await self.cache.evict_expired()
        self._server = await asyncio.start_server(self.handle_client, self.host, self.port)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop accepting new connections."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        started = time.perf_counter()
        peer = writer.get_extra_info("peername")
        client_ip = peer[0] if peer else "unknown"
        client_port = int(peer[1]) if peer and len(peer) > 1 else 0

        request: ProxyRequest | None = None
        status_code = 500
        cache_hit = False
        response_size = 0
        target_url = ""
        method = ""

        try:
            request = await read_http_request(reader)
            method = request.method.upper()
            target_url = request.url

            if self._is_self_request(request):
                status_code = 200
                body = self._proxy_info_page()
                response_size = len(body)
                await self._send_simple_response(writer, status_code, "OK", body, content_type="text/html; charset=utf-8")
                request = None
                return

            allowed, reason = await self._is_allowed(request, client_ip)
            if not allowed:
                status_code = 403
                body = reason.encode("utf-8")
                await self._send_simple_response(writer, status_code, "Forbidden", body)
                response_size = len(body)
                return

            if request.is_connect:
                status_code = 200
                response_size = await self.tunnel.open(request.host, request.port, reader, writer)
                return

            request.headers = self.header_modifier.apply(request.headers)

            if self._can_read_from_cache(method, target_url, request.headers):
                decision = await self.cache.get(target_url)
                if decision.hit and decision.entry is not None:
                    cache_hit = True
                    status_code = decision.entry.status_code
                    response_size = 0 if method == "HEAD" else decision.entry.size
                    writer.write(
                        self._build_cached_response(
                            decision.entry,
                            include_body=(method != "HEAD"),
                        )
                    )
                    await writer.drain()
                    return

            if method == "GET":
                self._prepare_cache_miss_request(request)

            upstream = await self.forwarder.forward(request)
            status_code = upstream.status_code
            response_size = upstream.body_size
            writer.write(
                self._add_response_headers(
                    upstream.raw,
                    {
                        "X-Proxy-Cache": "MISS" if method == "GET" else "BYPASS",
                    },
                )
            )
            await writer.drain()

            if self._is_cacheable(method, status_code, upstream.headers, target_url, request.headers):
                await self.cache.put(
                    target_url,
                    content=upstream.body,
                    status_code=status_code,
                    content_type=upstream.content_type,
                    headers=upstream.headers,
                )
                with suppress(Exception):
                    await insert_cache_record(
                        url=target_url,
                        content=upstream.body,
                        content_type=upstream.content_type,
                        status_code=status_code,
                        ttl=self.cache.ttl,
                    )

        except (asyncio.IncompleteReadError, HTTPParseError, ValueError) as exc:
            status_code = 400
            body = f"Bad Request: {exc}".encode("utf-8")
            response_size = len(body)
            await self._send_simple_response(writer, status_code, "Bad Request", body)
        except (OSError, asyncio.TimeoutError) as exc:
            status_code = 502
            body = f"Bad Gateway: {exc}".encode("utf-8")
            response_size = len(body)
            await self._send_simple_response(writer, status_code, "Bad Gateway", body)
        except Exception as exc:
            status_code = 500
            body = f"Internal Server Error: {exc}".encode("utf-8")
            response_size = len(body)
            await self._send_simple_response(writer, status_code, "Internal Server Error", body)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if request is not None:
                await self._record_access(
                    client_ip=client_ip,
                    client_port=client_port,
                    method=method,
                    url=target_url,
                    status_code=status_code,
                    cache_hit=cache_hit,
                    response_size=response_size,
                    duration_ms=duration_ms,
                    user_agent=request.headers.get("user-agent", ""),
                )

            if not writer.is_closing():
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

    async def _is_allowed(self, request: ProxyRequest, client_ip: str) -> tuple[bool, str]:
        url = request.url
        if settings.BLACKLIST_ENABLED:
            blocked, rule = self.access_control.blacklist.is_blocked(url)
            if blocked:
                return False, f'Blocked by blacklist: matched rule "{rule}"'

        if settings.WHITELIST_ENABLED:
            allowed, _ = self.access_control.whitelist.is_allowed(url)
            if not allowed:
                return False, "Blocked: URL not in whitelist"

        return True, ""

    async def _record_access(
        self,
        client_ip: str,
        client_port: int,
        method: str,
        url: str,
        status_code: int,
        cache_hit: bool,
        response_size: int,
        duration_ms: int,
        user_agent: str,
    ) -> None:
        with suppress(Exception):
            self.access_logger.log_request(
                client_ip=client_ip,
                client_port=client_port,
                method=method,
                url=url,
                status_code=status_code,
                cache_hit=cache_hit,
                response_size=response_size,
                duration_ms=duration_ms,
                user_agent=user_agent,
            )
        with suppress(Exception):
            await insert_access_log(
                client_ip=client_ip,
                target_url=url,
                method=method,
                status_code=status_code,
                cache_hit=cache_hit,
                response_size=response_size,
                duration_ms=duration_ms,
            )

    def _is_self_request(self, request: ProxyRequest) -> bool:
        host = request.host.lower()
        local_hosts = {
            "127.0.0.1",
            "localhost",
            "::1",
            self.host.lower(),
        }
        return host in local_hosts and request.port == self.port

    @staticmethod
    def _proxy_info_page() -> bytes:
        return (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>HTTP Proxy Server</title>"
            "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:760px;"
            "margin:48px auto;line-height:1.7;color:#1f2937}"
            "code{background:#f3f4f6;padding:2px 6px;border-radius:4px}</style>"
            "</head><body>"
            "<h1>HTTP Proxy Server 正在运行</h1>"
            "<p>这个端口是代理服务端口，不是网站页面端口。请不要直接把浏览器打开到 "
            "<code>http://127.0.0.1:8080/</code>。</p>"
            "<p>Dashboard 地址：<code>http://127.0.0.1:8000/dashboard/</code></p>"
            "<p>通过代理测试 HouseRent：配置浏览器 HTTP 代理为 "
            "<code>127.0.0.1:8080</code>，然后访问 HouseRent 的实际地址，例如 "
            "<code>http://192.168.1.5:5000/</code>。</p>"
            "</body></html>"
        ).encode("utf-8")

    @staticmethod
    def _can_read_from_cache(method: str, url: str, request_headers: dict[str, str]) -> bool:
        if method.upper() not in {"GET", "HEAD"}:
            return False
        if ProxyServer._is_static_asset(url, request_headers):
            return True
        return not ProxyServer._has_user_specific_request_headers(request_headers)

    @staticmethod
    def _is_cacheable(
        method: str,
        status_code: int,
        headers: dict[str, str],
        url: str = "",
        request_headers: dict[str, str] | None = None,
    ) -> bool:
        if method.upper() != "GET" or status_code != 200:
            return False
        cache_control = headers.get("cache-control", "").lower()
        pragma = headers.get("pragma", "").lower()
        is_static_asset = ProxyServer._is_static_asset(url, headers)

        if "no-store" in cache_control:
            return False

        if is_static_asset:
            return True

        if request_headers and ProxyServer._has_user_specific_request_headers(request_headers):
            return False

        return (
            "no-cache" not in cache_control
            and "private" not in cache_control
            and pragma != "no-cache"
            and "set-cookie" not in headers
        )

    @staticmethod
    def _has_user_specific_request_headers(headers: dict[str, str]) -> bool:
        return bool(headers.get("cookie") or headers.get("authorization"))

    @staticmethod
    def _is_static_asset(url: str, headers: dict[str, str]) -> bool:
        from urllib.parse import urlsplit

        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type.startswith(("image/", "font/")):
            return True
        if content_type in {
            "text/css",
            "application/javascript",
            "text/javascript",
            "application/x-javascript",
        }:
            return True

        path = urlsplit(url).path.lower()
        return path.endswith(
            (
                ".css",
                ".js",
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".webp",
                ".svg",
                ".ico",
                ".woff",
                ".woff2",
                ".ttf",
            )
        )

    @staticmethod
    def _prepare_cache_miss_request(request: ProxyRequest) -> None:
        if not ProxyServer._is_static_asset(request.url, request.headers):
            return

        for name in CONDITIONAL_REQUEST_HEADERS:
            request.headers.pop(name, None)

    def _build_cached_response(self, entry: CacheEntry, include_body: bool = True) -> bytes:
        reason = self._reason_phrase(entry.status_code)
        lines = [f"HTTP/1.1 {entry.status_code} {reason}"]
        has_transfer_encoding = False

        for name, value in entry.headers.items():
            lower_name = name.lower()
            if lower_name in HOP_BY_HOP_HEADERS and lower_name not in {"transfer-encoding"}:
                continue
            if lower_name == "content-length":
                continue
            if lower_name == "transfer-encoding":
                has_transfer_encoding = True
            canonical = "-".join(part.capitalize() for part in lower_name.split("-"))
            lines.append(f"{canonical}: {value}")

        if not has_transfer_encoding:
            lines.append(f"Content-Length: {len(entry.content)}")
        lines.append("Connection: close")
        lines.append("X-Proxy-Cache: HIT")
        body = entry.content if include_body else b""
        return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + body

    @staticmethod
    def _add_response_headers(raw: bytes, headers: dict[str, str]) -> bytes:
        head, separator, body = raw.partition(b"\r\n\r\n")
        if not separator:
            return raw

        existing = head.decode("iso-8859-1", errors="replace").split("\r\n")
        filtered = []
        injected_names = {name.lower() for name in headers}
        for line in existing:
            if ":" not in line:
                filtered.append(line)
                continue
            name, _ = line.split(":", 1)
            if name.strip().lower() not in injected_names:
                filtered.append(line)

        for name, value in headers.items():
            filtered.append(f"{name}: {value}")

        return ("\r\n".join(filtered) + "\r\n\r\n").encode("iso-8859-1") + body

    @staticmethod
    def _reason_phrase(status_code: int) -> str:
        phrases = {
            200: "OK",
            301: "Moved Permanently",
            302: "Found",
            304: "Not Modified",
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found",
            500: "Internal Server Error",
            502: "Bad Gateway",
            504: "Gateway Timeout",
        }
        return phrases.get(status_code, "OK")

    async def _send_simple_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        reason: str,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        response = (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("iso-8859-1") + body
        writer.write(response)
        await writer.drain()
