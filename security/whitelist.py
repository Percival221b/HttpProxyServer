"""
白名单管理

白名单用于限制代理只能访问指定的域名/URL。
- 白名单为空时：允许所有请求（黑名单另有限制的除外）
- 白名单非空时：仅允许匹配白名单规则的请求

支持从配置文件加载、运行时增删、热加载。

Usage:
    whitelist = Whitelist()
    await whitelist.load_from_file()
    allowed, rule = whitelist.is_allowed("http://allowed-site.com/page")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from security.base_list import BaseList

if TYPE_CHECKING:
    pass


class Whitelist(BaseList):
    """
    白名单管理器。

    匹配语义:
        - 白名单为空（未激活）: 所有请求都允许通过
        - 白名单非空（激活）: 仅允许匹配白名单规则的请求

    规则文件的每一行为一条规则，支持:
        - 精确域名: company.com
        - 子域名通配: *.company.com
        - 路径通配: company.com/api/*
        - 正则表达式: /pattern/

    Runtime API (供 Dashboard 调用):
        await whitelist.add_rule("pattern")
        await whitelist.remove_rule("pattern")
        rules = whitelist.get_rules()
    """

    def __init__(self, file_path: str | Path | None = None) -> None:
        """
        Args:
            file_path: 白名单文件路径，默认使用 config/settings.py 中的 WHITELIST_PATH
        """
        if file_path is None:
            from config.settings import WHITELIST_PATH
            file_path = WHITELIST_PATH

        super().__init__(file_path=file_path, logger_name="whitelist")

    # ---- 公有 API ----

    def is_allowed(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否被白名单允许。

        若白名单为空（未激活），始终返回 (True, None)。

        Args:
            url: 完整的请求 URL

        Returns:
            (是否允许, 匹配到的规则字符串或 None)

        Example:
            >>> whitelist.is_allowed("http://company.com")  # 白名单非空且匹配
            (True, "company.com")
            >>> whitelist.is_allowed("http://other.com")    # 白名单非空但不匹配
            (False, None)
            >>> whitelist.is_allowed("http://any.com")      # 白名单为空
            (True, None)
        """
        return self.is_match(url)

    def is_match(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否匹配白名单规则。

        若白名单为空（未激活），始终返回 (True, None) — 全部放行。

        Args:
            url: 完整的请求 URL

        Returns:
            (是否匹配/允许, 匹配到的规则或 None)
        """
        if not self.is_active:
            # 白名单未激活 → 全部放行
            return True, None

        return self._engine.match(url)

    # ---- 便捷方法 ----

    def allow_domain(self, domain: str) -> bool:
        """
        便捷方法：允许指定域名（包括所有子域名）。

        Args:
            domain: 域名字符串

        Returns:
            True 如果成功添加
        """
        result1 = self._engine.add_pattern(domain)
        result2 = self._engine.add_pattern(f"*.{domain}")
        return result1 is not None or result2 is not None

    def disallow(self, pattern: str) -> bool:
        """
        便捷方法：移除白名单中的指定规则。

        Args:
            pattern: 要移除的规则

        Returns:
            True 如果规则存在并被移除
        """
        return self._engine.remove_pattern(pattern)
