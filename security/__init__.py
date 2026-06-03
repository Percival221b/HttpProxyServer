"""
Security 模块 — HTTP 代理服务器的访问控制

提供黑名单和白名单功能，拦截或放行请求。
在代理服务器请求处理流水线中作为第一道关卡。

主要类:
    AccessControl  — 组合访问控制（代理服务器的入口点）
    Blacklist      — 黑名单管理器
    Whitelist      — 白名单管理器
    AccessDecision — 访问决策结果
    PatternEngine  — 模式匹配引擎

Usage:
    from security import AccessControl, get_access_control

    # 方式1：直接创建
    ac = AccessControl()
    await ac.load_rules()
    decision = await ac.check("http://example.com/path")

    # 方式2：使用全局单例
    ac = get_access_control()
    await ac.load_rules()
"""

from security.pattern_engine import PatternEngine, PatternType, CompiledPattern
from security.base_list import BaseList
from security.blacklist import Blacklist
from security.whitelist import Whitelist
from security.access_control import AccessControl, AccessDecision

__all__ = [
    # 主入口
    "AccessControl",
    "AccessDecision",
    # 列表管理器
    "Blacklist",
    "Whitelist",
    # 底层引擎
    "PatternEngine",
    "PatternType",
    "CompiledPattern",
    # 基类
    "BaseList",
    # 单例访问器
    "get_access_control",
]

# ============================================================
# 全局单例（供代理服务器和 Dashboard 共享）
# ============================================================

_access_control_instance: AccessControl | None = None


def get_access_control() -> AccessControl:
    """
    获取全局 AccessControl 单例。

    代理服务器和 Dashboard 通过此函数共享同一个访问控制实例，
    确保规则修改在两个组件间保持一致。

    Returns:
        全局唯一的 AccessControl 实例

    Example:
        >>> ac = get_access_control()
        >>> await ac.load_rules()
        >>> decision = await ac.check("http://example.com")
    """
    global _access_control_instance
    if _access_control_instance is None:
        _access_control_instance = AccessControl()
    return _access_control_instance


def reset_access_control() -> None:
    """
    重置全局 AccessControl 单例。

    主要用于测试场景，生产环境一般不需要调用。
    """
    global _access_control_instance
    _access_control_instance = None
