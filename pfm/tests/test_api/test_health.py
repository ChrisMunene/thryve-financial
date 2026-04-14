from contextlib import asynccontextmanager

from app.api import health


class _HealthySession:
    async def execute(self, query):
        return 1


@asynccontextmanager
async def _healthy_session_factory():
    yield _HealthySession()


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
        _async_return(health.AuthHealthCheck(status="healthy", provider="SupabaseAuthDelegate")),
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
            "auth": {"status": "healthy", "provider": "SupabaseAuthDelegate"},
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
    async def _inner():
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
        _async_return(health.AuthHealthCheck(status="unhealthy", provider="MockAuthDelegate")),
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
        "provider": "MockAuthDelegate",
    }
    assert response.json()["checks"]["celery"] == {
        "status": "unhealthy",
        "workers": 0,
        "queues": {"default": 7, "high": 0, "low": 0},
    }
    assert response.json()["uptime_seconds"] == 15


async def test_auth_health_check_uses_delegate_validation(monkeypatch):
    class HealthyDelegate:
        def validate_configuration(self):
            return None

    monkeypatch.setattr(health, "_get_auth_delegate", lambda: HealthyDelegate())

    result = await health._auth_health_check()

    assert result.status == "healthy"
    assert result.provider == "HealthyDelegate"


async def test_redis_health_check_uses_round_trip(fake_redis):
    result = await health._redis_health_check()

    assert result.status == "healthy"
    assert result.latency_ms is not None
    assert fake_redis._data == {}


async def test_celery_health_check_surfaces_queue_depths(monkeypatch):
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

    result = await health._celery_health_check()

    assert result.status == "healthy"
    assert result.workers == 2
    assert result.queues == {"default": 5, "high": 1, "low": 0}


async def test_readiness_returns_200_when_dependencies_ready(client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class HealthyAuthService:
        def __init__(self, delegate):
            self.delegate = delegate

        def validate_configuration(self):
            return None

    monkeypatch.setattr(health, "AuthService", HealthyAuthService)
    monkeypatch.setattr(health, "_get_auth_delegate", lambda: object())

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["dependencies"] == {
        "database": "ok",
        "redis": "ok",
        "auth": "ok",
    }


async def test_readiness_returns_503_when_auth_not_ready(client, monkeypatch):
    monkeypatch.setattr(health, "get_async_session_factory", lambda: _healthy_session_factory)

    class FailingAuthService:
        def __init__(self, delegate):
            self.delegate = delegate

        def validate_configuration(self):
            raise RuntimeError("missing auth secret")

    monkeypatch.setattr(health, "AuthService", FailingAuthService)
    monkeypatch.setattr(health, "_get_auth_delegate", lambda: object())

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
    app.state.shutting_down = True
    app.state.shutting_down = False

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
