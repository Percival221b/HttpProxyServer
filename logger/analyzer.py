"""
日志分析器
提供日志查询、过滤和分析功能
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, Counter


class LogAnalyzer:
    """访问日志分析器"""

    def __init__(self, log_file: str | None = None):
        """
        初始化日志分析器

        Args:
            log_file: 日志文件路径
        """
        if log_file is None:
            from config.settings import ACCESS_LOG_PATH
            log_file = ACCESS_LOG_PATH

        self.log_file = Path(log_file)
        self._cached_logs = []
        self._last_load_time = None

    def load_logs(self, force_reload: bool = False) -> List[Dict]:
        """
        加载日志文件

        Args:
            force_reload: 是否强制重新加载

        Returns:
            日志条目列表
        """
        if not force_reload and self._cached_logs and self._last_load_time:
            # 检查文件是否被修改
            if datetime.fromtimestamp(self.log_file.stat().st_mtime) <= self._last_load_time:
                return self._cached_logs

        logs = []

        if not self.log_file.exists():
            return logs

        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                log_entry = self._parse_log_line(line.strip())
                if log_entry:
                    logs.append(log_entry)

        self._cached_logs = logs
        self._last_load_time = datetime.now()

        return logs

    def _parse_log_line(self, line: str) -> Optional[Dict]:
        """
        解析单行日志

        支持两种格式：
        1. JSON格式
        2. 文本格式
        """
        # 尝试JSON解析
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

        # 解析文本格式
        # 格式: timestamp | client_ip:port | method url | Status:code | Cache:status | Size:sizeB | Time:timeMs | User-Agent:ua
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| ([^:]+):(\d+) \| (\w+) (.*?) \| Status:(\d+) \| Cache:(HIT|MISS) \| Size:(\d+)B \| Time:([\d.]+)ms \| User-Agent:(.*)'
        match = re.match(pattern, line)

        if match:
            return {
                "timestamp": match.group(1),
                "client_ip": match.group(2),
                "client_port": int(match.group(3)),
                "method": match.group(4),
                "url": match.group(5),
                "status_code": int(match.group(6)),
                "cache_hit": match.group(7) == "HIT",
                "response_size": int(match.group(8)),
                "duration_ms": float(match.group(9)),
                "user_agent": match.group(10)
            }

        return None

    def filter_logs(self,
                   start_time: Optional[datetime] = None,
                   end_time: Optional[datetime] = None,
                   client_ip: Optional[str] = None,
                   method: Optional[str] = None,
                   status_code: Optional[int] = None,
                   cache_hit: Optional[bool] = None,
                   url_pattern: Optional[str] = None) -> List[Dict]:
        """
        过滤日志

        Args:
            start_time: 开始时间
            end_time: 结束时间
            client_ip: 客户端IP
            method: 请求方法
            status_code: 状态码
            cache_hit: 是否命中缓存
            url_pattern: URL匹配模式（正则表达式）

        Returns:
            过滤后的日志列表
        """
        logs = self.load_logs()

        filtered = []
        for log in logs:
            # 时间过滤
            if start_time or end_time:
                log_time = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                if start_time and log_time < start_time:
                    continue
                if end_time and log_time > end_time:
                    continue

            # IP过滤
            if client_ip and log.get("client_ip") != client_ip:
                continue

            # 方法过滤
            if method and log.get("method") != method:
                continue

            # 状态码过滤
            if status_code and log.get("status_code") != status_code:
                continue

            # 缓存命中过滤
            if cache_hit is not None and log.get("cache_hit") != cache_hit:
                continue

            # URL模式过滤
            if url_pattern and not re.search(url_pattern, log.get("url", ""), re.IGNORECASE):
                continue

            filtered.append(log)

        return filtered

    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取统计信息

        Args:
            hours: 统计最近多少小时的数据

        Returns:
            统计信息字典
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        logs = self.filter_logs(start_time=cutoff_time)

        if not logs:
            return {}

        total_requests = len(logs)
        cache_hits = sum(1 for log in logs if log.get("cache_hit", False))

        # 状态码分布
        status_counter = Counter(log.get("status_code", 0) for log in logs)

        # 请求方法分布
        method_counter = Counter(log.get("method", "UNKNOWN") for log in logs)

        # 热门URL
        url_counter = Counter(log.get("url", "") for log in logs)

        # 响应时间统计
        durations = [log.get("duration_ms", 0) for log in logs]

        # 按小时统计
        hourly_stats = defaultdict(lambda: {"total": 0, "cache_hits": 0})
        for log in logs:
            hour = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d %H:00")
            hourly_stats[hour]["total"] += 1
            if log.get("cache_hit", False):
                hourly_stats[hour]["cache_hits"] += 1

        return {
            "time_range_hours": hours,
            "total_requests": total_requests,
            "cache_hits": cache_hits,
            "cache_misses": total_requests - cache_hits,
            "cache_hit_rate": round(cache_hits / total_requests * 100, 2) if total_requests > 0 else 0,
            "status_codes": dict(status_counter),
            "methods": dict(method_counter),
            "top_urls": url_counter.most_common(10),
            "avg_response_time_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "max_response_time_ms": max(durations) if durations else 0,
            "min_response_time_ms": min(durations) if durations else 0,
            "hourly_stats": dict(hourly_stats)
        }

    def get_client_stats(self) -> List[Dict[str, Any]]:
        """
        获取客户端统计信息

        Returns:
            每个客户端的统计信息列表
        """
        logs = self.load_logs()

        client_data = defaultdict(lambda: {
            "requests": 0,
            "cache_hits": 0,
            "total_size": 0,
            "methods": Counter(),
            "status_codes": Counter()
        })

        for log in logs:
            ip = log.get("client_ip", "unknown")
            client_data[ip]["requests"] += 1
            if log.get("cache_hit", False):
                client_data[ip]["cache_hits"] += 1
            client_data[ip]["total_size"] += log.get("response_size", 0)
            client_data[ip]["methods"][log.get("method", "UNKNOWN")] += 1
            client_data[ip]["status_codes"][log.get("status_code", 0)] += 1

        result = []
        for ip, data in client_data.items():
            result.append({
                "client_ip": ip,
                "requests": data["requests"],
                "cache_hit_rate": round(data["cache_hits"] / data["requests"] * 100, 2) if data["requests"] > 0 else 0,
                "total_bytes": data["total_size"],
                "methods": dict(data["methods"]),
                "status_codes": dict(data["status_codes"])
            })

        return sorted(result, key=lambda x: x["requests"], reverse=True)

    def export_to_csv(self, output_file: str):
        """导出日志为CSV格式"""
        import csv

        logs = self.load_logs()
        if not logs:
            return

        fieldnames = ["timestamp", "client_ip", "client_port", "method", "url",
                     "status_code", "cache_hit", "response_size", "duration_ms", "user_agent"]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for log in logs:
                writer.writerow({k: log.get(k, "") for k in fieldnames})
