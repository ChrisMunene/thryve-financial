from contextlib import asynccontextmanager

from app.api import health
from app.auth.mock import MockAuthService


class _HealthySession:
    async def execute(self, query):
        return 1


@asynccontextmanager
async def _healthy_session_factory():
    yield _HealthySession()


class _LazyRedisService:
    def __init__(
        self,
        *,
        ensure_started_result: bool = True,
        round_trip_error: Exception | None = None,
    ) -> None:
        self._ensure_started_result = ensure_started_result
        self._round_trip_error = round_trip_error
        self.ensure_started_calls = 0
        self.round_trip_calls = 0
        self.ping_calls = 0
        self.is_available = False

    async def ensure_started(self) -> bool:
        self.ensure_started_calls += 1
        return self._ensure_started_result

    async def round_trip(self, *, timeout_seconds: float = 2.0) -> None:
        self.round_trip_calls += 1
        if not await self.ensure_started():
            raise RuntimeError("Redis is unavailable.")
        if self._round_trip_error is not None:
            raise self._round_trip_error

    async def require_client(self):
        if not await self.ensure_started():
            raise RuntimeError("Redis is unavailable.")
        return self

    async def ping(self, *, timeout_seconds: float = 2.0) -> bool:
        self.ping_calls += 1
        return True


async def test_health_check_returns_operational_snapshot(app, client, monkeypatch):
    app._app.version = "1.2.3"
    app.state.started_at_monotonic = 100.0

    monkeypatch.setattr(
        health,
        "_database_health_check",
        _async_return(health.LatencyHealthCheck(status="healthy", latency_ms=2)),
    )
    monkeypatch.setattr(
        health,
        "_redis_health_check",
        _async_return(health.LatencyHealthCheck(status="healthy", latency_ms=1)),
    )
    monkeypatch.setattr(
        health,
        "_auth_health_check",
        _async_return(health.AuthHealthCheck(status="healthy", provider="supabase")),
    )
    monkeypatch.setattr(
        health,
        "_celery_health_check",
        _async_return(
            health.CeleryHealthCheck(
                status="healthy",
                workers=4,
                queues={"default": 3, "high": 0, "low": 1},
            )
        ),
    )
    monkeypatch.setattr(health.time, "monotonic", lambda: 86500.0)

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "checks": {
            "database": {"status": "healthy", "latency_ms": 2},
            "redis": {"status": "healthy", "latency_ms": 1},
            "auth": {"status": "healthy", "provider": "supabase"},
            "celery": {
                "status": "healthy",
                "workers": 4,
                "queues": {"default": 3, "high": 0, "low": 1},
            },
        },
        "version": "1.2.3",
        "uptime_seconds": 86400,
    }


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


async def test_health_check_surfaces_unhealthy_dependencies(app, client, monkeypatch):
    app._app.version = "1.2.3"
    app.state.started_at_monotonic = 10.0

    monkeypatch.setattr(
        health,
        "_database_health_check",
        _async_return(health.LatencyHealthCheck(status="healthy", latency_ms=2)),
    )
    monkeypatch.setattr(
        health,
        "_redis_health_check",
        _async_return(health.LatencyHealthCheck(status="unhealthy")),
    )
    monkeypatch.setattr(
        health,
        "_auth_health_check",
        _async_return(health.AuthHealthCheck(status="unhealthy", provider="mock")),
    )
    monkeypatch.setattr(
        health,
        "_celery_health_check",
        _async_return(
            health.CeleryHealthCheck(
                status="unhealthy",
                workers=0,
                queues={"default": 7, "high": 0, "low": 0},
            )
        ),
    )
    monkeypatch.setattr(health.time, "monotonic", lambda: 25.0)

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"
    assert response.json()["checks"]["redis"] == {"status": "unhealthy"}
    assert response.json()["checks"]["auth"] == {
        "status": "unhealthy",
        "provider": "mock",
    }
    assert response.json()["checks"]["celery"] == {
        "status": "unhealthy",
        "workers": 0,
        "queues": {"default": 7, "high": 0, "low": 0},
    }
    assert response.json()["uptime_seconds"] == 15


