"""
缓存模块 — HTTP 代理服务器的缓存层

提供基于 LRU 淘汰和 TTL 过期的内存缓存。
代理服务器在请求处理中通过 CacheManager 查询和存储缓存。

主要类:
    CacheManager — 缓存管理器（代理服务器的入口点）
    CacheEntry   — 缓存条目数据模型
    CacheDecision — 缓存查询结果（命中/未命中）
    CacheStats   — 缓存统计快照
    LRUCache     — 底层 LRU 容器

使用示例:
    from cache import get_cache_manager

    cache_mgr = get_cache_manager()

    # 查询缓存
    decision = await cache_mgr.get("http://example.com/api")
    if decision.hit:
        return decision.entry.content

    # 存储缓存
    await cache_mgr.put(
        "http://example.com/api",
        content=response_body,
        content_type="application/json",
        status_code=200,
    )

    # 统计
    stats = await cache_mgr.get_stats()
    print(f"命中率: {stats.hit_rate:.2%}")
"""

from cache.cache_model import CacheEntry, CacheDecision
from cache.lru_cache import LRUCache
from cache.cache_manager import CacheManager, CacheStats

__all__ = [
    # 主入口
    "CacheManager",
    "CacheStats",
    # 数据模型
    "CacheEntry",
    "CacheDecision",
    # 底层容器
    "LRUCache",
    # 单例访问器
    "get_cache_manager",
    "reset_cache_manager",
]

# ============================================================
# 全局单例（供代理服务器和 Dashboard 共享）
# ============================================================

_cache_manager_instance: CacheManager | None = None


def get_cache_manager(
    ttl: int | None = None,
    max_size: int | None = None,
) -> CacheManager:
    """
    获取全局 CacheManager 单例。

    代理服务器和 Dashboard 通过此函数共享同一个缓存实例，
    确保缓存状态在两个组件间保持一致。

    首次调用时创建实例，后续调用返回同一个实例。
    可通过参数在首次创建时覆盖默认配置。

    Args:
        ttl: 默认 TTL（秒），仅在首次创建时生效
        max_size: 最大容量，仅在首次创建时生效

    Returns:
        全局唯一的 CacheManager 实例

    Example:
        >>> cache_mgr = get_cache_manager()
        >>> decision = await cache_mgr.get("http://example.com")
        >>> stats = await cache_mgr.get_stats()
    """
    global _cache_manager_instance
    if _cache_manager_instance is None:
        _cache_manager_instance = CacheManager(ttl=ttl, max_size=max_size)
    return _cache_manager_instance


def reset_cache_manager() -> None:
    """
    重置全局 CacheManager 单例。

    主要用于测试场景，生产环境一般不需要调用。
    调用后下次 get_cache_manager() 会创建新实例。
    """
    global _cache_manager_instance
    _cache_manager_instance = None
