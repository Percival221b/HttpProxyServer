"""
抽象基类 - 黑名单/白名单的公共逻辑

提供文件读写、异步锁保护、规则增删查、热加载等公共功能。
Blacklist 和 Whitelist 继承此类，仅需实现各自的匹配语义。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from security.pattern_engine import PatternEngine


class BaseList(ABC):
    """
    访问控制列表的抽象基类。

    子类需要实现:
        - is_blocked(url) 或 is_allowed(url) —— 匹配语义

    公共功能:
        - 从文件加载规则
        - 保存规则到文件
        - 运行时添加/删除规则
        - 热加载（清空并重新加载）
        - 获取规则列表
    """

    def __init__(self, file_path: str | Path, logger_name: str) -> None:
        """
        Args:
            file_path: 规则文件路径
            logger_name: 日志组件名称（如 "blacklist" / "whitelist"）
        """
        self._file_path = Path(file_path)
        self._engine = PatternEngine()
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component=logger_name)

    # ---- 属性 ----

    @property
    def count(self) -> int:
        """当前规则总数"""
        return self._engine.count

    @property
    def is_active(self) -> bool:
        """是否有激活的规则"""
        return self._engine.count > 0

    @property
    def file_path(self) -> str:
        """规则文件路径"""
        return str(self._file_path)

    # ---- 文件 I/O ----

    async def load_from_file(self) -> int:
        """
        从配置文件加载规则（不清空已有规则，追加模式）。

        Returns:
            成功加载的规则数量
        """
        async with self._lock:
            return self._load_from_file_sync()

    async def reload(self) -> int:
        """
        热加载：清空所有规则，重新从文件加载。

        Returns:
            加载的规则数量
        """
        async with self._lock:
            self._engine.clear()
            count = self._load_from_file_sync()
            self._logger.info("Rules reloaded: {} patterns loaded from {}", count, self._file_path)
            return count

    async def save_to_file(self) -> int:
        """
        将当前内存中的规则保存到配置文件。

        Returns:
            写入的规则数量
        """
        async with self._lock:
            rules = self._engine.get_rules_raw()
            try:
                self._file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._file_path, "w", encoding="utf-8") as f:
                    f.write("# Access Control Rules\n")
                    f.write(f"# Total: {len(rules)} rules\n")
                    f.write("# Last updated: auto-generated\n\n")
                    for rule in rules:
                        f.write(rule + "\n")
                self._logger.info("Saved {} rules to {}", len(rules), self._file_path)
                return len(rules)
            except OSError as e:
                self._logger.error("Failed to save rules to {}: {}", self._file_path, e)
                raise

    # ---- 运行时规则管理 ----

    async def add_rule(self, pattern: str) -> bool:
        """
        运行时添加一条规则（同时保存到文件）。

        Args:
            pattern: 规则字符串

        Returns:
            True 如果添加成功（新规则），False 如果规则已存在
        """
        async with self._lock:
            result = self._engine.add_pattern(pattern)
            if result is not None:
                self._logger.info("Rule added: {}", pattern)
                return True
            self._logger.debug("Rule already exists, skipped: {}", pattern)
            return False

    async def remove_rule(self, pattern: str) -> bool:
        """
        运行时删除一条规则（同时保存到文件）。

        Args:
            pattern: 规则字符串

        Returns:
            True 如果规则被移除，False 如果规则不存在
        """
        async with self._lock:
            result = self._engine.remove_pattern(pattern)
            if result:
                self._logger.info("Rule removed: {}", pattern)
                return True
            self._logger.debug("Rule not found, cannot remove: {}", pattern)
            return False

    # ---- 查询 ----

    def get_rules(self) -> list[dict]:
        """获取所有规则的列表（供 Dashboard 展示）"""
        return self._engine.get_patterns()

    def get_rules_raw(self) -> list[str]:
        """获取所有规则的原始字符串列表"""
        return self._engine.get_rules_raw()

    # ---- 内部方法 ----

    def _load_from_file_sync(self) -> int:
        """
        同步方式从文件加载规则（调用方已持有锁）。

        Returns:
            成功加载的规则数量
        """
        if not self._file_path.exists():
            self._logger.warning("Rules file not found: {}", self._file_path)
            return 0

        count = 0
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    parsed = self._parse_line(line)
                    if parsed is None:
                        continue
                    result = self._engine.add_pattern(parsed)
                    if result is not None:
                        count += 1
                    else:
                        self._logger.warning(
                            "Invalid or duplicate rule at line {}: '{}'",
                            line_num, parsed,
                        )
            self._logger.info("Loaded {} rules from {}", count, self._file_path)
        except OSError as e:
            self._logger.error("Failed to read rules from {}: {}", self._file_path, e)
            return 0

        return count

    @staticmethod
    def _parse_line(line: str) -> str | None:
        """
        解析文件中的一行。

        - 去除首尾空白
        - 跳过空行
        - 跳过以 # 开头的注释行
        - 处理行尾注释（# 后面的内容视为注释，但 # 前有内容则保留）

        Returns:
            解析后的规则字符串，或 None（跳过该行）
        """
        stripped = line.strip()

        if not stripped:
            return None

        # 注释行
        if stripped.startswith("#"):
            return None

        # 处理行内注释：找到第一个不在正则表达式内的 #
        # 规则：如果行以 / 开头则是正则，不处理内联注释
        if not stripped.startswith("/"):
            comment_idx = stripped.find(" #")
            if comment_idx != -1:
                stripped = stripped[:comment_idx].strip()
                if not stripped:
                    return None

        return stripped

    # ---- 抽象方法（子类实现） ----

    @abstractmethod
    def is_match(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否匹配列表中的规则。

        子类实现各自的语义：
            Blacklist.is_match → (blocked, matched_rule)
            Whitelist.is_match → (allowed, matched_rule)

        Args:
            url: 要检查的完整 URL

        Returns:
            (是否匹配, 匹配到的规则或 None)
        """
        ...
