"""Tests for the Redis service and its FastAPI lifecycle integration."""

from __future__ import annotations

import asyncio

import pytest

from app import main
from app.config import Settings
from app.db import redis as redis_module


class _FakeRedisClient:
    def __init__(
        self,
        *,
        ping_error: Exception | None = None,
        ping_started: asyncio.Event | None = None,
        ping_release: asyncio.Event | None = None,
    ) -> None:
        self._ping_error = ping_error
        self._ping_started = ping_started
        self._ping_release = ping_release
        self.ping_calls = 0
        self.closed = False
        self._data: dict[str, str] = {}

    async def ping(self) -> bool:
        self.ping_calls += 1
        if self._ping_started is not None:
            self._ping_started.set()
        if self._ping_release is not None:
            await self._ping_release.wait()
        if self._ping_error is not None:
            raise self._ping_error
        return True

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._data[key] = value
        return True

    async def delete(self, key: str) -> int:
        self._data.pop(key, None)
        return 1

    async def scan_iter(self, match: str | None = None):
        for key in list(self._data.keys()):
            yield key

    async def aclose(self) -> None:
        self.closed = True


class _RoundTripClient:
    def __init__(self) -> None:
        self._data = {}
        self.set_started = asyncio.Event()
        self.allow_set_return = asyncio.Event()
        self.closed = False

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._data[key] = value
        self.set_started.set()
        await self.allow_set_return.wait()
        return True

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def delete(self, key: str) -> int:
        self._data.pop(key, None)
        return 1

    async def aclose(self) -> None:
        self.closed = True


class _FailingRedisService:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.is_available = False

    async def start(self) -> None:
        self.start_calls += 1
        raise RuntimeError("redis down")

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeAnalytics:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeTelemetry:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeRedisMetrics:
    def __init__(self) -> None:
        self.reconnect_attempts: list[str] = []
        self.cooldown_skips: list[str] = []
        self.stopped_accesses: list[str] = []

    def record_redis_reconnect_attempt(self, *, source: str) -> None:
        self.reconnect_attempts.append(source)

    def record_redis_reconnect_cooldown_skip(self, *, source: str) -> None:
        self.cooldown_skips.append(source)

    def record_redis_stopped_access(self, *, source: str) -> None:
        self.stopped_accesses.append(source)


async def _noop_initialize_rate_limiting(app) -> None:
    return None


