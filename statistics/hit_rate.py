"""
缓存命中率计算器
计算实时和历史缓存命中率
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import deque
import logging


class HitRateCalculator:
    """缓存命中率计算器"""
    
    def __init__(self, stats_file: str = "logs/stats.json", history_size: int = 100):
        """
        初始化命中率计算器
        
        Args:
            stats_file: 统计文件路径
            history_size: 保存的历史记录数量
        """
        self.stats_file = Path(stats_file)
        self.history_size = history_size
        self._lock = threading.Lock()
        
        # 历史记录（滑动窗口）
        self._history = deque(maxlen=history_size)
        
        # 按域名统计
        self._domain_stats = {}
        
        # 按时间段统计
        self._hourly_stats = {}
        
        self.logger = logging.getLogger("HitRateCalculator")
        
        # 加载现有数据
        self._load_data()
    
    def _load_data(self):
        """加载已有数据"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._record_hit_rate(data.get("total_requests", 0),
                                          data.get("cache_hits", 0))
            except Exception as e:
                self.logger.error(f"Failed to load stats: {e}")
    
    def _record_hit_rate(self, total_requests: int, cache_hits: int):
        """记录命中率"""
        hit_rate = cache_hits / total_requests * 100 if total_requests > 0 else 0
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "total_requests": total_requests,
            "cache_hits": cache_hits,
            "hit_rate": round(hit_rate, 2)
        })
    
    def update(self, cache_hit: bool, url: str = ""):
        """
        更新命中率统计
        
        Args:
            cache_hit: 是否命中缓存
            url: 请求URL（用于域名统计）
        """
        with self._lock:
            # 更新域名统计
            if url:
                domain = self._extract_domain(url)
                if domain not in self._domain_stats:
                    self._domain_stats[domain] = {"total": 0, "hits": 0}
                self._domain_stats[domain]["total"] += 1
                if cache_hit:
                    self._domain_stats[domain]["hits"] += 1
            
            # 更新小时统计
            hour = datetime.now().strftime("%Y-%m-%d %H:00")
            if hour not in self._hourly_stats:
                self._hourly_stats[hour] = {"total": 0, "hits": 0}
            self._hourly_stats[hour]["total"] += 1
            if cache_hit:
                self._hourly_stats[hour]["hits"] += 1
    
    def _extract_domain(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            # 简单的域名提取
            if url.startswith("http://"):
                url = url[7:]
            elif url.startswith("https://"):
                url = url[8:]
            
            domain = url.split("/")[0].split(":")[0]
            return domain
        except Exception:
            return "unknown"
    
    def get_current_hit_rate(self) -> float:
        """获取当前总体命中率"""
        with self._lock:
            total = sum(stat["total"] for stat in self._hourly_stats.values())
            hits = sum(stat["hits"] for stat in self._hourly_stats.values())
            return round(hits / total * 100, 2) if total > 0 else 0
    
    def get_hit_rate_history(self, hours: int = 24) -> List[Dict]:
        """
        获取历史命中率数据
        
        Args:
            hours: 获取最近多少小时的数据
            
        Returns:
            每小时命中率列表
        """
        with self._lock:
            now = datetime.now()
            result = []
            
            for hour_str, stats in sorted(self._hourly_stats.items()):
                hour_time = datetime.strptime(hour_str, "%Y-%m-%d %H:00")
                if (now - hour_time).total_seconds() <= hours * 3600:
                    hit_rate = stats["hits"] / stats["total"] * 100 if stats["total"] > 0 else 0
                    result.append({
                        "hour": hour_str,
                        "total_requests": stats["total"],
                        "cache_hits": stats["hits"],
                        "hit_rate": round(hit_rate, 2)
                    })
            
            return result
    
    def get_domain_hit_rates(self) -> List[Dict]:
        """
        获取各域名的命中率
        
        Returns:
            按访问量排序的域名命中率列表
        """
        with self._lock:
            result = []
            for domain, stats in self._domain_stats.items():
                hit_rate = stats["hits"] / stats["total"] * 100 if stats["total"] > 0 else 0
                result.append({
                    "domain": domain,
                    "total_requests": stats["total"],
                    "cache_hits": stats["hits"],
                    "cache_misses": stats["total"] - stats["hits"],
                    "hit_rate": round(hit_rate, 2)
                })
            
            return sorted(result, key=lambda x: x["total_requests"], reverse=True)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        获取性能摘要
        
        Returns:
            性能摘要信息
        """
        with self._lock:
            total_requests = sum(stat["total"] for stat in self._hourly_stats.values())
            total_hits = sum(stat["hits"] for stat in self._hourly_stats.values())
            
            if len(self._history) > 0:
                recent_hit_rate = self._history[-1]["hit_rate"]
            else:
                recent_hit_rate = 0
            
            return {
                "current_hit_rate": self.get_current_hit_rate(),
                "recent_hit_rate": recent_hit_rate,
                "total_requests_all_time": total_requests,
                "total_cache_hits_all_time": total_hits,
                "domains_tracked": len(self._domain_stats),
                "hours_tracked": len(self._hourly_stats),
                "history_samples": len(self._history)
            }
    
    def get_recommendations(self) -> List[str]:
        """
        获取优化建议
        
        Returns:
            优化建议列表
        """
        recommendations = []
        
        current_rate = self.get_current_hit_rate()
        
        if current_rate < 30:
            recommendations.append("缓存命中率较低，建议增加缓存过期时间或检查缓存策略")
        elif current_rate > 80:
            recommendations.append("缓存命中率良好，当前策略有效")
        
        # 检查低命中率域名
        low_hit_domains = []
        for domain_stat in self.get_domain_hit_rates():
            if domain_stat["hit_rate"] < 20 and domain_stat["total_requests"] > 10:
                low_hit_domains.append(domain_stat["domain"])
        
        if low_hit_domains:
            recommendations.append(f"以下域名命中率较低，建议调整缓存策略: {', '.join(low_hit_domains[:3])}")
        
        return recommendations