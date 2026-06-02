from dataclasses import dataclass


@dataclass
class AccessLog:
    """访问日志记录"""
    id: int | None = None
    access_time: str = ""
    client_ip: str = ""
    target_url: str = ""
    method: str = "GET"
    status_code: int = 0
    cache_hit: bool = False
    response_size: int = 0
    duration_ms: int = 0

    @classmethod
    def from_row(cls, row: tuple):
        return cls(
            id=row[0],
            access_time=row[1],
            client_ip=row[2],
            target_url=row[3],
            method=row[4],
            status_code=row[5],
            cache_hit=bool(row[6]),
            response_size=row[7],
            duration_ms=row[8],
        )


@dataclass
class CacheRecord:
    """缓存资源记录"""
    id: int | None = None
    url: str = ""
    content: bytes | None = None
    content_type: str = ""
    status_code: int = 0
    cached_at: str = ""
    expires_at: str = ""
    access_count: int = 0
    size: int = 0


@dataclass
class CacheStats:
    """缓存统计信息"""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    hit_rate: float = 0.0
    cached_resources: int = 0
    total_cache_size: int = 0


@dataclass
class TopResource:
    """热门资源"""
    url: str = ""
    access_count: int = 0


@dataclass
class MethodStats:
    """请求方法统计"""
    method: str = ""
    count: int = 0
