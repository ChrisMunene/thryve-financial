import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

logger = structlog.get_logger()


class RedisClient:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def initialize(self) -> None:
        settings = get_settings()
        redis = aioredis.from_url(
            settings.redis.url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        try:
            await redis.ping()
        except Exception as exc:
            logger.warning("redis.initialize_failed", error=str(exc))
            await redis.close()
            self._redis = None
            return

        self._redis = redis

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("Redis not initialized. Call initialize() first.")
        return self._redis

    async def get(self, key: str) -> str | None:
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl:
            await self.redis.set(key, value, ex=ttl)
        else:
            await self.redis.set(key, value)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value), ttl=ttl)

    async def invalidate(self, pattern: str) -> None:
        async for key in self.redis.scan_iter(match=pattern):
            await self.redis.delete(key)


redis_client = RedisClient()
