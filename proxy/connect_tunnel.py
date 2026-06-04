"""HTTPS CONNECT tunneling support."""

from __future__ import annotations

import asyncio


class ConnectTunnel:
    """Bidirectional TCP tunnel for HTTP CONNECT requests."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def open(self, host: str, port: int, client_reader, client_writer) -> int:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=self.timeout,
        )
        bytes_transferred = 0
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        async def pipe(reader, writer) -> int:
            total = 0
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    total += len(data)
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
            return total

        try:
            client_to_upstream = asyncio.create_task(pipe(client_reader, upstream_writer))
            upstream_to_client = asyncio.create_task(pipe(upstream_reader, client_writer))
            done, pending = await asyncio.wait(
                {client_to_upstream, upstream_to_client},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                bytes_transferred += task.result()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            upstream_writer.close()
            await upstream_writer.wait_closed()

        return bytes_transferred
