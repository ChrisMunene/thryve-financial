import json
from typing import Any

import redis.asyncio as aioredis

from app.config import settings


class RedisClient:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def initialize(self) -> None:
        self._redis = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )

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
