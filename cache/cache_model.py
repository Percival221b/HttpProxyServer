"""
缓存数据模型

定义缓存条目和缓存查询结果的数据结构。
供 cache_manager 和 lru_cache 使用，也暴露给代理服务器用于判断缓存命中/未命中。

Classes:
    CacheEntry   — 缓存条目，保存完整的响应信息
    CacheDecision — 缓存查询结果（命中/未命中 + 原因）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """
    单条缓存记录。

    保存 HTTP 响应的完整信息，包括内容、头、状态码等。
    同时记录缓存元数据（创建时间、过期时间、访问次数等）。

    Attributes:
        url: 请求的完整 URL（缓存键）
        content: 响应体（字节串）
        content_type: Content-Type 头（如 "text/html; charset=utf-8"）
        status_code: HTTP 状态码
        headers: 响应头字典
        cached_at: 缓存创建时间戳（time.monotonic，用于 TTL 判断）
        expires_at: 过期时间戳（cached_at + ttl）
        access_count: 被访问的次数（用于统计）
        size: 响应体大小（字节数）
    """

    url: str
    content: bytes = b""
    content_type: str = ""
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    cached_at: float = 0.0
    expires_at: float = 0.0
    access_count: int = 0
    size: int = 0

    def __post_init__(self) -> None:
        if self.size == 0 and self.content:
            self.size = len(self.content)

    def is_expired(self, now: float | None = None) -> bool:
        """
        判断缓存是否已过期。

        Args:
            now: 当前时间戳（默认使用 time.monotonic()）

        Returns:
            True 表示已过期
        """
        import time

        current = now if now is not None else time.monotonic()
        return current >= self.expires_at

    def ttl_remaining(self, now: float | None = None) -> float:
        """
        剩余生存时间（秒）。

        Args:
            now: 当前时间戳

        Returns:
            剩余秒数，已过期时返回 0
        """
        import time

        current = now if now is not None else time.monotonic()
        remaining = self.expires_at - current
        return max(0.0, remaining)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（不含 content 二进制数据，供 API 返回）。"""
        return {
            "url": self.url,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "headers": self.headers,
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "size": self.size,
        }

    def __repr__(self) -> str:
        return (
            f"CacheEntry(url={self.url!r}, status={self.status_code}, "
            f"size={self.size}, access_count={self.access_count})"
        )


@dataclass
class CacheDecision:
    """
    缓存查询结果。

    代理服务器根据此结果决定是直接返回缓存内容还是转发请求。

    Attributes:
        hit: 是否命中缓存（True=命中，可直接返回；False=未命中，需转发）
        entry: 命中的缓存条目（hit=True 时有效）
        reason: 未命中原因（如 "not_found", "expired", "cache_disabled"）

    Example:
        >>> decision = await cache_manager.get("http://example.com")
        >>> if decision.hit:
        ...     return decision.entry.content
        ... else:
        ...     response = await forward_request(url)
        ...     await cache_manager.put(url, response)
    """

    hit: bool
    entry: CacheEntry | None = None
    reason: str = ""

    # ---- 未命中原因常量 ----
    NOT_FOUND: str = "not_found"
    EXPIRED: str = "expired"
    CACHE_DISABLED: str = "cache_disabled"
    EMPTY_CONTENT: str = "empty_content"

    @classmethod
    def miss(cls, reason: str = "") -> CacheDecision:
        """快捷构造：缓存未命中。"""
        return cls(hit=False, reason=reason)

    @classmethod
    def found(cls, entry: CacheEntry) -> CacheDecision:
        """快捷构造：缓存命中（同时递增访问计数）。"""
        entry.access_count += 1
        return cls(hit=True, entry=entry)

    def __bool__(self) -> bool:
        return self.hit
