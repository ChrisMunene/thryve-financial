"""Tests for rate limiting policy and integration."""

import hashlib
from inspect import isawaitable

from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pyrate_limiter import AbstractBucket
from starlette.requests import Request

from app.config import Settings
from app.core import rate_limit as rate_limit_module
from app.main import create_app
from app.middleware.error_handler import register_error_handlers


class _FakeLimiter:
    def __init__(self, *results: bool):
        self._results = list(results) or [True]
        self.keys: list[str] = []

    async def try_acquire_async(self, key: str, blocking: bool = False) -> bool:
        self.keys.append(key)
        if self._results:
            return self._results.pop(0)
        return True


class _FakeBucket(AbstractBucket):
    def put(self, item):
        return True

    def leak(self, current_timestamp=None):
        return 0

    def flush(self):
        return None

    def count(self):
        return 0

    def peek(self, index: int):
        return None


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


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

        assert await rate_limit_module._resolve_rate_limit_identity(request) == "user:user-123"

    async def test_uses_bearer_token_hash_when_user_not_set(self):
        token = "token-123"
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("127.0.0.1", 1234),
        }
        request = Request(scope)

        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert await rate_limit_module._resolve_rate_limit_identity(request) == f"token:{expected}"


class TestNamedPolicies:
    def test_builds_named_policy_registry_from_settings(self):
        settings = Settings(
            rate_limit={
                "default_limit": 100,
                "default_window_seconds": 60,
                "write_limit": 30,
                "write_window_seconds": 60,
                "expensive_limit": 10,
                "expensive_window_seconds": 60,
                "auth_limit": 5,
                "auth_window_seconds": 60,
            }
        )

        policies = rate_limit_module._build_rate_limit_policies(settings)

        assert policies.default == rate_limit_module.RateLimitPolicy(100, 60)
        assert policies.write == rate_limit_module.RateLimitPolicy(30, 60)
        assert policies.expensive == rate_limit_module.RateLimitPolicy(10, 60)
        assert policies.auth == rate_limit_module.RateLimitPolicy(5, 60)

    async def test_public_rate_limit_api_uses_registry(self, monkeypatch):
        policies = rate_limit_module.RateLimitPolicies(
            default=rate_limit_module.RateLimitPolicy(100, 60),
            write=rate_limit_module.RateLimitPolicy(30, 60),
            expensive=rate_limit_module.RateLimitPolicy(10, 60),
            auth=rate_limit_module.RateLimitPolicy(5, 60),
        )
        monkeypatch.setattr(rate_limit_module, "_get_rate_limit_policies", lambda: policies)

        assert (
            rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.DEFAULT)._policy
            == policies.default
        )
        assert (
            rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.WRITE)._policy
            == policies.write
        )
        assert (
            rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.EXPENSIVE)._policy
            == policies.expensive
        )
        assert (
            rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.AUTH)._policy
            == policies.auth
        )

    def test_exempt_tier_requires_skip_limiter(self):
        try:
            rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.EXEMPT)
        except ValueError as exc:
            assert "skip_limiter" in str(exc)
        else:
            raise AssertionError("Expected ValueError for exempt tier binding")

    async def test_get_or_create_limiter_awaits_async_redis_bucket_init(self, monkeypatch):
        policy = rate_limit_module.RateLimitPolicy(10, 60)
        bucket = _FakeBucket()

        rate_limit_module._LIMITER_INSTANCE_CACHE.clear()
        rate_limit_module._LIMITER_INIT_LOCKS.clear()

        monkeypatch.setattr(rate_limit_module.redis_client, "_redis", object())

        def fake_redis_bucket_init(*args, **kwargs):
            return _async_return(bucket)()

        monkeypatch.setattr(rate_limit_module.RedisBucket, "init", fake_redis_bucket_init)
        monkeypatch.setattr(rate_limit_module, "Limiter", lambda argument: {"bucket": argument})

        limiter = await rate_limit_module._get_or_create_limiter(policy)

        assert limiter == {"bucket": bucket}
        assert not isawaitable(limiter)


class TestRateLimiterDependency:
    async def test_rate_limit_returns_standardized_429(self, monkeypatch):
        app = FastAPI()
        register_error_handlers(app)
        fake_limiter = _FakeLimiter(True, False)
        monkeypatch.setattr(
            rate_limit_module,
            "_get_rate_limit_policies",
            lambda: rate_limit_module.RateLimitPolicies(
                default=rate_limit_module.RateLimitPolicy(100, 60),
                write=rate_limit_module.RateLimitPolicy(1, 60),
                expensive=rate_limit_module.RateLimitPolicy(10, 60),
                auth=rate_limit_module.RateLimitPolicy(5, 60),
            ),
        )

        router = APIRouter()

        @router.get(
            "/limited",
            dependencies=[Depends(rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.WRITE))],
        )
        async def limited():
            return {"ok": True}

        app.include_router(router)

        monkeypatch.setattr(
            rate_limit_module,
            "_get_or_create_limiter",
            _async_return(fake_limiter),
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            first = await ac.get("/limited")
            second = await ac.get("/limited")

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["code"] == "rate_limited"
        assert second.json()["retryable"] is True
        assert second.headers["retry-after"] == "60"
        assert second.headers["x-ratelimit-limit"] == "1"

    async def test_rate_limit_fails_open_when_backend_unavailable(self, monkeypatch):
        app = FastAPI()
        register_error_handlers(app)

        @app.get(
            "/limited",
            dependencies=[Depends(rate_limit_module.rate_limit(rate_limit_module.RateLimitTier.WRITE))],
        )
        async def limited():
            return {"ok": True}

        monkeypatch.setattr(rate_limit_module, "_get_or_create_limiter", _async_return(None))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/limited")

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_health_endpoint_is_exempt_from_rate_limit(self, monkeypatch):
        app = create_app()
        fake_limiter = _FakeLimiter(False, False)

        monkeypatch.setattr(
            rate_limit_module,
            "_get_or_create_limiter",
            _async_return(fake_limiter),
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            first = await ac.get("/api/v1/health")
            second = await ac.get("/api/v1/health")

        assert first.status_code == 200
        assert second.status_code == 200
        assert fake_limiter.keys == []