async def test_auth_health_check_uses_provider_validation():
    class HealthyAuthService:
        provider_name = "healthy"

        def validate_configuration(self):
            return None

    result = await health._auth_health_check(HealthyAuthService())

    assert result.status == "healthy"
    assert result.provider == "healthy"


async def test_redis_health_check_uses_round_trip(fake_redis, fake_redis_service):
    result = await health._redis_health_check(fake_redis_service)

    assert result.status == "healthy"
    assert result.latency_ms is not None
    assert fake_redis._data == {}


async def test_redis_health_check_recovers_by_ensuring_redis_is_started():
    redis_service = _LazyRedisService()

    result = await health._redis_health_check(redis_service)

    assert result.status == "healthy"
    assert redis_service.ensure_started_calls == 1
    assert redis_service.round_trip_calls == 1


async def test_celery_health_check_surfaces_queue_depths(monkeypatch, fake_redis_service):
    monkeypatch.setattr(
        health,
        "_celery_worker_count",
        lambda: 2,
    )
    monkeypatch.setattr(
        health,
        "_celery_queue_depths",
        _async_return({"default": 5, "high": 1, "low": 0}),
    )

    result = await health._celery_health_check(fake_redis_service)

    assert result.status == "healthy"
    assert result.workers == 2
    assert result.queues == {"default": 5, "high": 1, "low": 0}


async def test_celery_health_check_reports_unhealthy_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        health,
        "_celery_worker_count",
        lambda: 2,
    )

    redis_service = _LazyRedisService(ensure_started_result=False)

    result = await health._celery_health_check(redis_service)

    assert result.status == "unhealthy"
    assert redis_service.ensure_started_calls == 1


async def test_readiness_returns_200_when_dependencies_ready(app, client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class HealthyAuthService:
        provider_name = "healthy"

        def validate_configuration(self):
            return None

    app.dependency_overrides[health.get_auth_service] = lambda: HealthyAuthService()

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["dependencies"] == {
        "database": "ok",
        "redis": "ok",
        "auth": "ok",
    }


async def test_readiness_recovers_by_ensuring_redis_is_started(app, client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class HealthyAuthService:
        provider_name = "healthy"

        def validate_configuration(self):
            return None

    redis_service = _LazyRedisService()
    app.state.redis = redis_service
    app.dependency_overrides[health.get_auth_service] = lambda: HealthyAuthService()

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert redis_service.ensure_started_calls == 1
    assert redis_service.round_trip_calls == 1
    assert redis_service.ping_calls == 0


async def test_readiness_returns_503_when_redis_round_trip_fails(app, client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class HealthyAuthService:
        provider_name = "healthy"

        def validate_configuration(self):
            return None

    redis_service = _LazyRedisService(round_trip_error=RuntimeError("read-only replica"))
    app.state.redis = redis_service
    app.dependency_overrides[health.get_auth_service] = lambda: HealthyAuthService()

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "dependency_unavailable"
    assert body["errors"][0]["field"] == "redis"
    assert redis_service.ensure_started_calls == 1
    assert redis_service.round_trip_calls == 1
    assert redis_service.ping_calls == 0


async def test_readiness_returns_503_when_auth_not_ready(app, client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class FailingAuthService:
        provider_name = "healthy"

        def validate_configuration(self):
            raise RuntimeError("missing auth secret")

    app.dependency_overrides[health.get_auth_service] = lambda: FailingAuthService()

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "dependency_unavailable"
    assert body["errors"][0]["field"] == "auth"


async def test_readiness_returns_503_during_shutdown(app, client):
    app.state.shutting_down = True

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "dependency_unavailable"
    assert "shutting down" in body["detail"].lower()

    app.state.shutting_down = False


async def test_shutdown_flag_resets(app, client):
    app.dependency_overrides[health.get_auth_service] = lambda: MockAuthService()
    app.state.shutting_down = True
    app.state.shutting_down = False

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
