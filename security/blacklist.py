"""
黑名单管理

黑名单中的 URL 模式匹配到的请求将被拒绝访问。
支持从配置文件加载、运行时增删、热加载。

Usage:
    blacklist = Blacklist()
    await blacklist.load_from_file()
    blocked, rule = blacklist.is_blocked("http://evil.com/tracker.js")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from security.base_list import BaseList

if TYPE_CHECKING:
    pass


class Blacklist(BaseList):
    """
    黑名单管理器。

    匹配语义: 如果 URL 匹配黑名单中的任意规则，请求被阻止。

    规则文件的每一行为一条规则，支持:
        - 精确域名: example.com
        - 子域名通配: *.example.com
        - 路径通配: example.com/ads/*
        - 正则表达式: /pattern/

    Runtime API (供 Dashboard 调用):
        await blacklist.add_rule("pattern")
        await blacklist.remove_rule("pattern")
        rules = blacklist.get_rules()
    """

    def __init__(self, file_path: str | Path | None = None) -> None:
        """
        Args:
            file_path: 黑名单文件路径，默认使用 config/settings.py 中的 BLACKLIST_PATH
        """
        if file_path is None:
            from config.settings import BLACKLIST_PATH
            file_path = BLACKLIST_PATH

        super().__init__(file_path=file_path, logger_name="blacklist")

    # ---- 公有 API ----

    def is_blocked(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否被黑名单阻止。

        Args:
            url: 完整的请求 URL

        Returns:
            (是否被阻止, 匹配到的规则字符串或 None)

        Example:
            >>> blacklist.is_blocked("http://evil.com/phishing")
            (True, "evil.com")
            >>> blacklist.is_blocked("http://safe-site.com")
            (False, None)
        """
        return self.is_match(url)

    def is_match(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否匹配黑名单规则。

        Args:
            url: 完整的请求 URL

        Returns:
            (是否匹配, 匹配到的规则或 None)
        """
        return self._engine.match(url)

    # ---- 便捷方法 ----

    def block_ip(self, ip: str) -> bool:
        """
        便捷方法：阻止指定 IP 地址。

        实际上添加精确匹配规则。

        Args:
            ip: IP 地址字符串

        Returns:
            True 如果成功添加
        """
        return self._engine.add_pattern(ip) is not None

    def block_domain(self, domain: str) -> bool:
        """
        便捷方法：阻止指定域名（包括所有子域名）。

        Args:
            domain: 域名字符串

        Returns:
            True 如果成功添加
        """
        # 添加精确域名匹配
        result1 = self._engine.add_pattern(domain)
        # 添加通配符子域名匹配
        result2 = self._engine.add_pattern(f"*.{domain}")
        return result1 is not None or result2 is not None

    def unblock(self, pattern: str) -> bool:
        """
        便捷方法：解除对指定模式的阻止。

        Args:
            pattern: 要移除的规则

        Returns:
            True 如果规则存在并被移除
        """
        return self._engine.remove_pattern(pattern)
