"""
LRU（最近最少使用）缓存实现

基于 collections.OrderedDict 实现 O(1) 的读写和淘汰操作。
异步安全，使用 asyncio.Lock 保护并发访问。

核心数据结构:
    OrderedDict 按插入/访问顺序维护条目：
    - 每次 get/put 时将条目移到末尾（最近使用）
    - 当容量超限时，弹出最前面的条目（最久未使用）

Classes:
    LRUCache — 带可选 TTL 的 LRU 缓存容器
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Generator

from cache.cache_model import CacheEntry


class LRUCache:
    """
    基于 OrderedDict 的 LRU 缓存容器。

    特性：
        - O(1) 查找、插入、淘汰
        - 异步安全（asyncio.Lock）
        - 容量控制（max_size）
        - 可选的 TTL 支持

    使用示例：
        >>> cache = LRUCache(max_size=1000)
        >>> await cache.put("http://example.com", entry)
        >>> entry = await cache.get("http://example.com")  # 命中 → 移到末尾
        >>> None == await cache.get("http://missing.com")  # 未命中 → None
    """

    def __init__(self, max_size: int = 1000) -> None:
        """
        Args:
            max_size: 最大缓存条目数（默认 1000）
        """
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._max_size: int = max_size
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock: asyncio.Lock = asyncio.Lock()

    # ================================================================
    # 属性
    # ================================================================

    @property
    def max_size(self) -> int:
        """最大容量。"""
        return self._max_size

    @property
    def size(self) -> int:
        """当前条目数。"""
        return len(self._store)

    @property
    def is_full(self) -> bool:
        """是否已满。"""
        return len(self._store) >= self._max_size

    # ================================================================
    # 核心操作
    # ================================================================

    async def get(self, url: str) -> CacheEntry | None:
        """
        查找缓存条目。

        - 命中时将该条目移到 LRU 队列末尾（标记为最近使用）
        - 未命中时返回 None

        Args:
            url: 请求 URL（缓存键）

        Returns:
            CacheEntry 如果命中，否则 None
        """
        async with self._lock:
            entry = self._store.get(url)
            if entry is not None:
                # 移到末尾 → 标记为最近使用
                self._store.move_to_end(url)
            return entry

    async def put(self, url: str, entry: CacheEntry) -> CacheEntry | None:
        """
        插入或更新缓存条目。

        - 如果 URL 已存在，更新条目并移到末尾
        - 如果容量已满，淘汰最久未使用的条目

        Args:
            url: 请求 URL（缓存键）
            entry: 缓存条目

        Returns:
            被淘汰的 CacheEntry（如果有），否则 None
        """
        async with self._lock:
            evicted: CacheEntry | None = None

            if url in self._store:
                # 已存在 → 更新
                self._store[url] = entry
                self._store.move_to_end(url)
                return None

            # 容量检查 → 淘汰最久未使用
            if len(self._store) >= self._max_size:
                evicted_url, evicted = self._store.popitem(last=False)

            self._store[url] = entry
            return evicted

    async def remove(self, url: str) -> bool:
        """
        删除指定 URL 的缓存条目。

        Args:
            url: 要删除的 URL

        Returns:
            True 表示成功删除，False 表示条目不存在
        """
        async with self._lock:
            if url in self._store:
                del self._store[url]
                return True
            return False

    async def contains(self, url: str) -> bool:
        """
        检查 URL 是否在缓存中。

        Args:
            url: 请求 URL

        Returns:
            True 表示缓存中存在
        """
        async with self._lock:
            return url in self._store

    async def clear(self) -> int:
        """
        清空所有缓存条目。

        Returns:
            被清除的条目数量
        """
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    # ================================================================
    # 淘汰
    # ================================================================

    async def evict_expired(self, now: float | None = None) -> list[CacheEntry]:
        """
        淘汰所有已过期的缓存条目。

        遍历所有条目，删除 expires_at <= now 的。

        Args:
            now: 当前时间戳（默认使用 time.monotonic()）

        Returns:
            被淘汰的过期条目列表
        """
        current = now if now is not None else time.monotonic()
        async with self._lock:
            expired_urls = [
                url
                for url, entry in self._store.items()
                if entry.expires_at > 0 and current >= entry.expires_at
            ]
            expired_entries = [self._store[url] for url in expired_urls]
            for url in expired_urls:
                del self._store[url]
            return expired_entries

    async def evict_oldest(self, count: int = 1) -> list[CacheEntry]:
        """
        淘汰最旧的 N 条记录（LRU 顺序）。

        Args:
            count: 要淘汰的条目数

        Returns:
            被淘汰的条目列表
        """
        async with self._lock:
            evicted: list[CacheEntry] = []
            for _ in range(min(count, len(self._store))):
                _, entry = self._store.popitem(last=False)
                evicted.append(entry)
            return evicted

    # ================================================================
    # 查询 / 迭代
    # ================================================================

    async def get_all_entries(self) -> list[CacheEntry]:
        """
        获取所有缓存条目（快照）。

        Returns:
            所有条目的列表（按 LRU 顺序，从旧到新）
        """
        async with self._lock:
            return list(self._store.values())

    async def get_all_urls(self) -> list[str]:
        """
        获取所有缓存 URL。

        Returns:
            所有 URL 的列表
        """
        async with self._lock:
            return list(self._store.keys())

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"LRUCache(size={len(self._store)}, max_size={self._max_size})"
