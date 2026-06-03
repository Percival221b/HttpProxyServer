"""
热门资源追踪器
追踪访问次数最多的资源、带宽消耗最大的资源等
"""

import json
import threading
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging


class TopResourcesTracker:
    """热门资源追踪器"""

    def __init__(self, data_file: str = "logs/top_resources.json", top_n: int = 100):
        """
        初始化热门资源追踪器

        Args:
            data_file: 数据持久化文件路径
            top_n: 保留的热门资源数量
        """
        self.data_file = Path(data_file)
        self.top_n = top_n
        self._lock = threading.RLock()

        # 统计数据
        self._url_stats = Counter()  # URL -> 访问次数
        self._url_bytes = Counter()  # URL -> 传输字节数
        self._url_last_access = {}   # URL -> 最后访问时间

        # 按域名统计
        self._domain_stats = Counter()
        self._domain_bytes = Counter()

        # 按内容类型统计
        self._content_type_stats = Counter()

        # 时间窗口数据（最近1小时）
        self._recent_accesses = []

        self.logger = logging.getLogger("TopResourcesTracker")

        # 加载已有数据
        self._load_data()

    def record_access(self, url: str, size: int = 0, content_type: str = ""):
        """
        记录一次资源访问

        Args:
            url: 请求URL
            size: 响应大小（字节）
            content_type: 内容类型
        """
        with self._lock:
            # 更新URL统计
            self._url_stats[url] += 1
            self._url_bytes[url] += size
            self._url_last_access[url] = datetime.now().isoformat()

            # 更新域名统计
            domain = self._extract_domain(url)
            self._domain_stats[domain] += 1
            self._domain_bytes[domain] += size

            # 更新内容类型统计
            if content_type:
                main_type = content_type.split(';')[0].strip()
                self._content_type_stats[main_type] += 1

            # 更新最近访问（用于计算热点趋势）
            self._recent_accesses.append({
                "timestamp": datetime.now(),
                "url": url,
                "size": size
            })

            # 清理过期数据
            self._cleanup_old_data()

            # 持久化
            self._save_data()

    def _extract_domain(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            if url.startswith("http://"):
                url = url[7:]
            elif url.startswith("https://"):
                url = url[8:]
            domain = url.split("/")[0].split(":")[0]
            return domain
        except Exception:
            return "unknown"

    def _cleanup_old_data(self):
        """清理过期数据，只保留top_n条"""
        # 清理URL统计
        if len(self._url_stats) > self.top_n * 2:
            # 保留访问次数最多的top_n条
            top_urls = set(url for url, _ in self._url_stats.most_common(self.top_n))
            self._url_stats = Counter({url: count for url, count in self._url_stats.items()
                                       if url in top_urls})
            self._url_bytes = Counter({url: bytes for url, bytes in self._url_bytes.items()
                                       if url in top_urls})
            self._url_last_access = {url: time for url, time in self._url_last_access.items()
                                     if url in top_urls}

    def _load_data(self):
        """从文件加载数据"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._url_stats = Counter(data.get("url_stats", {}))
                    self._url_bytes = Counter(data.get("url_bytes", {}))
                    self._url_last_access = data.get("url_last_access", {})
                    self._domain_stats = Counter(data.get("domain_stats", {}))
                    self._domain_bytes = Counter(data.get("domain_bytes", {}))
                    self._content_type_stats = Counter(data.get("content_type_stats", {}))
            except Exception as e:
                self.logger.error(f"Failed to load data: {e}")

    def _save_data(self):
        """持久化数据到文件"""
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "url_stats": dict(self._url_stats),
                "url_bytes": dict(self._url_bytes),
                "url_last_access": self._url_last_access,
                "domain_stats": dict(self._domain_stats),
                "domain_bytes": dict(self._domain_bytes),
                "content_type_stats": dict(self._content_type_stats),
                "last_updated": datetime.now().isoformat()
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save data: {e}")

    def get_top_urls(self, n: int = 10, by_bytes: bool = False) -> List[Dict]:
        """
        获取热门URL

        Args:
            n: 返回数量
            by_bytes: 是否按传输字节数排序（否则按访问次数）

        Returns:
            热门URL列表
        """
        with self._lock:
            if by_bytes:
                top = self._url_bytes.most_common(n)
            else:
                top = self._url_stats.most_common(n)

            result = []
            for url, value in top:
                result.append({
                    "url": url,
                    "count": self._url_stats.get(url, 0),
                    "total_bytes": self._url_bytes.get(url, 0),
                    "last_access": self._url_last_access.get(url, ""),
                    "avg_size": round(self._url_bytes.get(url, 0) / self._url_stats.get(url, 1), 2)
                })
            return result

    def get_top_domains(self, n: int = 10, by_bytes: bool = False) -> List[Dict]:
        """
        获取热门域名

        Args:
            n: 返回数量
            by_bytes: 是否按传输字节数排序

        Returns:
            热门域名列表
        """
        with self._lock:
            if by_bytes:
                top = self._domain_bytes.most_common(n)
            else:
                top = self._domain_stats.most_common(n)

            result = []
            for domain, value in top:
                result.append({
                    "domain": domain,
                    "requests": self._domain_stats.get(domain, 0),
                    "total_bytes": self._domain_bytes.get(domain, 0),
                    "avg_bytes_per_request": round(self._domain_bytes.get(domain, 0) /
                                                   self._domain_stats.get(domain, 1), 2)
                })
            return result

    def get_content_type_distribution(self) -> List[Dict]:
        """
        获取内容类型分布

        Returns:
            内容类型统计列表
        """
        with self._lock:
            total = sum(self._content_type_stats.values())
            result = []
            for content_type, count in self._content_type_stats.most_common():
                result.append({
                    "content_type": content_type,
                    "count": count,
                    "percentage": round(count / total * 100, 2) if total > 0 else 0
                })
            return result

    def get_trending_resources(self, minutes: int = 60) -> List[Dict]:
        """
        获取最近一段时间内的热门趋势

        Args:
            minutes: 时间窗口（分钟）

        Returns:
            趋势资源列表
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=minutes)

            recent_counter = Counter()
            for access in self._recent_accesses:
                if access["timestamp"] >= cutoff:
                    recent_counter[access["url"]] += 1

            # 计算增长因子（当前窗口 vs 历史平均）
            trending = []
            for url, recent_count in recent_counter.most_common(20):
                total_count = self._url_stats.get(url, 1)
                historical_avg = total_count / 24  # 粗略估算历史平均每小时
                growth_factor = recent_count / (historical_avg + 0.01)

                trending.append({
                    "url": url,
                    "recent_requests": recent_count,
                    "historical_avg_per_hour": round(historical_avg, 2),
                    "growth_factor": round(growth_factor, 2),
                    "total_requests": total_count
                })

            return sorted(trending, key=lambda x: x["growth_factor"], reverse=True)[:10]

    def get_summary(self) -> Dict[str, Any]:
        """
        获取热门资源摘要

        Returns:
            摘要信息
        """
        with self._lock:
            return {
                "total_unique_urls": len(self._url_stats),
                "total_unique_domains": len(self._domain_stats),
                "total_content_types": len(self._content_type_stats),
                "top_url": self.get_top_urls(1)[0] if self._url_stats else None,
                "top_domain": self.get_top_domains(1)[0] if self._domain_stats else None,
                "most_common_content_type": self._content_type_stats.most_common(1)[0][0]
                                           if self._content_type_stats else None
            }

class deque_with_maxlen:
    """带最大长度的双端队列（兼容collections.deque的语法）"""
    def __init__(self, maxlen=10000):
        from collections import deque
        self._deque = deque(maxlen=maxlen)

    def append(self, item):
        self._deque.append(item)

    def __iter__(self):
        return iter(self._deque)
