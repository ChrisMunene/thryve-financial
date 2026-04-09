from contextlib import asynccontextmanager

from app.api import health


class _HealthySession:
    async def execute(self, query):
        return 1


@asynccontextmanager
async def _healthy_session_factory():
    yield _HealthySession()


async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


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
    assert response.json()["dependencies"] == {
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
    assert response.json()["dependencies"]["auth"] == "error"


async def test_readiness_returns_503_during_shutdown(app, client):
    app.state.shutting_down = True

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "shutting_down"}

    app.state.shutting_down = False


async def test_shutdown_flag_resets(app, client):
    app.state.shutting_down = True
    app.state.shutting_down = False

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
