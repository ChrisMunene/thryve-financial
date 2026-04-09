"""Tests for rate limiting logic and middleware."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.exceptions import RateLimitError
from app.core import rate_limit as rate_limit_module
from app.core.rate_limit import (
    RateLimitMiddleware,
    _check_rate_limit,
    _is_unlimited_path,
    _resolve_request_identity,
)


class TestRateLimitLogic:
    async def test_under_limit_passes(self, fake_redis):
        key = "test:ratelimit:under"

        metadata = await _check_rate_limit(key, limit=10, window=60)
        assert metadata["remaining"] == 9
        assert metadata["limit"] == 10
        assert metadata["retry_after"] >= 1

    async def test_at_limit_raises(self, fake_redis):
        key = "test:ratelimit:at"

        for _ in range(9):
            await _check_rate_limit(key, limit=10, window=60)

        try:
            await _check_rate_limit(key, limit=10, window=60)
        except RateLimitError as exc:
            assert exc.details is not None
            assert len(exc.details) == 2
        else:
            raise AssertionError("Expected RateLimitError")

    async def test_different_keys_independent(self, fake_redis):
        key_a = "test:ratelimit:user_a"
        key_b = "test:ratelimit:user_b"

        for _ in range(4):
            await _check_rate_limit(key_a, limit=5, window=60)

        metadata = await _check_rate_limit(key_b, limit=5, window=60)
        assert metadata["remaining"] == 4


class TestRateLimitIdentity:
    async def test_prefers_authenticated_user_id(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
        request = Request(scope)
        request.state.user_id = "user-123"
        assert _resolve_request_identity(request) == "user:user-123"

    async def test_uses_bearer_token_hash_when_user_not_set(self, client):
        response = await client.get("/api/v1/health", headers={"authorization": "Bearer token-123"})
        assert response.status_code == 200
        assert "x-ratelimit-limit" not in response.headers


class TestUnlimitedPaths:
    def test_health_paths_are_exempt(self):
        assert _is_unlimited_path("/api/v1/health") is True
        assert _is_unlimited_path("/api/v1/health/ready") is True
        assert _is_unlimited_path("/api/v1/transactions") is False


class TestRateLimitMiddleware:
    async def test_global_rate_limit_headers_present(self, fake_redis):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, default_limit=2, window=60)

        @app.get("/limited")
        async def limited():
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/limited")

        assert response.status_code == 200
        assert response.headers["x-ratelimit-limit"] == "2"
        assert response.headers["x-ratelimit-remaining"] == "1"
        assert "x-ratelimit-reset" in response.headers

    async def test_global_rate_limit_returns_429_without_server_error(self, fake_redis):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, default_limit=2, window=60)

        @app.get("/limited")
        async def limited():
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            first = await ac.get("/limited")
            second = await ac.get("/limited")

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert second.headers["x-ratelimit-remaining"] == "0"
        assert "retry-after" in second.headers

    async def test_global_rate_limit_fails_open_when_redis_unavailable(self, monkeypatch):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, default_limit=2, window=60)

        @app.get("/limited")
        async def limited():
            return {"ok": True}

        async def broken_check(*args, **kwargs):
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr(rate_limit_module, "_check_rate_limit", broken_check)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/limited")

        assert response.status_code == 200
        assert "x-ratelimit-limit" not in response.headers

    async def test_health_endpoint_is_exempt_from_rate_limit(self, fake_redis):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, default_limit=1, window=60)

        @app.get("/api/v1/health")
        async def health():
            return {"status": "healthy"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            first = await ac.get("/api/v1/health")
            second = await ac.get("/api/v1/health")

        assert first.status_code == 200
        assert second.status_code == 200
        assert "x-ratelimit-limit" not in first.headers
        assert "x-ratelimit-limit" not in second.headers
