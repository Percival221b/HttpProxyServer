"""
模式匹配引擎

提供 URL 模式匹配的核心算法，支持四种匹配类型：
  - EXACT:       精确域名/路径匹配 (example.com)
  - WILDCARD:    子域名通配符匹配 (*.example.com)
  - PATH_WILDCARD: 路径前缀匹配 (example.com/ads/*)
  - REGEX:       正则表达式匹配 (/pattern/)

线程安全：写操作（add/remove/clear）通过 copy-on-write 实现，读操作（match）无锁。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache
from urllib.parse import urlparse
from typing import ClassVar


class PatternType(Enum):
    """模式类型枚举"""
    EXACT = auto()        # 精确匹配: example.com
    WILDCARD = auto()     # 通配符: *.example.com
    PATH_WILDCARD = auto()  # 路径通配符: example.com/path/*
    REGEX = auto()        # 正则表达式: /pattern/


@dataclass(frozen=True, slots=True)
class CompiledPattern:
    """编译后的单条匹配规则"""
    raw: str                        # 原始字符串
    type: PatternType               # 模式类型
    regex: re.Pattern | None = None # 编译后的正则（WILDCARD / REGEX 使用）
    domain: str | None = None       # 域名部分（EXACT / PATH_WILDCARD 使用）
    path_prefix: str | None = None  # 路径前缀（PATH_WILDCARD 使用）

    def to_dict(self) -> dict:
        """序列化为字典（供 Dashboard API 使用）"""
        return {
            "raw": self.raw,
            "type": self.type.name.lower(),
        }


@dataclass
class _EngineState:
    """引擎内部状态（用于 copy-on-write）"""
    exact_domains: set[str] = field(default_factory=set)
    exact_paths: set[str] = field(default_factory=set)
    compiled_list: list[CompiledPattern] = field(default_factory=list)
    count: int = 0


class PatternEngine:
    """
    模式匹配引擎

    编译并匹配 URL 模式规则。支持四种模式类型的添加、删除和批量匹配。

    Usage:
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        engine.add_pattern("/^.*evil.*$/")
        is_match, matched = engine.match("http://sub.example.com/path")
    """

    # 用于检测正则模式的前后缀
    REGEX_DELIMITER: ClassVar[str] = "/"

    # 通配符域名验证正则：*.example.com
    WILDCARD_DOMAIN_RE: ClassVar[re.Pattern] = re.compile(
        r'^\*\.([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.'
        r'[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)$'
    )

    def __init__(self) -> None:
        self._state = _EngineState()

    # ---- 公有 API ----

    def add_pattern(self, raw: str) -> CompiledPattern | None:
        """
        添加一条匹配规则。

        Args:
            raw: 原始规则字符串

        Returns:
            CompiledPattern（成功）或 None（规则已存在/无效）
        """
        raw = raw.strip()
        if not raw:
            return None

        compiled = self._compile(raw)
        if compiled is None:
            return None

        state = self._state

        # 检查是否已存在 + 构建新状态
        if compiled.type == PatternType.EXACT:
            if compiled.path_prefix:
                # 域名+路径精确匹配，如 example.com/special/path
                key = (compiled.domain or "") + (compiled.path_prefix or "")
                if key in state.exact_paths:
                    return None
                new_exact_paths = set(state.exact_paths)
                new_exact_paths.add(key)
                new_exact_domains = set(state.exact_domains)
            else:
                # 纯域名精确匹配，如 example.com
                key = compiled.domain or compiled.raw
                if key in state.exact_domains:
                    return None
                new_exact_domains = set(state.exact_domains)
                new_exact_domains.add(key)
                new_exact_paths = set(state.exact_paths)

            # Copy-on-write：原子替换
            self._state = _EngineState(
                exact_domains=new_exact_domains,
                exact_paths=new_exact_paths,
                compiled_list=list(state.compiled_list),
                count=len(new_exact_domains) + len(new_exact_paths) + len(state.compiled_list),
            )
        else:
            # 检查是否在编译列表中已存在
            for existing in state.compiled_list:
                if existing.raw == raw:
                    return None
            new_compiled = list(state.compiled_list)
            new_compiled.append(compiled)

            # Copy-on-write：原子替换
            self._state = _EngineState(
                exact_domains=set(state.exact_domains),
                exact_paths=set(state.exact_paths),
                compiled_list=new_compiled,
                count=len(state.exact_domains) + len(state.exact_paths) + len(new_compiled),
            )

        return compiled

    def remove_pattern(self, raw: str) -> bool:
        """
        移除一条匹配规则。

        Returns:
            True 如果规则存在并被移除
        """
        raw = raw.strip()
        if not raw:
            return False

        state = self._state

        # 尝试从 exact 集合中移除
        new_exact_domains = set(state.exact_domains)
        new_exact_paths = set(state.exact_paths)
        new_compiled = list(state.compiled_list)
        removed = False

        if raw in new_exact_domains:
            new_exact_domains.discard(raw)
            removed = True
        elif raw in new_exact_paths:
            new_exact_paths.discard(raw)
            removed = True
        else:
            # 尝试从编译列表中移除
            new_compiled = [p for p in state.compiled_list if p.raw != raw]
            if len(new_compiled) != len(state.compiled_list):
                removed = True

        if not removed:
            return False

        self._state = _EngineState(
            exact_domains=new_exact_domains,
            exact_paths=new_exact_paths,
            compiled_list=new_compiled,
            count=len(new_exact_domains) + len(new_exact_paths) + len(new_compiled),
        )
        return True

    def match(self, url: str) -> tuple[bool, str | None]:
        """
        检查 URL 是否匹配任何规则。

        Args:
            url: 完整的 URL 字符串

        Returns:
            (是否匹配, 匹配到的原始规则字符串或 None)
        """
        state = self._state  # 读取引用（无需加锁）
        host, path = _parse_url(url)

        # 1. 快速路径：O(1) 精确匹配
        if host in state.exact_domains:
            return True, host

        if host + path in state.exact_paths:
            return True, host + path

        # 2. 遍历编译后的正则列表
        for pattern in state.compiled_list:
            if pattern.type == PatternType.REGEX or pattern.type == PatternType.WILDCARD:
                if pattern.regex and pattern.regex.search(url):
                    return True, pattern.raw
            elif pattern.type == PatternType.PATH_WILDCARD:
                if pattern.domain == host:
                    prefix = pattern.path_prefix or ""
                    if path.startswith(prefix):
                        return True, pattern.raw

        return False, None

    def clear(self) -> None:
        """清空所有规则"""
        self._state = _EngineState()

    @property
    def count(self) -> int:
        """当前规则总数"""
        return self._state.count

    def get_patterns(self) -> list[dict]:
        """
        获取所有规则的列表（供 Dashboard 展示）。

        Returns:
            list[dict]: 每条规则包含 raw 和 type 字段
        """
        state = self._state
        result = []

        for domain in sorted(state.exact_domains):
            result.append({"raw": domain, "type": "exact"})
        for path_val in sorted(state.exact_paths):
            result.append({"raw": path_val, "type": "exact"})
        for pattern in state.compiled_list:
            result.append(pattern.to_dict())

        return result

    def get_rules_raw(self) -> list[str]:
        """获取所有规则的原始字符串列表"""
        state = self._state
        rules = list(state.exact_domains)
        rules.extend(state.exact_paths)
        rules.extend(p.raw for p in state.compiled_list)
        return rules

    # ---- 内部方法 ----

    def _compile(self, raw: str) -> CompiledPattern | None:
        """将原始规则字符串编译为 CompiledPattern"""
        # 正则模式：以 / 开头和结尾
        if raw.startswith(self.REGEX_DELIMITER) and raw.endswith(self.REGEX_DELIMITER) and len(raw) > 2:
            regex_str = raw[1:-1]
            try:
                compiled_re = re.compile(regex_str, re.IGNORECASE)
            except re.error:
                return None
            return CompiledPattern(raw=raw, type=PatternType.REGEX, regex=compiled_re)

        # 子域名通配符：*.example.com
        if raw.startswith("*."):
            domain = raw[2:]
            if self.WILDCARD_DOMAIN_RE.match(raw):
                # 构建匹配 *.domain 的正则
                # 至少匹配一层子域名（使用 + 而非 *，确保不匹配裸域名）
                escaped = re.escape(domain)
                # 匹配: scheme://sub.domain[:port][/path] — 至少一层子域名
                regex_str = (
                    r'^https?://'
                    r'([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+'
                    + escaped +
                    r'(:\d+)?(/.*)?$'
                )
                try:
                    compiled_re = re.compile(regex_str, re.IGNORECASE)
                except re.error:
                    return None
                return CompiledPattern(raw=raw, type=PatternType.WILDCARD, regex=compiled_re)
            # 如果不匹配标准格式，当作通用通配符处理
            escaped = re.escape(raw).replace(r'\*', r'[^\s/]+')
            try:
                compiled_re = re.compile(escaped, re.IGNORECASE)
            except re.error:
                return None
            return CompiledPattern(raw=raw, type=PatternType.WILDCARD, regex=compiled_re)

        # 路径通配符：domain.com/path/*
        if "/*" in raw:
            idx = raw.index("/*")
            domain_part = raw[:idx]

            # 如果 domain_part 包含 / ，说明是域名+路径前缀
            if "/" in domain_part:
                host, _, prefix = domain_part.partition("/")
                return CompiledPattern(
                    raw=raw,
                    type=PatternType.PATH_WILDCARD,
                    domain=host.lower(),
                    path_prefix="/" + prefix,
                )
            else:
                # 只有域名，如 example.com/*
                return CompiledPattern(
                    raw=raw,
                    type=PatternType.PATH_WILDCARD,
                    domain=domain_part.lower(),
                    path_prefix="/",
                )

        # 包含通配符 *（非标准位置）
        if "*" in raw:
            escaped = re.escape(raw).replace(r'\*', r'[^\s/]+')
            try:
                compiled_re = re.compile(escaped, re.IGNORECASE)
            except re.error:
                return None
            return CompiledPattern(raw=raw, type=PatternType.WILDCARD, regex=compiled_re)

        # 精确匹配：区分纯域名和域名+路径
        if "/" in raw and not raw.startswith("http"):
            host, _, path = raw.partition("/")
            return CompiledPattern(
                raw=raw,
                type=PatternType.EXACT,
                domain=host.lower(),
                path_prefix="/" + path,
            )

        # 纯域名精确匹配
        return CompiledPattern(
            raw=raw,
            type=PatternType.EXACT,
            domain=raw.lower(),
        )


# ---- 工具函数 ----

@lru_cache(maxsize=2048)
def _parse_url(url: str) -> tuple[str, str]:
    """
    解析 URL，提取 host（小写）和 path 部分。

    对于缺少 scheme 的 URL，自动补全。

    Returns:
        (host, path) 二元组
    """
    if "://" not in url:
        url = "http://" + url
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
        return host, path
    except Exception:
        return url.lower(), "/"
