import aiosqlite
from config.settings import DATABASE_PATH
from database.models import AccessLog, CacheRecord, CacheStats, TopResource, MethodStats


async def init_db():
    """初始化数据库，创建表结构"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_time TEXT NOT NULL,
                client_ip TEXT NOT NULL,
                target_url TEXT NOT NULL,
                method TEXT NOT NULL DEFAULT 'GET',
                status_code INTEGER DEFAULT 0,
                cache_hit INTEGER DEFAULT 0,
                response_size INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                content BLOB,
                content_type TEXT DEFAULT '',
                status_code INTEGER DEFAULT 0,
                cached_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                size INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_access_time
            ON access_logs(access_time DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_url
            ON cache_records(url)
        """)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接"""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


# ========== 访问日志 ==========

async def insert_access_log(
    client_ip: str,
    target_url: str,
    method: str = "GET",
    status_code: int = 0,
    cache_hit: bool = False,
    response_size: int = 0,
    duration_ms: int = 0,
):
    from datetime import datetime

    access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO access_logs
               (access_time, client_ip, target_url, method, status_code,
                cache_hit, response_size, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (access_time, client_ip, target_url, method, status_code,
             int(cache_hit), response_size, duration_ms),
        )
        await db.commit()


async def get_access_logs(limit: int = 100, offset: int = 0) -> list[AccessLog]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM access_logs ORDER BY access_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [AccessLog(
            id=row[0],
            access_time=row[1],
            client_ip=row[2],
            target_url=row[3],
            method=row[4],
            status_code=row[5],
            cache_hit=bool(row[6]),
            response_size=row[7],
            duration_ms=row[8],
        ) for row in rows]


async def get_logs_count() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM access_logs")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def clear_access_logs():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM access_logs")
        await db.commit()


# ========== 缓存记录 ==========

async def insert_cache_record(
    url: str,
    content: bytes,
    content_type: str,
    status_code: int,
    ttl: int = 60,
):
    from datetime import datetime, timedelta

    now = datetime.now()
    cached_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (now + timedelta(seconds=ttl)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO cache_records
               (url, content, content_type, status_code, cached_at, expires_at, access_count, size)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (url, content, content_type, status_code, cached_at, expires_at, len(content)),
        )
        await db.commit()


async def get_cache_record(url: str) -> CacheRecord | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM cache_records WHERE url = ?", (url,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return CacheRecord(
            id=row[0], url=row[1], content=row[2], content_type=row[3],
            status_code=row[4], cached_at=row[5], expires_at=row[6],
            access_count=row[7], size=row[8],
        )


async def get_cached_urls() -> list[str]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT url FROM cache_records")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_cache_count() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM cache_records")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def clear_expired_cache() -> int:
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM cache_records WHERE expires_at < ?", (now,)
        )
        await db.commit()
        return cursor.rowcount


# ========== 统计查询 ==========

async def get_cache_stats() -> CacheStats:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        total = await db.execute("SELECT COUNT(*) FROM access_logs")
        total_requests = (await total.fetchone())[0]

        hits = await db.execute(
            "SELECT COUNT(*) FROM access_logs WHERE cache_hit = 1"
        )
        cache_hits = (await hits.fetchone())[0]

        cached = await db.execute("SELECT COUNT(*) FROM cache_records")
        cached_count = (await cached.fetchone())[0]

        total_size = await db.execute(
            "SELECT COALESCE(SUM(size), 0) FROM cache_records"
        )
        total_cache_size = (await total_size.fetchone())[0]

    cache_misses = total_requests - cache_hits
    hit_rate = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0

    return CacheStats(
        total_requests=total_requests,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        hit_rate=round(hit_rate, 2),
        cached_resources=cached_count,
        total_cache_size=total_cache_size,
    )


async def get_top_resources(limit: int = 10) -> list[TopResource]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """SELECT target_url, COUNT(*) as cnt
               FROM access_logs
               GROUP BY target_url
               ORDER BY cnt DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [TopResource(url=row[0], access_count=row[1]) for row in rows]


async def get_method_stats() -> list[MethodStats]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """SELECT method, COUNT(*) as cnt
               FROM access_logs
               GROUP BY method
               ORDER BY cnt DESC"""
        )
        rows = await cursor.fetchall()
        return [MethodStats(method=row[0], count=row[1]) for row in rows]


async def get_recent_logs(limit: int = 50) -> list[AccessLog]:
    return await get_access_logs(limit=limit)
