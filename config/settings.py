"""
项目全局配置

包含代理服务器、缓存、安全模块、日志、Dashboard 等所有模块的配置常量。
所有配置都提供默认值，并允许通过环境变量覆盖，便于本地开发和部署。
"""

import os
from pathlib import Path


def _get_bool_env(name: str, default: bool) -> bool:
    """Parse common boolean environment variable values."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ============================================================
# 基础路径
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = str(BASE_DIR / "config")

# ============================================================
# 代理服务器配置
# ============================================================
PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8080"))

# ============================================================
# Dashboard 配置
# ============================================================
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))

# ============================================================
# 缓存配置
# ============================================================
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
CACHE_MAX_SIZE = int(os.environ.get("CACHE_MAX_SIZE", "1000"))

# ============================================================
# 数据库配置
# ============================================================
DATABASE_PATH = os.environ.get(
    "DATABASE_PATH",
    str(BASE_DIR / "database" / "proxy.db"),
)

# ============================================================
# 安全模块配置（访问控制）
# ============================================================
BLACKLIST_PATH = os.environ.get(
    "BLACKLIST_PATH",
    str(BASE_DIR / "config" / "blacklist.txt"),
)
WHITELIST_PATH = os.environ.get(
    "WHITELIST_PATH",
    str(BASE_DIR / "config" / "whitelist.txt"),
)
HEADER_RULES_PATH = os.environ.get(
    "HEADER_RULES_PATH",
    str(BASE_DIR / "config" / "header_rules.json"),
)

BLACKLIST_ENABLED = _get_bool_env("BLACKLIST_ENABLED", True)
WHITELIST_ENABLED = _get_bool_env("WHITELIST_ENABLED", True)

# 热加载间隔（秒，0 = 禁用自动热加载）
SECURITY_RELOAD_INTERVAL = int(os.environ.get("SECURITY_RELOAD_INTERVAL", "0"))

# 是否记录被拒绝的请求
LOG_BLOCKED_REQUESTS = _get_bool_env("LOG_BLOCKED_REQUESTS", True)

# ============================================================
# 日志配置
# ============================================================
LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
ACCESS_LOG_PATH = os.environ.get("ACCESS_LOG_PATH", str(Path(LOG_DIR) / "access.log"))
ERROR_LOG_PATH = os.environ.get("ERROR_LOG_PATH", str(Path(LOG_DIR) / "error.log"))
