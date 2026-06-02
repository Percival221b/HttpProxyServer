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
