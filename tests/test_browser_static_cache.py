from __future__ import annotations

import json

from logger.access_logger import AccessLogger
from proxy.parser import ProxyRequest
from proxy.server import ProxyServer


def test_static_cache_miss_request_drops_browser_revalidation_headers():
    request = ProxyRequest(
        method="GET",
        target="http://example.test/static/app.js",
        version="HTTP/1.1",
        headers={
            "host": "example.test",
            "if-none-match": '"asset-etag"',
            "if-modified-since": "Fri, 05 Jun 2026 01:00:00 GMT",
            "user-agent": "Firefox",
        },
    )

    ProxyServer._prepare_cache_miss_request(request)

    assert "if-none-match" not in request.headers
    assert "if-modified-since" not in request.headers
    assert request.headers["user-agent"] == "Firefox"


def test_dynamic_cache_miss_request_keeps_revalidation_headers():
    request = ProxyRequest(
        method="GET",
        target="http://example.test/dashboard",
        version="HTTP/1.1",
        headers={
            "host": "example.test",
            "if-none-match": '"page-etag"',
        },
    )

    ProxyServer._prepare_cache_miss_request(request)

    assert request.headers["if-none-match"] == '"page-etag"'


def test_access_logger_recovers_empty_stats_file(tmp_path):
    log_path = tmp_path / "access.log"
    stats_path = tmp_path / "stats.json"
    stats_path.write_text("", encoding="utf-8")

    logger = AccessLogger(str(log_path))
    logger.log_request(
        client_ip="127.0.0.1",
        client_port=8080,
        method="GET",
        url="http://example.test/static/app.css",
        status_code=200,
        cache_hit=False,
        response_size=128,
        duration_ms=1,
        user_agent="pytest",
    )

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert stats["total_requests"] == 1
    assert stats["cache_misses"] == 1
    assert stats["status_codes"]["200"] == 1
