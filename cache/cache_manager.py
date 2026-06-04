"""
缓存管理器 — 缓存模块主入口

集成 LRU 内存缓存和 TTL 过期控制，作为代理服务器的缓存层。
每个 HTTP 请求到达时，代理服务器调用 CacheManager 进行缓存查询和存储。

职责：
    1. 缓存查询（get）：查 LRU → 检查 TTL → 返回 CacheDecision
    2. 缓存存储（put）：构造 CacheEntry → 写入 LRU
    3. TTL 过期清理：惰性过期（查询时检查）+ 主动清理（evict_expired）
    4. 统计信息：命中/未命中计数、命中率、条目数、总大小

使用示例（在代理服务器中）：
    from cache import get_cache_manager

    cache_mgr = get_cache_manager()

    # 请求到达时
    decision = await cache_mgr.get(url)
    if decision.hit:
        return decision.entry  # 缓存命中，直接返回
    else:
        response = await forward_to_target(url)
        await cache_mgr.put(url, response_body, content_type, status_code)
        return response

配置来源（config/settings.py）：
    CACHE_TTL      — 默认 TTL（秒），默认 60
    CACHE_MAX_SIZE — 最大缓存条目数，默认 1000

Classes:
    CacheManager — 缓存管理器
    CacheStats   — 缓存统计信息
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from loguru import logger

from cache.cache_model import CacheEntry, CacheDecision
from cache.lru_cache import LRUCache
from config.settings import CACHE_TTL, CACHE_MAX_SIZE


@dataclass
class CacheStats:
    """
    缓存统计快照。

    Attributes:
        total_requests: 总查询次数（get 调用次数）
        hits: 命中次数
        misses: 未命中次数
        hit_rate: 命中率（0.0 ~ 1.0）
        entry_count: 当前缓存条目数
        total_size_bytes: 缓存内容总字节数
        max_size: 最大容量
        default_ttl: 默认 TTL（秒）
    """

    total_requests: int = 0
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    entry_count: int = 0
    total_size_bytes: int = 0
    max_size: int = 1000
    default_ttl: int = 60


class CacheManager:
    """
    缓存管理器 — 代理服务器缓存层的主入口。

    整合 LRU 淘汰和 TTL 过期：
        - get() → 从 LRU 查找 → 检查 TTL 过期 → 返回 CacheDecision
        - put() → 构造 CacheEntry → 写入 LRU（自动淘汰旧条目）
        - 惰性过期：查询时自动删除已过期的条目
        - 主动清理：支持按需/定时清理过期条目

    所有公开方法均为异步安全，可在协程中并发调用。
    """

    def __init__(
        self,
        ttl: int | None = None,
        max_size: int | None = None,
    ) -> None:
        """
        Args:
            ttl: 默认缓存 TTL（秒），None 则使用 config.settings.CACHE_TTL
            max_size: 最大缓存条目数，None 则使用 config.settings.CACHE_MAX_SIZE
        """
        self._ttl: int = ttl if ttl is not None else CACHE_TTL
        self._max_size: int = max_size if max_size is not None else CACHE_MAX_SIZE
        self._lru: LRUCache = LRUCache(max_size=self._max_size)

        # 统计计数器
        self._total_requests: int = 0
        self._hits: int = 0
        self._misses: int = 0

        # 是否启用缓存
        self._enabled: bool = True

        self._logger = logger.bind(component="cache_manager")

    # ================================================================
    # 属性
    # ================================================================

    @property
    def ttl(self) -> int:
        """默认 TTL（秒）。"""
        return self._ttl

    @property
    def max_size(self) -> int:
        """最大容量。"""
        return self._max_size

    @property
    def enabled(self) -> bool:
        """缓存是否启用。"""
        return self._enabled

    @property
    def entry_count(self) -> int:
        """当前缓存条目数。"""
        return len(self._lru)

    # ================================================================
    # 启用/禁用
    # ================================================================

    def enable(self) -> None:
        """启用缓存。"""
        self._enabled = True
        self._logger.info("Cache enabled")

    def disable(self) -> None:
        """禁用缓存（禁用后所有 get 返回 miss）。"""
        self._enabled = False
        self._logger.info("Cache disabled")

    # ================================================================
    # 核心 API：缓存查询
    # ================================================================

    async def get(self, url: str) -> CacheDecision:
        """
        查询缓存。

        流程：
            1. 缓存禁用 → 返回 miss
            2. 从 LRU 查找
            3. 未找到 → 返回 miss（not_found）
            4. 找到但已过期 → 惰性删除 → 返回 miss（expired）
            5. 找到且未过期 → 返回 hit（含 CacheEntry）

        Args:
            url: 请求的完整 URL

        Returns:
            CacheDecision（.hit=True 表示命中，.entry 为缓存内容）

        Example:
            >>> decision = await cache_mgr.get("http://example.com/api")
            >>> if decision:
            ...     content = decision.entry.content
        """
        self._total_requests += 1

        # 缓存禁用
        if not self._enabled:
            self._misses += 1
            return CacheDecision.miss(CacheDecision.CACHE_DISABLED)

        # LRU 查找
        entry = await self._lru.get(url)
        if entry is None:
            self._misses += 1
            return CacheDecision.miss(CacheDecision.NOT_FOUND)

        # 检查 TTL 过期（惰性删除）
        now = time.monotonic()
        if entry.is_expired(now):
            await self._lru.remove(url)
            self._misses += 1
            self._logger.debug(
                "Cache EXPIRED | url={} | cached_at={:.1f} | expires_at={:.1f}",
                url, entry.cached_at, entry.expires_at,
            )
            return CacheDecision.miss(CacheDecision.EXPIRED)

        # 命中
        self._hits += 1
        self._logger.debug("Cache HIT | url={} | size={} | access_count={}", url, entry.size, entry.access_count)
        return CacheDecision.found(entry)

    # ================================================================
    # 核心 API：缓存存储
    # ================================================================

    async def put(
        self,
        url: str,
        content: bytes,
        content_type: str = "",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        ttl: int | None = None,
    ) -> CacheEntry:
        """
        将响应内容存入缓存。

        自动处理：
            - 跳过空内容
            - 跳过已禁用的缓存
            - 计算过期时间
            - 容量满时自动 LRU 淘汰

        Args:
            url: 请求 URL（缓存键）
            content: 响应体
            content_type: Content-Type
            status_code: HTTP 状态码
            headers: 响应头
            ttl: 此条目的 TTL（秒），None 则使用默认 TTL

        Returns:
            新创建的 CacheEntry

        Example:
            >>> entry = await cache_mgr.put(
            ...     "http://example.com",
            ...     b"<html>...</html>",
            ...     content_type="text/html",
            ...     status_code=200,
            ... )
        """
        # 跳过空内容
        if not content:
            self._logger.debug("Cache SKIP (empty content) | url={}", url)
            return CacheEntry(url=url, content=b"")

        # 禁用时不写入
        if not self._enabled:
            self._logger.debug("Cache SKIP (disabled) | url={}", url)
            return CacheEntry(url=url, content=content)

        # 构造条目
        effective_ttl = ttl if ttl is not None else self._ttl
        now = time.monotonic()

        entry = CacheEntry(
            url=url,
            content=content,
            content_type=content_type,
            status_code=status_code,
            headers=headers or {},
            cached_at=now,
            expires_at=now + effective_ttl,
            access_count=0,
            size=len(content),
        )

        # 写入 LRU
        evicted = await self._lru.put(url, entry)

        if evicted:
            self._logger.debug(
                "Cache EVICT (LRU) | evicted_url={} | new_url={}",
                evicted.url, url,
            )

        self._logger.debug(
            "Cache PUT | url={} | size={} | ttl={}s | status={}",
            url, entry.size, effective_ttl, status_code,
        )
        return entry

    # ================================================================
    # 缓存管理
    # ================================================================

    async def remove(self, url: str) -> bool:
        """
        删除指定 URL 的缓存条目。

        Args:
            url: 要删除的 URL

        Returns:
            True 表示成功删除
        """
        removed = await self._lru.remove(url)
        if removed:
            self._logger.debug("Cache REMOVE | url={}", url)
        return removed

    async def clear(self) -> int:
        """
        清空所有缓存。

        Returns:
            被清除的条目数量
        """
        count = await self._lru.clear()
        self._logger.info("Cache CLEARED | {} entries removed", count)
        return count

    async def evict_expired(self) -> int:
        """
        主动清理所有过期条目。

        Returns:
            被清理的过期条目数量
        """
        expired = await self._lru.evict_expired()
        if expired:
            self._logger.info(
                "Cache EVICT_EXPIRED | {} entries (urls: {})",
                len(expired),
                [e.url for e in expired],
            )
        return len(expired)

    async def refresh_ttl(self, url: str, ttl: int | None = None) -> bool:
        """
        刷新指定缓存条目的 TTL（延长过期时间）。

        Args:
            url: 缓存 URL
            ttl: 新的 TTL（秒），None 则使用默认 TTL

        Returns:
            True 表示成功刷新
        """
        entry = await self._lru.get(url)
        if entry is None:
            return False

        effective_ttl = ttl if ttl is not None else self._ttl
        now = time.monotonic()
        entry.expires_at = now + effective_ttl
        self._logger.debug("Cache REFRESH_TTL | url={} | new_ttl={}s", url, effective_ttl)
        return True

    # ================================================================
    # 查询 / 统计
    # ================================================================

    async def get_stats(self) -> CacheStats:
        """
        获取缓存统计快照。

        Returns:
            CacheStats 包含命中率、条目数、总大小等信息
        """
        # 计算总大小
        entries = await self._lru.get_all_entries()
        total_size = sum(e.size for e in entries)

        hit_rate = (
            self._hits / self._total_requests
            if self._total_requests > 0
            else 0.0
        )

        return CacheStats(
            total_requests=self._total_requests,
            hits=self._hits,
            misses=self._misses,
            hit_rate=round(hit_rate, 4),
            entry_count=len(entries),
            total_size_bytes=total_size,
            max_size=self._max_size,
            default_ttl=self._ttl,
        )

    async def get_all_entries(self) -> list[CacheEntry]:
        """
        获取所有缓存条目列表（供 Dashboard 使用）。

        Returns:
            所有 CacheEntry 的列表
        """
        return await self._lru.get_all_entries()

    async def get_all_urls(self) -> list[str]:
        """
        获取所有缓存的 URL 列表。

        Returns:
            URL 字符串列表
        """
        return await self._lru.get_all_urls()

    async def contains(self, url: str) -> bool:
        """
        检查 URL 是否在缓存中（不更新 LRU 顺序，不检查过期）。

        Args:
            url: 请求 URL

        Returns:
            True 表示存在
        """
        return await self._lru.contains(url)

    def reset_stats(self) -> None:
        """重置统计计数器（不影响缓存内容）。"""
        self._total_requests = 0
        self._hits = 0
        self._misses = 0
        self._logger.info("Cache stats reset")

    # ================================================================
    # 配置
    # ================================================================

    def update_config(self, ttl: int | None = None, max_size: int | None = None) -> None:
        """
        运行时更新缓存配置。

        Args:
            ttl: 新的默认 TTL（秒）
            max_size: 新的最大容量

        Note:
            修改 max_size 不会立即淘汰条目。
            当下次 put 触发容量检查时，新限制生效。
        """
        if ttl is not None and ttl > 0:
            self._ttl = ttl
            self._logger.info("Cache TTL updated to {}s", ttl)
        if max_size is not None and max_size > 0:
            self._max_size = max_size
            self._lru._max_size = max_size
            self._logger.info("Cache max_size updated to {}", max_size)

    def __repr__(self) -> str:
        return (
            f"CacheManager(entries={self.entry_count}, "
            f"hits={self._hits}, misses={self._misses}, "
            f"enabled={self._enabled}, ttl={self._ttl}s)"
        )