class TestRedisService:
    def test_raw_client_raises_typed_unavailable_error_when_not_started(self):
        service = redis_module.build_redis_service(Settings(environment="development"))

        with pytest.raises(redis_module.RedisUnavailableError, match="unavailable"):
            _ = service.raw_client

    async def test_start_initializes_the_client(self, monkeypatch):
        fake_client = _FakeRedisClient()
        monkeypatch.setattr(redis_module.aioredis, "from_url", lambda *args, **kwargs: fake_client)

        service = redis_module.build_redis_service(Settings(environment="development"))
        await service.start()

        assert service.is_available is True
        assert service.raw_client is fake_client
        assert fake_client.ping_calls == 1

    async def test_ensure_started_recovers_after_startup_failure(self, monkeypatch):
        failing_client = _FakeRedisClient(ping_error=RuntimeError("redis down"))
        healthy_client = _FakeRedisClient()
        clients = [failing_client, healthy_client]

        monkeypatch.setattr(
            redis_module.aioredis,
            "from_url",
            lambda *args, **kwargs: clients.pop(0),
        )

        service = redis_module.build_redis_service(Settings(environment="development"))

        assert await service.ensure_started() is False
        service._start_retry_cooldown_seconds = 0.0
        assert await service.ensure_started() is True
        assert failing_client.closed is True
        assert service.raw_client is healthy_client

    async def test_ensure_started_records_reconnect_attempt_and_cooldown_skip(self, monkeypatch):
        failing_client = _FakeRedisClient(ping_error=RuntimeError("redis down"))
        fake_metrics = _FakeRedisMetrics()

        monkeypatch.setattr(redis_module.aioredis, "from_url", lambda *args, **kwargs: failing_client)
        monkeypatch.setattr(redis_module, "get_metrics", lambda: fake_metrics)

        service = redis_module.build_redis_service(Settings(environment="development"))

        assert await service.ensure_started() is False
        assert await service.ensure_started() is False
        assert fake_metrics.reconnect_attempts == ["ensure_started"]
        assert fake_metrics.cooldown_skips == ["ensure_started"]

    async def test_require_client_recovers_after_startup_failure(self, monkeypatch):
        failing_client = _FakeRedisClient(ping_error=RuntimeError("redis down"))
        healthy_client = _FakeRedisClient()
        clients = [failing_client, healthy_client]

        monkeypatch.setattr(
            redis_module.aioredis,
            "from_url",
            lambda *args, **kwargs: clients.pop(0),
        )

        service = redis_module.build_redis_service(Settings(environment="development"))

        with pytest.raises(redis_module.RedisUnavailableError, match="temporarily unavailable"):
            await service.require_client()

        service._start_retry_cooldown_seconds = 0.0
        client = await service.require_client()

        assert client is healthy_client
        assert failing_client.closed is True

    async def test_get_recovers_after_startup_failure(self, monkeypatch):
        failing_client = _FakeRedisClient(ping_error=RuntimeError("redis down"))
        healthy_client = _FakeRedisClient()
        healthy_client._data["cache:key"] = "value"
        clients = [failing_client, healthy_client]

        monkeypatch.setattr(
            redis_module.aioredis,
            "from_url",
            lambda *args, **kwargs: clients.pop(0),
        )

        service = redis_module.build_redis_service(Settings(environment="development"))

        with pytest.raises(redis_module.RedisUnavailableError, match="temporarily unavailable"):
            await service.get("cache:key")

        service._start_retry_cooldown_seconds = 0.0
        assert await service.get("cache:key") == "value"

    async def test_ensure_started_serializes_concurrent_connection_attempts(self, monkeypatch):
        ping_started = asyncio.Event()
        ping_release = asyncio.Event()
        fake_client = _FakeRedisClient(
            ping_started=ping_started,
            ping_release=ping_release,
        )
        from_url_calls = 0

        def fake_from_url(*args, **kwargs):
            nonlocal from_url_calls
            from_url_calls += 1
            return fake_client

        monkeypatch.setattr(redis_module.aioredis, "from_url", fake_from_url)

        service = redis_module.build_redis_service(Settings(environment="development"))
        first = asyncio.create_task(service.ensure_started())
        await ping_started.wait()
        second = asyncio.create_task(service.ensure_started())
        ping_release.set()

        assert await first is True
        assert await second is True
        assert from_url_calls == 1
        assert service.raw_client is fake_client

    async def test_stop_closes_the_client(self):
        fake_client = _FakeRedisClient()
        service = redis_module.RedisService.with_client(fake_client)

        await service.stop()

        assert service.is_available is False
        assert fake_client.closed is True

    async def test_backend_generation_advances_when_the_published_client_changes(self, monkeypatch):
        fake_client = _FakeRedisClient()
        monkeypatch.setattr(redis_module.aioredis, "from_url", lambda *args, **kwargs: fake_client)

        service = redis_module.build_redis_service(Settings(environment="development"))

        assert service.backend_generation == 0

        await service.start()
        assert service.backend_generation == 1

        await service.stop()
        assert service.backend_generation == 2

    async def test_stop_marks_service_stopped_and_blocks_lazy_restart(self, monkeypatch):
        fake_client = _FakeRedisClient()
        from_url_calls = 0
        fake_metrics = _FakeRedisMetrics()

        def fake_from_url(*args, **kwargs):
            nonlocal from_url_calls
            from_url_calls += 1
            return fake_client

        monkeypatch.setattr(redis_module.aioredis, "from_url", fake_from_url)
        monkeypatch.setattr(redis_module, "get_metrics", lambda: fake_metrics)

        service = redis_module.RedisService.with_client(fake_client)

        await service.stop()

        assert service.is_stopped is True
        assert await service.ensure_started() is False
        assert from_url_calls == 0
        with pytest.raises(redis_module.RedisServiceStoppedError, match="stopped"):
            _ = service.raw_client
        assert fake_metrics.stopped_accesses == ["ensure_started", "raw_client"]

    async def test_start_raises_when_service_has_been_stopped(self, monkeypatch):
        fake_client = _FakeRedisClient()
        fake_metrics = _FakeRedisMetrics()
        monkeypatch.setattr(redis_module, "get_metrics", lambda: fake_metrics)
        service = redis_module.RedisService.with_client(fake_client)

        await service.stop()

        with pytest.raises(redis_module.RedisServiceStoppedError, match="stopped"):
            await service.start()
        assert fake_metrics.stopped_accesses == ["start"]

    async def test_public_helper_raises_stopped_error_after_stop(self, monkeypatch):
        fake_client = _FakeRedisClient()
        fake_metrics = _FakeRedisMetrics()
        monkeypatch.setattr(redis_module, "get_metrics", lambda: fake_metrics)
        service = redis_module.RedisService.with_client(fake_client)

        await service.stop()

        with pytest.raises(redis_module.RedisServiceStoppedError, match="stopped"):
            await service.get("cache:key")
        assert fake_metrics.stopped_accesses == ["require_client"]

    async def test_round_trip_keeps_using_the_captured_client_during_shutdown(self):
        fake_client = _RoundTripClient()
        service = redis_module.RedisService.with_client(fake_client)

        round_trip_task = asyncio.create_task(service.round_trip())
        await fake_client.set_started.wait()

        stop_task = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        fake_client.allow_set_return.set()

        await round_trip_task
        await stop_task

        assert service.is_available is False
        assert fake_client.closed is True


class TestRedisLifespan:
    async def test_lifespan_logs_and_degrades_when_redis_fails_to_start(self, monkeypatch):
        settings = Settings(environment="development")
        fake_analytics = _FakeAnalytics()
        fake_telemetry = _FakeTelemetry()
        failing_service = _FailingRedisService()

        monkeypatch.setattr(main, "get_settings", lambda: settings)
        monkeypatch.setattr(main, "create_analytics_service", lambda: fake_analytics)
        monkeypatch.setattr(main, "bootstrap_api_telemetry", lambda app, settings: fake_telemetry)
        monkeypatch.setattr(main, "initialize_rate_limiting", _noop_initialize_rate_limiting)
        monkeypatch.setattr(main, "build_redis_service", lambda settings: failing_service)

        application = main.create_app()

        async with main.lifespan(application._app):
            assert application.state.redis is failing_service

        assert failing_service.start_calls == 1
        assert failing_service.stop_calls == 1
        assert fake_analytics.closed is True
        assert fake_telemetry.shutdown_calls == 1
