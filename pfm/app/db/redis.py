from __future__ import annotations

import asyncio
import json
import uuid
from inspect import isawaitable
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import Settings, get_settings
from app.core.telemetry.metrics import get_metrics

logger = structlog.get_logger()


class RedisServiceError(RuntimeError):
    """Base error for Redis service lifecycle and availability failures."""


class RedisUnavailableError(RedisServiceError):
    """Raised when Redis is not currently available for use."""


class RedisServiceStoppedError(RedisUnavailableError):
    """Raised when a stopped Redis service is accessed or restarted."""


def _observe_reconnect_attempt(*, source: str) -> None:
    get_metrics().record_redis_reconnect_attempt(source=source)
    logger.info("redis.reconnect_attempt", source=source)


def _observe_reconnect_cooldown_skip(
    *,
    source: str,
    remaining_cooldown_seconds: float,
) -> None:
    get_metrics().record_redis_reconnect_cooldown_skip(source=source)
    logger.debug(
        "redis.reconnect_cooldown_skip",
        source=source,
        remaining_cooldown_seconds=round(max(0.0, remaining_cooldown_seconds), 3),
    )


def _observe_stopped_access(*, source: str) -> None:
    get_metrics().record_redis_stopped_access(source=source)
    logger.warning("redis.stopped_access", source=source)


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
    """Own the process Redis client and expose a small application-facing API.

    Contract:
    - Prefer the helper methods below for normal application reads, writes, and probes.
    - Use ``require_client()`` when a caller needs a recovery-aware raw Redis client for a
      short custom sequence that the service does not already model.
    - Use ``raw_client`` only for intentionally low-level integrations that must bind to the
      already-published client and manage availability separately.
    """

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
        self._stopped = False
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
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def backend_generation(self) -> int:
        return self._backend_generation

    @property
    def raw_client(self) -> aioredis.Redis:
        """Return the published Redis client without attempting recovery. Use this only when you need access to the client directly. Otherwise always use service methods """
        if self._client is None:
            if self._stopped:
                _observe_stopped_access(source="raw_client")
                raise RedisServiceStoppedError(
                    "Redis service has been stopped and cannot be used."
                )
            raise RedisUnavailableError(
                "Redis is unavailable. Start the Redis service first."
            )
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

    async def _start_locked(self, *, source: str) -> None:
        if self._client is not None:
            return
        if self._stopped:
            _observe_stopped_access(source=source)
            raise RedisServiceStoppedError(
                "Redis service has been stopped and cannot be restarted."
            )

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
            await self._start_locked(source="start")

    async def ensure_started(self) -> bool:
        if self._client is not None:
            return True
        if self._stopped:
            _observe_stopped_access(source="ensure_started")
            return False

        async with self._start_lock:
            if self._client is not None:
                return True
            if self._stopped:
                _observe_stopped_access(source="ensure_started")
                return False

            now = asyncio.get_running_loop().time()
            if (
                self._last_start_failure_at is not None
                and now - self._last_start_failure_at < self._start_retry_cooldown_seconds
            ):
                _observe_reconnect_cooldown_skip(
                    source="ensure_started",
                    remaining_cooldown_seconds=(
                        self._start_retry_cooldown_seconds
                        - (now - self._last_start_failure_at)
                    ),
                )
                return False

            try:
                _observe_reconnect_attempt(source="ensure_started")
                await self._start_locked(source="ensure_started")
            except Exception:
                return False

            return True

    async def stop(self) -> None:
        async with self._start_lock:
            client = self._client
            self._stopped = True
            if client is not None:
                self._backend_generation += 1
            self._client = None
            self._last_start_failure_at = None
        await _close_client(client)

    async def close(self) -> None:
        await self.stop()

    async def require_client(self) -> aioredis.Redis:
        """Return a recovery-aware raw Redis client for short custom call sequences."""
        client = self._client
        if client is not None:
            return client
        if self._stopped:
            _observe_stopped_access(source="require_client")
            raise RedisServiceStoppedError(
                "Redis service has been stopped and cannot be used."
            )

        if not await self.ensure_started():
            if self._stopped:
                _observe_stopped_access(source="require_client")
                raise RedisServiceStoppedError(
                    "Redis service has been stopped and cannot be used."
                )
            raise RedisUnavailableError("Redis is temporarily unavailable.")

        client = self._client
        if client is None:
            raise RedisUnavailableError("Redis is temporarily unavailable.")
        return client

    async def ping(self, *, timeout_seconds: float = 2.0) -> bool:
        client = await self.require_client()
        return await asyncio.wait_for(client.ping(), timeout=timeout_seconds)

    # Normal application code should prefer the helper methods below over direct client access.
    async def round_trip(
        self,
        *,
        timeout_seconds: float = 2.0,
        ttl_seconds: int = 5,
        key_prefix: str = "healthcheck",
    ) -> None:
        client = await self.require_client()
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
        client = await self.require_client()
        return await client.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        client = await self.require_client()
        if ttl is None:
            await client.set(key, value)
            return
        await client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        client = await self.require_client()
        await client.delete(key)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value), ttl=ttl)

    async def delete_pattern(self, pattern: str) -> None:
        client = await self.require_client()
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)


def build_redis_service(settings: Settings | None = None) -> RedisService:
    return RedisService.from_settings(settings)


__all__ = [
    "RedisService",
    "RedisServiceError",
    "RedisUnavailableError",
    "RedisServiceStoppedError",
    "build_redis_service",
]
