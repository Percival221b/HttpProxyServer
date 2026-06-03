"""
性能指标收集器
收集和计算代理服务器的各种性能指标
"""

import time
import threading
import psutil
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
import logging


class MetricsCollector:
    """性能指标收集器"""
    
    def __init__(self, history_size: int = 3600):
        """
        初始化指标收集器
        
        Args:
            history_size: 保留的历史数据点数
        """
        self.history_size = history_size
        self._lock = threading.Lock()
        
        # 响应时间记录（毫秒）
        self._response_times = deque(maxlen=history_size)
        
        # 请求大小记录
        self._request_sizes = deque(maxlen=history_size)
        
        # 响应大小记录
        self._response_sizes = deque(maxlen=history_size)
        
        # 并发连接