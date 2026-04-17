from __future__ import annotations

import asyncio
import json
import uuid
from inspect import isawaitable
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import Settings, get_settings

logger = structlog.get_logger()


async def _close_client(client: Any | None) -> None:
    if client is None:
        return

    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        await aclose()
        return

    close = getattr(client, "close", None)
    if callable(close):
        result = close()
        if isawaitable(result):
            await result


class RedisService:
    """Own the process Redis client and expose a small application-facing API."""

    def __init__(
        self,
        *,
        url: str,
        socket_timeout_seconds: float = 5.0,
        socket_connect_timeout_seconds: float = 5.0,
    ) -> None:
        self._url = url
        self._socket_timeout_seconds = socket_timeout_seconds
        self._socket_connect_timeout_seconds = socket_connect_timeout_seconds
        self._client: aioredis.Redis | None = None
        self._backend_generation = 0
        self._start_lock = asyncio.Lock()
        self._last_start_failure_at: float | None = None
        self._start_retry_cooldown_seconds = 1.0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RedisService:
        effective_settings = settings or get_settings()
        return cls(
            url=effective_settings.redis.url,
            socket_timeout_seconds=5.0,
            socket_connect_timeout_seconds=5.0,
        )

    @classmethod
    def with_client(
        cls,
        client: aioredis.Redis,
        *,
        url: str = "redis://test",
    ) -> RedisService:
        service = cls(url=url)
        service._client = client
        service._backend_generation = 1
        return service

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @property
    def backend_generation(self) -> int:
        return self._backend_generation

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("Redis is unavailable. Start the Redis service first.")
        return self._client

    def key(self, *parts: object) -> str:
        return ":".join(str(part).strip(":") for part in parts if str(part))

    def _build_client(self) -> aioredis.Redis:
        return aioredis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=self._socket_timeout_seconds,
            socket_connect_timeout=self._socket_connect_timeout_seconds,
        )

    async def _start_locked(self) -> None:
        if self._client is not None:
            return

        client = self._build_client()
        try:
            await client.ping()
        except Exception:
            self._last_start_failure_at = asyncio.get_running_loop().time()
            await _close_client(client)
            raise

        self._client = client
        self._backend_generation += 1
        self._last_start_failure_at = None

    async def start(self) -> None:
        if self._client is not None:
            return

        async with self._start_lock:
            await self._start_locked()

    async def ensure_started(self) -> bool:
        if self._client is not None:
            return True

        async with self._start_lock:
            if self._client is not None:
                return True

            now = asyncio.get_running_loop().time()
            if (
                self._last_start_failure_at is not None
                and now - self._last_start_failure_at < self._start_retry_cooldown_seconds
            ):
                return False

            try:
                await self._start_locked()
            except Exception:
                return False

            return True

    async def stop(self) -> None:
        async with self._start_lock:
            client = self._client
            if client is not None:
                self._backend_generation += 1
            self._client = None
            self._last_start_failure_at = None
        await _close_client(client)

    async def close(self) -> None:
        await self.stop()

    async def ping(self, *, timeout_seconds: float = 2.0) -> bool:
        return await asyncio.wait_for(self.client.ping(), timeout=timeout_seconds)

    async def round_trip(
        self,
        *,
        timeout_seconds: float = 2.0,
        ttl_seconds: int = 5,
        key_prefix: str = "healthcheck",
    ) -> None:
        client = self.client
        probe_key = self.key(key_prefix, uuid.uuid4().hex)
        await asyncio.wait_for(client.set(probe_key, "ok", ex=ttl_seconds), timeout_seconds)
        try:
            value = await asyncio.wait_for(client.get(probe_key), timeout_seconds)
            if value != "ok":
                raise RuntimeError("Redis round-trip probe returned an unexpected value.")
        finally:
            try:
                await asyncio.wait_for(client.delete(probe_key), timeout_seconds)
            except Exception:
                logger.warning("redis.round_trip_cleanup_failed", probe_key=probe_key)

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl is None:
            await self.client.set(key, value)
            return
        await self.client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value), ttl=ttl)

    async def delete_pattern(self, pattern: str) -> None:
        client = self.client
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)


def build_redis_service(settings: Settings | None = None) -> RedisService:
    return RedisService.from_settings(settings)


__all__ = ["RedisService", "build_redis_service"]
