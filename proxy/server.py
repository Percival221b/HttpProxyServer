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
from proxy.parser import HTTPParseError, ProxyRequest, read_http_request
from security import get_access_control


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

            if method == "GET":
                decision = await self.cache.get(target_url)
                if decision.hit and decision.entry is not None:
                    cache_hit = True
                    status_code = decision.entry.status_code
                    response_size = decision.entry.size
                    writer.write(self._build_cached_response(decision.entry))
                    await writer.drain()
                    return

            upstream = await self.forwarder.forward(request)
            status_code = upstream.status_code
            response_size = upstream.body_size
            writer.write(upstream.raw)
            await writer.drain()

            if self._is_cacheable(method, status_code, upstream.headers):
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

    @staticmethod
    def _is_cacheable(method: str, status_code: int, headers: dict[str, str]) -> bool:
        if method.upper() != "GET" or status_code != 200:
            return False
        cache_control = headers.get("cache-control", "").lower()
        pragma = headers.get("pragma", "").lower()
        return (
            "no-store" not in cache_control
            and "no-cache" not in cache_control
            and pragma != "no-cache"
        )

    def _build_cached_response(self, entry: CacheEntry) -> bytes:
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
        return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + entry.content

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
    ) -> None:
        response = (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("iso-8859-1") + body
        writer.write(response)
        await writer.drain()
