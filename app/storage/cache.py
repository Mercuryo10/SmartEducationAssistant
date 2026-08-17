"""缓存后端抽象与工厂（docs/03 §6）。

- Cache 接口：get/set/delete/clear。
- MemoryCache：开发期（CACHE_BACKEND=memory），基于 cachetools.TTLCache。
- RedisCache：生产期（CACHE_BACKEND=redis），惰性导入 redis 包。
- get_cache()：按配置返回实现，业务层只依赖接口。
"""
import time
from typing import Protocol

from app.core.config import settings

# Key 约定（docs/03 §6.2）：ctx:{conversation_id} / rag:{hash} / media:{sha256}


class Cache(Protocol):
    """缓存抽象：业务层只依赖本接口，禁止直连 redis。"""

    def get(self, key: str) -> str | None:
        """读取缓存值，未命中返回 None。"""
        ...

    def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        """写入缓存并设置过期秒数。"""
        ...

    def delete(self, key: str) -> None:
        """删除指定键。"""
        ...

    def clear(self) -> None:
        """清空全部缓存。"""
        ...


class MemoryCache:
    """内存 TTL 缓存（开发期后端）。

    基于 cachetools.TTLCache 控制容量上限；每个键独立过期时间。
    注意：进程内、单实例有效，重启即失效。
    """

    def __init__(self, maxsize: int = 1024, default_ttl: int = 300) -> None:
        from cachetools import TTLCache

        self._maxsize = maxsize
        self._cache: TTLCache[str, tuple[float, str]] = TTLCache(maxsize=maxsize, ttl=default_ttl)

    def get(self, key: str) -> str | None:
        """读取缓存值，未命中或已过期返回 None。"""
        item = self._cache.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        """写入缓存并设置独立过期秒数。"""
        self._cache[key] = (time.time() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        """删除指定键。"""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """清空全部缓存。"""
        self._cache.clear()

    def __repr__(self) -> str:
        return f"MemoryCache(size={len(self._cache)}/{self._maxsize})"


class RedisCache:
    """Redis 缓存（生产期后端，docs/03 §6.4）。

    redis 包惰性导入：开发期不安装 redis 也能正常 import 本模块。
    阻塞调用应在 FastAPI 的 def 路由（线程池）中执行。
    """

    def __init__(self, url: str | None = None) -> None:
        import redis

        self._url = url or settings.cache_url
        self._client = redis.Redis.from_url(self._url, decode_responses=True)

    def get(self, key: str) -> str | None:
        """读取缓存值，未命中返回 None。"""
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        """写入缓存，由 Redis EXPIRE 控制过期。"""
        self._client.set(key, value, ex=ttl_seconds)

    def delete(self, key: str) -> None:
        """删除指定键。"""
        self._client.delete(key)

    def clear(self) -> None:
        """清空当前库（仅当库专用时使用）。"""
        self._client.flushdb()

    def __repr__(self) -> str:
        return f"RedisCache(url={self._url})"


def get_cache() -> Cache:
    """按 CACHE_BACKEND 返回缓存实现（默认 memory）。"""
    if settings.cache_backend == "redis":
        return RedisCache()
    return MemoryCache()
