import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库配置
DATABASE_PATH = os.path.join(BASE_DIR, "database", "proxy.db")

# 代理服务器配置
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080

# Dashboard 配置
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8000

# 缓存配置
CACHE_TTL = 60
CACHE_MAX_SIZE = 1000

# 日志文件路径
LOG_DIR = os.path.join(BASE_DIR, "logs")
ACCESS_LOG_PATH = os.path.join(LOG_DIR, "access.log")
ERROR_LOG_PATH = os.path.join(LOG_DIR, "error.log")

# 黑/白名单文件路径
CONFIG_DIR = os.path.join(BASE_DIR, "config")
BLACKLIST_PATH = os.path.join(CONFIG_DIR, "blacklist.txt")
WHITELIST_PATH = os.path.join(CONFIG_DIR, "whitelist.txt")
"""
项目全局配置

包含代理服务器、缓存、安全模块、日志、Dashboard 等所有模块的配置常量。
"""

import os
from pathlib import Path

# ============================================================
# 基础路径
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent

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
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))         # 默认 TTL（秒）
CACHE_MAX_SIZE = int(os.environ.get("CACHE_MAX_SIZE", "1000"))  # 最大缓存记录数

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

# 黑名单文件路径
BLACKLIST_PATH = os.environ.get(
    "BLACKLIST_PATH",
    str(BASE_DIR / "config" / "blacklist.txt"),
)

# 白名单文件路径
WHITELIST_PATH = os.environ.get(
    "WHITELIST_PATH",
    str(BASE_DIR / "config" / "whitelist.txt"),
)

# 功能开关（可通过环境变量控制）
BLACKLIST_ENABLED = os.environ.get("BLACKLIST_ENABLED", "true").lower() == "true"
WHITELIST_ENABLED = os.environ.get("WHITELIST_ENABLED", "true").lower() == "true"

# 热加载间隔（秒，0 = 禁用自动热加载）
SECURITY_RELOAD_INTERVAL = int(os.environ.get("SECURITY_RELOAD_INTERVAL", "0"))

# 是否记录被拒绝的请求
LOG_BLOCKED_REQUESTS = os.environ.get("LOG_BLOCKED_REQUESTS", "true").lower() == "true"

# ============================================================
# 日志配置
# ============================================================
LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
ACCESS_LOG_PATH = os.environ.get("ACCESS_LOG_PATH", str(Path(LOG_DIR) / "access.log"))
ERROR_LOG_PATH = os.environ.get("ERROR_LOG_PATH", str(Path(LOG_DIR) / "error.log"))
