"""
组合访问控制

整合黑名单和白名单，提供统一的请求检查入口。
代理服务器在收到请求时首先调用 AccessControl.check() 判断是否允许访问。

决策优先级:
    1. 黑名单优先：命中黑名单 → 直接拒绝
    2. 白名单检查：白名单非空 → 检查是否匹配；白名单为空 → 放行
    3. 默认放行

Usage:
    ac = AccessControl()
    await ac.load_rules()
    decision = await ac.check("http://example.com/path")
    if not decision.allowed:
        return Response(403, body=decision.reason)
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from security.blacklist import Blacklist
from security.whitelist import Whitelist


@dataclass
class AccessDecision:
    """
    访问控制决策结果。

    Attributes:
        allowed: 是否允许访问
        reason: 人类可读的决策原因
        matched_rule: 触发的具体规则（如果有）
        rule_type: 规则类型 "blacklist" / "whitelist" / "default"
    """
    allowed: bool
    reason: str = ""
    matched_rule: str | None = None
    rule_type: str = "default"

    # 决策类型常量
    BLOCKED_BY_BLACKLIST: str = "blocked_by_blacklist"
    BLOCKED_BY_WHITELIST: str = "blocked_by_whitelist"
    ALLOWED_BY_WHITELIST: str = "allowed_by_whitelist"
    ALLOWED_DEFAULT: str = "allowed_default"


class AccessControl:
    """
    组合访问控制 — 代理服务器的安全入口。

    整合黑名单和白名单的检查逻辑：
        1. 先检查黑名单（匹配 → 拒绝）
        2. 再检查白名单（非空且不匹配 → 拒绝）
        3. 其余情况放行

    支持 Dashboard 集成：
        - CRUD 操作黑名单/白名单规则
        - 热加载规则
        - 查询状态
    """

    def __init__(
        self,
        blacklist: Blacklist | None = None,
        whitelist: Whitelist | None = None,
    ) -> None:
        """
        Args:
            blacklist: 黑名单实例（默认自动创建）
            whitelist: 白名单实例（默认自动创建）
        """
        self.blacklist = blacklist or Blacklist()
        self.whitelist = whitelist or Whitelist()
        self._logger = logger.bind(component="access_control")

    # ---- 核心 API ----

    async def check(self, url: str, client_ip: str | None = None) -> AccessDecision:
        """
        检查请求是否应该被允许。

        这是代理服务器在收到每个请求时调用的主要方法。

        决策流程:
            1. 黑名单检查 → 命中则拒绝
            2. 白名单检查 → 激活但不匹配则拒绝
            3. 默认放行

        Args:
            url: 完整的请求 URL
            client_ip: 客户端 IP（可选，用于日志记录）

        Returns:
            AccessDecision 决策结果

        Example:
            >>> decision = await ac.check("http://evil.com/js")
            >>> decision.allowed
            False
            >>> decision.reason
            'Blocked by blacklist: matched rule "*.evil.com"'
        """
        # ---- Step 1: 黑名单检查 ----
        is_blocked, matched_rule = self.blacklist.is_blocked(url)
        if is_blocked:
            reason = f'Blocked by blacklist: matched rule "{matched_rule}"'
            if client_ip:
                self._logger.warning(
                    "BLOCKED | client={} | url={} | rule=\"{}\" | type=blacklist",
                    client_ip, url, matched_rule,
                )
            else:
                self._logger.warning(
                    "BLOCKED | url={} | rule=\"{}\" | type=blacklist", url, matched_rule,
                )
            return AccessDecision(
                allowed=False,
                reason=reason,
                matched_rule=matched_rule,
                rule_type=AccessDecision.BLOCKED_BY_BLACKLIST,
            )

        # ---- Step 2: 白名单检查 ----
        is_allowed, matched_rule = self.whitelist.is_allowed(url)
        if not is_allowed:
            reason = "Blocked: URL not in whitelist"
            if client_ip:
                self._logger.warning(
                    "BLOCKED | client={} | url={} | type=whitelist (not matched)", client_ip, url,
                )
            else:
                self._logger.warning(
                    "BLOCKED | url={} | type=whitelist (not matched)", url,
                )
            return AccessDecision(
                allowed=False,
                reason=reason,
                matched_rule=None,
                rule_type=AccessDecision.BLOCKED_BY_WHITELIST,
            )

        # ---- Step 3: 放行 ----
        if matched_rule:
            # 白名单中有匹配的规则
            self._logger.debug("ALLOWED | url={} | matched_whitelist=\"{}\"", url, matched_rule)
            return AccessDecision(
                allowed=True,
                reason=f'Allowed by whitelist: matched rule "{matched_rule}"',
                matched_rule=matched_rule,
                rule_type=AccessDecision.ALLOWED_BY_WHITELIST,
            )
        else:
            # 白名单未激活，默认放行
            self._logger.debug("ALLOWED | url={} | type=default (whitelist inactive)", url)
            return AccessDecision(
                allowed=True,
                reason="Allowed (whitelist not active)",
                rule_type=AccessDecision.ALLOWED_DEFAULT,
            )

    # ---- 生命周期 ----

    async def load_rules(self) -> None:
        """从配置文件加载黑名单和白名单规则"""
        bl_count = await self.blacklist.load_from_file()
        wl_count = await self.whitelist.load_from_file()
        self._logger.info(
            "Access control initialized: {} blacklist rules, {} whitelist rules loaded",
            bl_count, wl_count,
        )

    async def reload(self) -> None:
        """热加载：清空并重新从文件加载所有规则"""
        await self.blacklist.reload()
        await self.whitelist.reload()

    # ---- Dashboard API ----

    async def add_blacklist_rule(self, pattern: str) -> bool:
        """添加黑名单规则"""
        result = await self.blacklist.add_rule(pattern)
        if result:
            self._logger.info("Blacklist rule added via API: {}", pattern)
        return result

    async def remove_blacklist_rule(self, pattern: str) -> bool:
        """删除黑名单规则"""
        result = await self.blacklist.remove_rule(pattern)
        if result:
            self._logger.info("Blacklist rule removed via API: {}", pattern)
        return result

    async def add_whitelist_rule(self, pattern: str) -> bool:
        """添加白名单规则"""
        result = await self.whitelist.add_rule(pattern)
        if result:
            self._logger.info("Whitelist rule added via API: {}", pattern)
        return result

    async def remove_whitelist_rule(self, pattern: str) -> bool:
        """删除白名单规则"""
        result = await self.whitelist.remove_rule(pattern)
        if result:
            self._logger.info("Whitelist rule removed via API: {}", pattern)
        return result

    async def save_rules(self) -> tuple[int, int]:
        """
        保存当前规则到文件。

        Returns:
            (blacklist_count, whitelist_count)
        """
        bl_count = await self.blacklist.save_to_file()
        wl_count = await self.whitelist.save_to_file()
        return bl_count, wl_count

    def get_status(self) -> dict:
        """
        获取访问控制状态（供 Dashboard API）。

        Returns:
            包含规则数量、规则列表、功能开关的字典
        """
        from config import settings
        return {
            "blacklist_enabled": settings.BLACKLIST_ENABLED,
            "whitelist_enabled": settings.WHITELIST_ENABLED,
            "blacklist_count": self.blacklist.count,
            "whitelist_count": self.whitelist.count,
            "blacklist_rules": self.blacklist.get_rules(),
            "whitelist_rules": self.whitelist.get_rules(),
            "blacklist_path": self.blacklist.file_path,
            "whitelist_path": self.whitelist.file_path,
        }
