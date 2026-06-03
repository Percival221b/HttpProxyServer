"""
性能指标收集器

收集和计算代理服务器的响应时间、传输大小、连接数和系统资源指标。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

try:
    import psutil
except ModuleNotFoundError:
    psutil = None


class MetricsCollector:
    """性能指标收集器"""

    def __init__(self, history_size: int = 3600) -> None:
        """
        Args:
            history_size: 保留的历史数据点数
        """
        self.history_size = history_size
        self._lock = threading.RLock()

        self._response_times = deque(maxlen=history_size)
        self._request_sizes = deque(maxlen=history_size)
        self._response_sizes = deque(maxlen=history_size)
        self._request_events = deque(maxlen=history_size)
        self._system_samples = deque(maxlen=history_size)

        self._total_requests = 0
        self._total_errors = 0
        self._active_connections = 0
        self._max_active_connections = 0
        self._started_at = time.time()

        self.logger = logging.getLogger("MetricsCollector")

    def record_request(
        self,
        duration_ms: float,
        request_size: int = 0,
        response_size: int = 0,
        status_code: int = 200,
    ) -> None:
        """记录一次请求的性能数据"""
        with self._lock:
            self._total_requests += 1
            if status_code >= 400:
                self._total_errors += 1

            self._response_times.append(float(duration_ms))
            self._request_sizes.append(max(0, int(request_size)))
            self._response_sizes.append(max(0, int(response_size)))
            self._request_events.append(
                {
                    "timestamp": datetime.now(),
                    "duration_ms": float(duration_ms),
                    "request_size": max(0, int(request_size)),
                    "response_size": max(0, int(response_size)),
                    "status_code": int(status_code),
                }
            )

    def connection_opened(self) -> None:
        """记录一个新连接"""
        with self._lock:
            self._active_connections += 1
            self._max_active_connections = max(
                self._max_active_connections,
                self._active_connections,
            )

    def connection_closed(self) -> None:
        """记录一个连接关闭"""
        with self._lock:
            self._active_connections = max(0, self._active_connections - 1)

    def sample_system_metrics(self) -> dict[str, Any]:
        """采样 CPU、内存和进程资源使用情况"""
        if psutil is None:
            sample = {
                "timestamp": datetime.now().isoformat(),
                "available": False,
                "error": "psutil is not installed",
                "active_connections": self.get_active_connections(),
            }
            with self._lock:
                self._system_samples.append(sample)
            return sample

        process = psutil.Process()
        sample = {
            "timestamp": datetime.now().isoformat(),
            "available": True,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "process_memory_bytes": process.memory_info().rss,
            "process_threads": process.num_threads(),
            "active_connections": self.get_active_connections(),
        }

        with self._lock:
            self._system_samples.append(sample)

        return sample

    def get_active_connections(self) -> int:
        """获取当前活跃连接数"""
        with self._lock:
            return self._active_connections

    def get_summary(self) -> dict[str, Any]:
        """获取整体性能摘要"""
        with self._lock:
            response_times = list(self._response_times)
            response_sizes = list(self._response_sizes)
            request_sizes = list(self._request_sizes)
            uptime_seconds = max(0.001, time.time() - self._started_at)

            return {
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": self._rate(self._total_errors, self._total_requests),
                "requests_per_second": round(self._total_requests / uptime_seconds, 2),
                "active_connections": self._active_connections,
                "max_active_connections": self._max_active_connections,
                "avg_response_time_ms": self._avg(response_times),
                "max_response_time_ms": max(response_times) if response_times else 0,
                "min_response_time_ms": min(response_times) if response_times else 0,
                "avg_request_size": self._avg(request_sizes),
                "avg_response_size": self._avg(response_sizes),
                "total_response_bytes": sum(response_sizes),
                "uptime_seconds": round(uptime_seconds, 2),
                "last_system_sample": self._system_samples[-1] if self._system_samples else None,
            }

    def get_recent_requests(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取最近的请求性能记录"""
        with self._lock:
            events = list(self._request_events)[-limit:]

        return [
            {
                **event,
                "timestamp": event["timestamp"].isoformat(),
            }
            for event in events
        ]

    def reset(self) -> None:
        """重置所有已收集指标"""
        with self._lock:
            self._response_times.clear()
            self._request_sizes.clear()
            self._response_sizes.clear()
            self._request_events.clear()
            self._system_samples.clear()
            self._total_requests = 0
            self._total_errors = 0
            self._active_connections = 0
            self._max_active_connections = 0
            self._started_at = time.time()

    @staticmethod
    def _avg(values: list[float] | list[int]) -> float:
        return round(sum(values) / len(values), 2) if values else 0

    @staticmethod
    def _rate(part: int, total: int) -> float:
        return round(part / total * 100, 2) if total else 0
