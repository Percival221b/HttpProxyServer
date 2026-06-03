"""
访问日志记录器
记录客户端访问时间、目标地址、请求方法、响应状态、是否命中缓存等信息
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json


class AccessLogger:
    """HTTP代理访问日志记录器"""

    # 日志格式常量
    LOG_FORMAT = "{timestamp} | {client_ip}:{client_port} | {method} {url} | " \
                 "Status:{status_code} | Cache:{cache_hit} | Size:{response_size}B | " \
                 "Time:{duration_ms}ms | User-Agent:{user_agent}"

    def __init__(self, log_file: str | None = None, json_format: bool = False):
        """
        初始化访问日志记录器

        Args:
            log_file: 日志文件路径
            json_format: 是否使用JSON格式记录日志
        """
        if log_file is None:
            from config.settings import ACCESS_LOG_PATH
            log_file = ACCESS_LOG_PATH

        self.log_file = Path(log_file)
        self.json_format = json_format
        self._lock = threading.Lock()

        # 确保日志目录存在
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # 配置日志记录器
        logger_name = f"AccessLogger.{self.log_file.resolve()}.{json_format}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        # 文件处理器
        if not self.logger.handlers:
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter('%(message)s'))

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

        # 当前请求统计
        self._current_stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def log_request(self,
                    client_ip: str,
                    client_port: int,
                    method: str,
                    url: str,
                    status_code: int,
                    cache_hit: bool = False,
                    response_size: int = 0,
                    duration_ms: float = 0,
                    user_agent: str = "",
                    extra: Optional[Dict] = None):
        """
        记录一次HTTP请求

        Args:
            client_ip: 客户端IP地址
            client_port: 客户端端口
            method: 请求方法 (GET, POST, etc.)
            url: 请求URL
            status_code: 响应状态码
            cache_hit: 是否命中缓存
            response_size: 响应大小（字节）
            duration_ms: 请求处理耗时（毫秒）
            user_agent: 用户代理字符串
            extra: 额外信息
        """
        # 更新统计
        self._current_stats["total_requests"] += 1
        if cache_hit:
            self._current_stats["cache_hits"] += 1
        else:
            self._current_stats["cache_misses"] += 1

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if self.json_format:
            log_entry = {
                "timestamp": timestamp,
                "client_ip": client_ip,
                "client_port": client_port,
                "method": method,
                "url": url,
                "status_code": status_code,
                "cache_hit": cache_hit,
                "response_size": response_size,
                "duration_ms": round(duration_ms, 2),
                "user_agent": user_agent,
                "extra": extra or {}
            }
            log_message = json.dumps(log_entry, ensure_ascii=False)
        else:
            cache_status = "HIT" if cache_hit else "MISS"
            log_message = self.LOG_FORMAT.format(
                timestamp=timestamp,
                client_ip=client_ip,
                client_port=client_port,
                method=method,
                url=url[:200],  # 限制URL长度
                status_code=status_code,
                cache_hit=cache_status,
                response_size=response_size,
                duration_ms=round(duration_ms, 2),
                user_agent=user_agent[:100]  # 限制User-Agent长度
            )

        with self._lock:
            self.logger.info(log_message)

        # 同时写入统计文件
        self._update_statistics(timestamp, cache_hit, status_code, url)

    def _flush_buffer(self):
        """刷新日志缓冲区"""
        for handler in self.logger.handlers:
            handler.flush()

    def _update_statistics(self, timestamp: str, cache_hit: bool, status_code: int, url: str):
        """更新实时统计文件"""
        stats_file = self.log_file.parent / "stats.json"
        try:
            with self._lock:
                if stats_file.exists():
                    with open(stats_file, 'r', encoding='utf-8') as f:
                        stats = json.load(f)
                else:
                    stats = {
                        "total_requests": 0,
                        "cache_hits": 0,
                        "cache_misses": 0,
                        "status_codes": {},
                        "last_update": timestamp
                    }

                stats["total_requests"] += 1
                if cache_hit:
                    stats["cache_hits"] += 1
                else:
                    stats["cache_misses"] += 1

                stats["status_codes"][str(status_code)] = stats["status_codes"].get(str(status_code), 0) + 1
                stats["last_update"] = timestamp

                with open(stats_file, 'w', encoding='utf-8') as f:
                    json.dump(stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to update statistics: {e}")

    def log_error(self, client_ip: str, url: str, error: str, error_type: str = "UNKNOWN"):
        """记录错误日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        error_entry = {
            "timestamp": timestamp,
            "client_ip": client_ip,
            "url": url,
            "error_type": error_type,
            "error_message": error
        }

        with self._lock:
            self.logger.error(json.dumps(error_entry, ensure_ascii=False))

    def flush(self):
        """强制刷新日志缓冲区"""
        with self._lock:
            self._flush_buffer()

    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计信息"""
        with self._lock:
            return self._current_stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        with self._lock:
            self._current_stats = {
                "total_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0,
            }
