# HTTP Proxy Cache Server

## 项目简介

本项目实现一个支持缓存机制的 HTTP 代理服务器。

客户端通过代理服务器访问目标网站时：

1. 请求首先到达代理服务器
2. 检查缓存是否存在
3. 若缓存命中则直接返回
4. 若未命中则转发请求至目标服务器
5. 保存响应至缓存
6. 返回结果给客户端

同时支持：

* HTTP代理
* HTTPS CONNECT隧道
* 缓存管理
* 日志记录
* 黑名单/白名单控制
* 访问统计
* Web管理界面

---

## 功能列表

### 基础功能

* HTTP请求接收与解析
* HTTP请求转发
* 响应回传
* 缓存存储与读取
* 日志记录
* 并发连接处理

### 扩展功能

* LRU缓存淘汰
* TTL缓存失效
* HTTPS CONNECT代理
* 黑名单控制
* 白名单控制
* Dashboard统计界面

---

## 项目结构

proxy/
HTTP代理核心模块

cache/
缓存模块

security/
访问控制模块

logger/
日志模块

statistics/
统计分析模块

dashboard/
Web管理界面

database/
SQLite数据库模块

---

## 启动项目

安装依赖：

pip install -r requirements.txt

初始化数据库：

python database/init_db.py

启动服务：

python app.py

默认代理端口：

8080

Dashboard：

http://localhost:8000

---

## 浏览器代理配置

HTTP Proxy：

127.0.0.1:8080

HTTPS Proxy：

127.0.0.1:8080

---

## 缓存策略

默认TTL：

60秒

缓存淘汰：

LRU

缓存容量：

1000条记录

---

## 日志格式

时间 | 客户端IP | 方法 | URL | 状态码 | CacheHit

示例：

2026-05-31 10:00:01
127.0.0.1
GET
http://example.com
200
HIT

---

## 访问控制模块 (Security) ✅ 已完成

Security 模块在代理请求处理流水线中作为**第一道关卡**，负责拦截或放行请求。

### 模块结构

```
security/
├── __init__.py           # 包导出 + 全局单例
├── pattern_engine.py     # 模式匹配引擎（核心算法）
├── base_list.py          # 抽象基类（文件I/O、热加载、CRUD）
├── blacklist.py          # 黑名单管理器
├── whitelist.py          # 白名单管理器
└── access_control.py     # 组合访问控制（主入口）
```

### 决策优先级

1. **黑名单优先** — 命中黑名单 → 直接拒绝
2. **白名单检查** — 白名单非空且不匹配 → 拒绝
3. **默认放行** — 两个列表都为空时允许所有请求

### 支持的匹配模式

| 类型 | 示例 | 匹配效果 |
|------|------|---------|
| 精确域名 | `ads.example.com` | 精确匹配该域名 |
| 精确路径 | `example.com/special/path` | 精确匹配域名+路径 |
| 子域名通配 | `*.evil.com` | 匹配 `sub.evil.com`，不匹配 `evil.com` 本身 |
| 路径通配 | `example.com/ads/*` | 匹配该路径下所有子路径 |
| 正则表达式 | `/^.*\\.spam\\.com/` | 自定义正则匹配 |

### 配置文件

- `config/blacklist.txt` — 黑名单规则（一行一条）
- `config/whitelist.txt` — 白名单规则（一行一条）

文件格式：

```
# 注释行以 # 开头
# 精确域名
ads.example.com

# 子域名通配
*.evil.com

# 路径通配
example.com/ads/*

# 正则表达式
/^.*\.adserver\d*\.com$/
```

### 代理服务器集成

```python
from security import AccessControl

ac = AccessControl()
await ac.load_rules()  # 启动时从文件加载

# 每个请求到达时调用
decision = await ac.check("http://example.com/path", client_ip="1.2.3.4")
if not decision.allowed:
    return Response(403, body=decision.reason)
# decision.allowed = True/False
# decision.reason = 人类可读的拒绝原因
# decision.matched_rule = 匹配到的规则
# decision.rule_type = "blacklist" / "whitelist" / "default"
```

### Dashboard API 接口（预留）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/security/status` | 获取黑白名单状态和规则列表 |
| POST | `/api/security/blacklist` | 添加黑名单规则 |
| DELETE | `/api/security/blacklist` | 删除黑名单规则 |
| POST | `/api/security/whitelist` | 添加白名单规则 |
| DELETE | `/api/security/whitelist` | 删除白名单规则 |
| POST | `/api/security/reload` | 热加载（从文件重新读取） |

### 运行测试

```bash
pytest tests/test_security.py -v
# 75 tests passed
```

---

## 小组成员分工

成员A：代理核心模块

成员B：缓存模块

成员C：日志与统计模块

成员D：访问控制模块 ✅

成员E：Dashboard与数据库模块
