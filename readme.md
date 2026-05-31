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

## 小组成员分工

成员A：代理核心模块

成员B：缓存模块

成员C：日志与统计模块

成员D：访问控制模块

成员E：Dashboard与数据库模块
