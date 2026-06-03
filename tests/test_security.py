"""
Security 模块的全面测试

覆盖：
    - PatternEngine: 四种模式匹配 + 边界情况
    - Blacklist: 加载/匹配/增删
    - Whitelist: 空列表语义/匹配/增删
    - AccessControl: 组合优先级/热加载
    - 并发访问安全

运行方式:
    pytest tests/test_security.py -v
    pytest tests/test_security.py -v -k "test_pattern"  # 仅运行模式匹配测试
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from security.pattern_engine import PatternEngine, PatternType, CompiledPattern
from security.blacklist import Blacklist
from security.whitelist import Whitelist
from security.access_control import AccessControl, AccessDecision


# ============================================================
# 测试辅助函数
# ============================================================

def create_temp_rules_file(rules: list[str]) -> str:
    """创建一个临时规则文件并返回路径"""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    for rule in rules:
        tmp.write(rule + "\n")
    tmp.close()
    return tmp.name


# ============================================================
# PatternEngine 测试
# ============================================================

class TestPatternExact:
    """精确匹配测试"""

    def test_exact_domain_match(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        matched, rule = engine.match("http://example.com/path")
        assert matched is True
        assert rule == "example.com"

    def test_exact_domain_match_https(self):
        engine = PatternEngine()
        engine.add_pattern("secure.com")
        matched, rule = engine.match("https://secure.com/page")
        assert matched is True

    def test_exact_domain_no_match(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        matched, rule = engine.match("http://other.com")
        assert matched is False

    def test_exact_domain_subdomain_no_match(self):
        """精确匹配不应匹配子域名"""
        engine = PatternEngine()
        engine.add_pattern("example.com")
        matched, rule = engine.match("http://sub.example.com/path")
        assert matched is False

    def test_exact_domain_with_port(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        matched, rule = engine.match("http://example.com:8080/path")
        assert matched is True

    def test_exact_domain_case_insensitive(self):
        engine = PatternEngine()
        engine.add_pattern("Example.COM")
        matched, rule = engine.match("http://EXAMPLE.com/path")
        assert matched is True

    def test_exact_path_match(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/special/path")
        matched, rule = engine.match("http://example.com/special/path")
        assert matched is True

    def test_exact_path_no_match(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/special/path")
        matched, rule = engine.match("http://example.com/other/path")
        assert matched is False

    def test_multiple_exact_domains(self):
        engine = PatternEngine()
        engine.add_pattern("site1.com")
        engine.add_pattern("site2.com")
        engine.add_pattern("site3.com")
        assert engine.count == 3
        assert engine.match("http://site2.com/path") == (True, "site2.com")
        assert engine.match("http://site1.com") == (True, "site1.com")
        assert engine.match("http://unknown.com") == (False, None)


class TestPatternWildcard:
    """通配符匹配测试"""

    def test_wildcard_subdomain_match(self):
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        matched, rule = engine.match("http://sub.example.com/path")
        assert matched is True
        assert rule == "*.example.com"

    def test_wildcard_multi_level_subdomain(self):
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        matched, rule = engine.match("http://a.b.example.com/path")
        assert matched is True

    def test_wildcard_no_match_root_domain(self):
        """*.example.com 不匹配 example.com 本身"""
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        matched, rule = engine.match("http://example.com/path")
        assert matched is False

    def test_wildcard_no_match_different_domain(self):
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        matched, rule = engine.match("http://other.com/path")
        assert matched is False

    def test_wildcard_https_match(self):
        engine = PatternEngine()
        engine.add_pattern("*.cdn.net")
        matched, rule = engine.match("https://assets.cdn.net/image.png")
        assert matched is True

    def test_wildcard_with_port(self):
        engine = PatternEngine()
        engine.add_pattern("*.example.com")
        matched, rule = engine.match("http://sub.example.com:3000/api")
        assert matched is True


class TestPatternPathWildcard:
    """路径通配符匹配测试"""

    def test_path_wildcard_match(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/ads/*")
        matched, rule = engine.match("http://example.com/ads/banner.jpg")
        assert matched is True

    def test_path_wildcard_nested_path(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/ads/*")
        matched, rule = engine.match("http://example.com/ads/deep/nested/file.js")
        assert matched is True

    def test_path_wildcard_no_match_different_path(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/ads/*")
        matched, rule = engine.match("http://example.com/content/page.html")
        assert matched is False

    def test_path_wildcard_no_match_different_domain(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/ads/*")
        matched, rule = engine.match("http://other.com/ads/banner.jpg")
        assert matched is False

    def test_path_wildcard_root_path(self):
        """domain.com/* 匹配所有路径"""
        engine = PatternEngine()
        engine.add_pattern("site.com/*")
        matched, rule = engine.match("http://site.com/any/path")
        assert matched is True


class TestPatternRegex:
    """正则表达式匹配测试"""

    def test_regex_simple_match(self):
        engine = PatternEngine()
        engine.add_pattern("/evil/")
        matched, rule = engine.match("http://evil.com/phishing")
        assert matched is True

    def test_regex_anchored_match(self):
        engine = PatternEngine()
        engine.add_pattern("/^.*\\.adserver\\d*\\.com/")
        matched, rule = engine.match("http://tracker.adserver123.com/page")
        assert matched is True

    def test_regex_no_match(self):
        engine = PatternEngine()
        engine.add_pattern("/evil/")
        matched, rule = engine.match("http://good.com/safe")
        assert matched is False

    def test_regex_case_insensitive(self):
        engine = PatternEngine()
        engine.add_pattern("/SpAm/")
        matched, rule = engine.match("http://SPAM.com/page")
        assert matched is True

    def test_invalid_regex(self):
        engine = PatternEngine()
        result = engine.add_pattern("/[invalid(regex/")
        assert result is None
        assert engine.count == 0


class TestPatternEngineManagement:
    """模式引擎管理操作测试"""

    def test_add_duplicate_pattern(self):
        engine = PatternEngine()
        result1 = engine.add_pattern("example.com")
        result2 = engine.add_pattern("example.com")
        assert result1 is not None
        assert result2 is None
        assert engine.count == 1

    def test_remove_existing_pattern(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        result = engine.remove_pattern("example.com")
        assert result is True
        assert engine.count == 0

    def test_remove_nonexistent_pattern(self):
        engine = PatternEngine()
        result = engine.remove_pattern("nope.com")
        assert result is False

    def test_remove_wildcard_pattern(self):
        engine = PatternEngine()
        engine.add_pattern("*.evil.com")
        assert engine.count == 1
        result = engine.remove_pattern("*.evil.com")
        assert result is True
        assert engine.count == 0

    def test_remove_regex_pattern(self):
        engine = PatternEngine()
        engine.add_pattern("/spam/")
        assert engine.count == 1
        result = engine.remove_pattern("/spam/")
        assert result is True
        assert engine.count == 0

    def test_clear_all(self):
        engine = PatternEngine()
        engine.add_pattern("a.com")
        engine.add_pattern("*.b.com")
        engine.add_pattern("/c/")
        assert engine.count == 3
        engine.clear()
        assert engine.count == 0

    def test_get_patterns(self):
        engine = PatternEngine()
        engine.add_pattern("*.evil.com")
        engine.add_pattern("safe.com")
        patterns = engine.get_patterns()
        assert len(patterns) == 2
        types = {p["type"] for p in patterns}
        assert types == {"exact", "wildcard"}

    def test_empty_engine(self):
        engine = PatternEngine()
        assert engine.count == 0
        assert engine.match("http://anything.com") == (False, None)
        assert engine.get_patterns() == []


class TestPatternEdgeCases:
    """边界情况测试"""

    def test_url_without_scheme(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        matched, rule = engine.match("example.com/path")
        assert matched is True

    def test_url_with_query_string(self):
        engine = PatternEngine()
        engine.add_pattern("api.com")
        matched, rule = engine.match("http://api.com/data?key=value&foo=bar")
        assert matched is True

    def test_url_with_fragment(self):
        engine = PatternEngine()
        engine.add_pattern("docs.com")
        # Fragment 通常在客户端处理，urlparse 的正确行为是忽略
        matched, rule = engine.match("http://docs.com/page#section")
        assert matched is True

    def test_ip_address_match(self):
        engine = PatternEngine()
        engine.add_pattern("192.168.1.100")
        matched, rule = engine.match("http://192.168.1.100/admin")
        assert matched is True

    def test_empty_pattern_ignored(self):
        engine = PatternEngine()
        result = engine.add_pattern("")
        assert result is None
        result = engine.add_pattern("   ")
        assert result is None
        assert engine.count == 0

    def test_pattern_with_trailing_slash(self):
        engine = PatternEngine()
        engine.add_pattern("example.com/")
        matched, rule = engine.match("http://example.com/")
        assert matched is True

    def test_long_url(self):
        engine = PatternEngine()
        engine.add_pattern("example.com")
        long_path = "/" + "a/" * 100 + "index.html"
        url = f"http://example.com{long_path}"
        matched, rule = engine.match(url)
        assert matched is True

    def test_unicode_domain(self):
        engine = PatternEngine()
        engine.add_pattern("例子.com")
        matched, rule = engine.match("http://例子.com/page")
        assert matched is True


# ============================================================
# Blacklist 测试
# ============================================================

class TestBlacklist:
    """黑名单测试"""

    @pytest.fixture
    def blacklist(self):
        """创建一个临时的黑名单实例"""
        path = create_temp_rules_file([
            "*.evil.com",
            "ads.tracker.net",
            "/badware/",
        ])
        bl = Blacklist(file_path=path)
        yield bl
        Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_load_from_file(self, blacklist):
        count = await blacklist.load_from_file()
        assert count == 3
        assert blacklist.count == 3

    @pytest.mark.asyncio
    async def test_is_blocked_true(self, blacklist):
        await blacklist.load_from_file()
        blocked, rule = blacklist.is_blocked("http://sub.evil.com/phishing")
        assert blocked is True
        assert rule == "*.evil.com"

    @pytest.mark.asyncio
    async def test_is_blocked_exact(self, blacklist):
        await blacklist.load_from_file()
        blocked, rule = blacklist.is_blocked("http://ads.tracker.net/pixel.gif")
        assert blocked is True
        assert rule == "ads.tracker.net"

    @pytest.mark.asyncio
    async def test_is_blocked_regex(self, blacklist):
        await blacklist.load_from_file()
        blocked, rule = blacklist.is_blocked("http://foo.badware.org/install.exe")
        assert blocked is True
        assert rule == "/badware/"

    @pytest.mark.asyncio
    async def test_is_blocked_false(self, blacklist):
        await blacklist.load_from_file()
        blocked, rule = blacklist.is_blocked("http://safe-site.com/page")
        assert blocked is False
        assert rule is None

    def test_block_domain(self, blacklist):
        blacklist.block_domain("spam-site.com")
        assert blacklist.count == 2  # 精确 + 通配符
        assert blacklist.is_blocked("http://spam-site.com/page")[0] is True
        assert blacklist.is_blocked("http://sub.spam-site.com/page")[0] is True

    def test_unblock(self, blacklist):
        # 直接操作底层引擎进行同步测试
        blacklist._engine.add_pattern("test.com")
        assert blacklist._engine.count == 1
        result = blacklist.unblock("test.com")
        assert result is True
        assert blacklist._engine.count == 0


# ============================================================
# Whitelist 测试
# ============================================================

class TestWhitelist:
    """白名单测试"""

    @pytest.fixture
    def whitelist(self):
        """创建一个有规则的白名单实例"""
        path = create_temp_rules_file([
            "*.company.com",
            "safe-site.org",
        ])
        wl = Whitelist(file_path=path)
        yield wl
        Path(path).unlink(missing_ok=True)

    @pytest.fixture
    def empty_whitelist(self):
        """创建一个空规则的白名单实例"""
        path = create_temp_rules_file([])
        wl = Whitelist(file_path=path)
        yield wl
        Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_load_from_file(self, whitelist):
        count = await whitelist.load_from_file()
        assert count == 2
        assert whitelist.is_active is True

    @pytest.mark.asyncio
    async def test_load_empty_file(self, empty_whitelist):
        count = await empty_whitelist.load_from_file()
        assert count == 0
        assert empty_whitelist.is_active is False

    @pytest.mark.asyncio
    async def test_is_allowed_match(self, whitelist):
        await whitelist.load_from_file()
        allowed, rule = whitelist.is_allowed("http://mail.company.com/inbox")
        assert allowed is True
        assert rule == "*.company.com"

    @pytest.mark.asyncio
    async def test_is_allowed_no_match(self, whitelist):
        await whitelist.load_from_file()
        allowed, rule = whitelist.is_allowed("http://other-site.com")
        assert allowed is False
        assert rule is None

    def test_empty_whitelist_allows_all(self, empty_whitelist):
        """白名单为空时允许所有请求"""
        allowed, rule = empty_whitelist.is_allowed("http://any-site.com/any/path")
        assert allowed is True
        assert rule is None

    def test_allow_domain(self, whitelist):
        whitelist.allow_domain("new-site.com")
        # 有精确匹配和通配符
        assert whitelist.is_allowed("http://new-site.com")[0] is True
        assert whitelist.is_allowed("http://sub.new-site.com")[0] is True

    def test_is_active(self):
        """is_active 应该在规则数>0时为True"""
        path = create_temp_rules_file(["example.com"])
        wl = Whitelist(file_path=path)
        assert wl.count == 0  # 还没加载
        # 同步添加一条（绕过锁）
        wl._engine.add_pattern("example.com")
        assert wl.is_active is True
        Path(path).unlink(missing_ok=True)


# ============================================================
# AccessControl 组合测试
# ============================================================

class TestAccessControl:
    """组合访问控制测试"""

    @pytest.fixture
    def ac(self):
        """创建组合访问控制实例"""
        bl_path = create_temp_rules_file(["*.evil.com"])
        wl_path = create_temp_rules_file(["*.company.com", "safe-site.org"])
        bl = Blacklist(file_path=bl_path)
        wl = Whitelist(file_path=wl_path)
        ac_instance = AccessControl(blacklist=bl, whitelist=wl)
        yield ac_instance
        Path(bl_path).unlink(missing_ok=True)
        Path(wl_path).unlink(missing_ok=True)

    @pytest.fixture
    def ac_empty(self):
        """创建空规则的访问控制实例"""
        bl_path = create_temp_rules_file([])
        wl_path = create_temp_rules_file([])
        bl = Blacklist(file_path=bl_path)
        wl = Whitelist(file_path=wl_path)
        ac_instance = AccessControl(blacklist=bl, whitelist=wl)
        yield ac_instance
        Path(bl_path).unlink(missing_ok=True)
        Path(wl_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_load_rules(self, ac):
        await ac.load_rules()
        assert ac.blacklist.count == 1
        assert ac.whitelist.count == 2

    @pytest.mark.asyncio
    async def test_blacklist_blocks(self, ac):
        await ac.load_rules()
        decision = await ac.check("http://sub.evil.com/phishing")
        assert decision.allowed is False
        assert decision.rule_type == AccessDecision.BLOCKED_BY_BLACKLIST
        assert "blacklist" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_whitelist_allows(self, ac):
        await ac.load_rules()
        decision = await ac.check("http://mail.company.com/inbox")
        assert decision.allowed is True
        assert decision.rule_type == AccessDecision.ALLOWED_BY_WHITELIST

    @pytest.mark.asyncio
    async def test_whitelist_blocks_non_matching(self, ac):
        await ac.load_rules()
        decision = await ac.check("http://other-site.com/page")
        assert decision.allowed is False
        assert decision.rule_type == AccessDecision.BLOCKED_BY_WHITELIST

    @pytest.mark.asyncio
    async def test_blacklist_priority_over_whitelist(self):
        """黑名单优先级高：即使URL同时匹配黑名单和白名单，也应拒绝"""
        bl_path = create_temp_rules_file(["example.com"])
        wl_path = create_temp_rules_file(["example.com"])
        bl = Blacklist(file_path=bl_path)
        wl = Whitelist(file_path=wl_path)
        ac_instance = AccessControl(blacklist=bl, whitelist=wl)
        await ac_instance.load_rules()

        decision = await ac_instance.check("http://example.com/page")
        assert decision.allowed is False
        assert decision.rule_type == AccessDecision.BLOCKED_BY_BLACKLIST

        Path(bl_path).unlink(missing_ok=True)
        Path(wl_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_empty_lists_allow_all(self, ac_empty):
        await ac_empty.load_rules()
        for url in [
            "http://site1.com",
            "http://site2.com/page",
            "http://site3.com/deep/path?query=1",
        ]:
            decision = await ac_empty.check(url)
            assert decision.allowed is True, f"Should allow {url}"
            assert decision.rule_type == AccessDecision.ALLOWED_DEFAULT

    @pytest.mark.asyncio
    async def test_only_blacklist_blocks_matching(self):
        """仅有黑名单时，匹配的被阻止，不匹配的放行"""
        bl_path = create_temp_rules_file(["blocked.com"])
        wl_path = create_temp_rules_file([])
        bl = Blacklist(file_path=bl_path)
        wl = Whitelist(file_path=wl_path)
        ac_instance = AccessControl(blacklist=bl, whitelist=wl)
        await ac_instance.load_rules()

        # 匹配黑名单
        d1 = await ac_instance.check("http://blocked.com/page")
        assert d1.allowed is False

        # 不匹配黑名单，白名单为空
        d2 = await ac_instance.check("http://allowed.com/page")
        assert d2.allowed is True
        assert d2.rule_type == AccessDecision.ALLOWED_DEFAULT

        Path(bl_path).unlink(missing_ok=True)
        Path(wl_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_client_ip_logging(self, ac):
        """确保 client_ip 参数不引发错误"""
        await ac.load_rules()
        decision = await ac.check("http://sub.evil.com/js", client_ip="192.168.1.1")
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_get_status(self, ac):
        await ac.load_rules()
        status = ac.get_status()
        assert "blacklist_count" in status
        assert "whitelist_count" in status
        assert "blacklist_rules" in status
        assert "whitelist_rules" in status
        assert status["blacklist_count"] == 1
        assert status["whitelist_count"] == 2
        assert isinstance(status["blacklist_enabled"], bool)
        assert isinstance(status["whitelist_enabled"], bool)


# ============================================================
# 热加载测试
# ============================================================

class TestHotReload:
    """热加载功能测试"""

    def test_reload_clears_and_reloads(self):
        """reload 应清空旧规则并加载新规则"""
        # 先用旧文件创建一个实例
        old_path = create_temp_rules_file(["old-site.com"])

        bl = Blacklist(file_path=old_path)

        # 同步加载（绕过锁用于测试）
        bl._engine.add_pattern("old-site.com")
        assert bl.count == 1

        # 修改文件内容
        new_path = create_temp_rules_file(["new-site.com", "other-site.com"])
        bl._file_path = Path(new_path)

        # reload 需要异步
        async def _reload():
            count = await bl.reload()
            return count

        count = asyncio.run(_reload())
        assert count == 2
        assert bl.count == 2

        Path(old_path).unlink(missing_ok=True)
        Path(new_path).unlink(missing_ok=True)

    def test_reload_empty_file(self):
        """reload 空文件应清空所有规则"""
        path = create_temp_rules_file(["some-site.com"])
        bl = Blacklist(file_path=path)
        bl._engine.add_pattern("some-site.com")

        # 写空文件
        Path(path).write_text("# just a comment\n\n", encoding="utf-8")

        count = asyncio.run(bl.reload())
        assert count == 0
        assert bl.count == 0

        Path(path).unlink(missing_ok=True)


# ============================================================
# 并发访问安全测试
# ============================================================

class TestConcurrentAccess:
    """并发访问安全测试"""

    @pytest.mark.asyncio
    async def test_concurrent_checks(self):
        """多个协程同时进行 check 操作不应出错"""
        path = create_temp_rules_file(["blocked.com", "*.evil.net"])
        bl = Blacklist(file_path=path)
        wl = Whitelist(file_path=create_temp_rules_file([]))
        ac = AccessControl(blacklist=bl, whitelist=wl)
        await ac.load_rules()

        urls = [
            "http://blocked.com/page",
            "http://safe.com/page",
            "http://sub.evil.net/js",
            "http://another-safe.org/api",
        ] * 25  # 100 次调用

        async def check_url(url):
            return await ac.check(url)

        results = await asyncio.gather(*[check_url(u) for u in urls])
        assert len(results) == 100
        blocked_count = sum(1 for r in results if not r.allowed)
        assert blocked_count == 50  # blocked.com 25次 + *.evil.net 25次

        Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_concurrent_add_rules(self):
        """并发添加规则不应导致状态损坏"""
        path = create_temp_rules_file([])
        bl = Blacklist(file_path=path)

        async def add_rule(i):
            await bl.add_rule(f"site{i}.com")

        await asyncio.gather(*[add_rule(i) for i in range(50)])
        # 所有50条规则应该都存在
        assert bl.count == 50

        Path(path).unlink(missing_ok=True)


# ============================================================
# 文件解析测试
# ============================================================

class TestFileParsing:
    """配置文件解析测试"""

    def test_comment_lines_ignored(self):
        content = """# This is a comment
        # Another comment
        actual-site.com
        # More comments
        """
        path = create_temp_rules_file([])
        Path(path).write_text(content, encoding="utf-8")

        bl = Blacklist(file_path=path)
        count = asyncio.run(bl.load_from_file())
        assert count == 1

        Path(path).unlink(missing_ok=True)

    def test_empty_lines_ignored(self):
        content = """

        site-a.com


        site-b.com

        """
        path = create_temp_rules_file([])
        Path(path).write_text(content, encoding="utf-8")

        bl = Blacklist(file_path=path)
        count = asyncio.run(bl.load_from_file())
        assert count == 2

        Path(path).unlink(missing_ok=True)

    def test_whitespace_trimmed(self):
        content = "   site-with-spaces.com   "
        path = create_temp_rules_file([])
        Path(path).write_text(content, encoding="utf-8")

        bl = Blacklist(file_path=path)
        count = asyncio.run(bl.load_from_file())
        assert count == 1
        assert bl.is_blocked("http://site-with-spaces.com/page")[0] is True

        Path(path).unlink(missing_ok=True)

    def test_inline_comment(self):
        content = "evil.com # this is a malicious site"
        path = create_temp_rules_file([])
        Path(path).write_text(content, encoding="utf-8")

        bl = Blacklist(file_path=path)
        count = asyncio.run(bl.load_from_file())
        assert count == 1
        # 内联注释后的空格+内容应被去除
        rules = bl.get_rules_raw()
        assert "evil.com" in rules
        assert "evil.com # this is a malicious site" not in rules

        Path(path).unlink(missing_ok=True)


# ============================================================
# AccessDecision 测试
# ============================================================

class TestAccessDecision:
    """访问决策数据类测试"""

    def test_allowed_decision(self):
        d = AccessDecision(allowed=True, reason="passed", rule_type="whitelist")
        assert d.allowed is True
        assert d.reason == "passed"

    def test_blocked_decision(self):
        d = AccessDecision(
            allowed=False,
            reason="blocked",
            matched_rule="*.evil.com",
            rule_type=AccessDecision.BLOCKED_BY_BLACKLIST,
        )
        assert d.allowed is False
        assert d.matched_rule == "*.evil.com"

    def test_constants(self):
        """常量值确认"""
        assert AccessDecision.BLOCKED_BY_BLACKLIST == "blocked_by_blacklist"
        assert AccessDecision.BLOCKED_BY_WHITELIST == "blocked_by_whitelist"
        assert AccessDecision.ALLOWED_BY_WHITELIST == "allowed_by_whitelist"
        assert AccessDecision.ALLOWED_DEFAULT == "allowed_default"
