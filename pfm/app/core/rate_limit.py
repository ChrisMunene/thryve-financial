"""
Rate limiting adapters built on top of ``fastapi-limiter``.

The package provides the limiting mechanics; this module owns app policy:
identity selection, error envelopes, and backend failure behavior.

Public route API:
    `Depends(rate_limit(RateLimitTier.X))`

Everything else in this module is an internal implementation detail.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from inspect import isawaitable
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi_limiter.decorators import skip_limiter
from fastapi_limiter.depends import RateLimiter as PackageRateLimiter
from pyrate_limiter import Limiter, Rate, RedisBucket

from app.config import Settings, get_settings
from app.core.exceptions import DependencyUnavailableError, RateLimitedError
from app.db.redis import RedisService

logger = structlog.get_logger()


@dataclass(frozen=True)
class RateLimitPolicy:
    """A requests-per-window rule applied to a route or router."""

    limit: int
    window_seconds: int


@dataclass
class _LimiterCacheState:
    redis_service: RedisService
    backend_generation: int
    instances: dict[RateLimitPolicy, Limiter] = field(default_factory=dict)
    init_locks: dict[RateLimitPolicy, asyncio.Lock] = field(default_factory=dict)


class RateLimitTier(StrEnum):
    DEFAULT = "default"
    WRITE = "write"
    EXPENSIVE = "expensive"
    AUTH = "auth"
    EXEMPT = "exempt"


_STRICT_REDIS_TIERS = frozenset({RateLimitTier.AUTH, RateLimitTier.WRITE})


@dataclass(frozen=True)
class RateLimitPolicies:
    """Internal named policy registry for the application."""

    default: RateLimitPolicy
    write: RateLimitPolicy
    expensive: RateLimitPolicy
    auth: RateLimitPolicy


def _build_rate_limit_policies(settings: Settings) -> RateLimitPolicies:
    """Build the full named tier registry from application settings."""
    return RateLimitPolicies(
        default=RateLimitPolicy(
            limit=settings.rate_limit.default_limit,
            window_seconds=settings.rate_limit.default_window_seconds,
        ),
        write=RateLimitPolicy(
            limit=settings.rate_limit.write_limit,
            window_seconds=settings.rate_limit.write_window_seconds,
        ),
        expensive=RateLimitPolicy(
            limit=settings.rate_limit.expensive_limit,
            window_seconds=settings.rate_limit.expensive_window_seconds,
        ),
        auth=RateLimitPolicy(
            limit=settings.rate_limit.auth_limit,
            window_seconds=settings.rate_limit.auth_window_seconds,
        ),
    )


def _get_rate_limit_policies() -> RateLimitPolicies:
    """Return the named policy registry for the current runtime settings."""
    return _build_rate_limit_policies(get_settings())


def _policy_for_tier(tier: RateLimitTier) -> RateLimitPolicy | None:
    policies = _get_rate_limit_policies()
    if tier == RateLimitTier.DEFAULT:
        return policies.default
    if tier == RateLimitTier.WRITE:
        return policies.write
    if tier == RateLimitTier.EXPENSIVE:
        return policies.expensive
    if tier == RateLimitTier.AUTH:
        return policies.auth
    if tier == RateLimitTier.EXEMPT:
        return None
    raise ValueError(f"Unsupported rate limit tier: {tier}")


async def _resolve_rate_limit_identity(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"token:{token_hash}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"

    return f"ip:{request.client.host}" if request.client else "ip:unknown"


async def _on_rate_limit_exceeded(request: Request, response: Response, policy: RateLimitPolicy):
    raise RateLimitedError.for_window(policy.window_seconds, limit=policy.limit)


def _app_redis_service(app: Any) -> RedisService:
    redis_service = getattr(app.state, "redis", None)
    if redis_service is None:
        raise RuntimeError("Redis service is not initialized on app.state")
    return redis_service


def _request_redis_service(request: Request) -> RedisService:
    return _app_redis_service(request.app)


def _requires_redis_backend(tier: RateLimitTier) -> bool:
    return tier in _STRICT_REDIS_TIERS


def _redis_backend_unavailable_error() -> DependencyUnavailableError:
    return DependencyUnavailableError.for_service(
        "redis",
        detail="Redis-backed rate limiting is temporarily unavailable.",
        retry_after=1,
    )


def _redis_backend_generation(redis_service: RedisService) -> int:
    return int(getattr(redis_service, "backend_generation", 0))


def _limiter_cache_for_app(app: Any, redis_service: RedisService) -> _LimiterCacheState:
    backend_generation = _redis_backend_generation(redis_service)
    cache = getattr(app.state, "_rate_limit_cache", None)
    if (
        cache is not None
        and cache.redis_service is redis_service
        and cache.backend_generation == backend_generation
    ):
        return cache

    cache = _LimiterCacheState(
        redis_service=redis_service,
        backend_generation=backend_generation,
    )
    app.state._rate_limit_cache = cache
    return cache


async def _get_or_create_limiter(
    policy: RateLimitPolicy,
    redis_service: RedisService,
    app: Any,
) -> Limiter | None:
    if policy.limit <= 0 or policy.window_seconds <= 0:
        raise ValueError("Rate limit policy values must be greater than 0")

    if not redis_service.is_available:
        return None

    limiter_cache = _limiter_cache_for_app(app, redis_service)
    cached = limiter_cache.instances.get(policy)
    if cached is not None:
        return cached

    lock = limiter_cache.init_locks.setdefault(policy, asyncio.Lock())
    async with lock:
        cached = limiter_cache.instances.get(policy)
        if cached is not None:
            return cached

        try:
            bucket = RedisBucket.init(
                [Rate(policy.limit, policy.window_seconds)],
                redis_service.client,
                bucket_key=redis_service.key(
                    "pfm",
                    "rate_limit",
                    policy.limit,
                    policy.window_seconds,
                ),
            )
            if isawaitable(bucket):
                bucket = await bucket
        except Exception as exc:
            logger.warning(
                "rate_limit.unavailable",
                error=str(exc),
                limit=policy.limit,
                window_seconds=policy.window_seconds,
            )
            return None

        limiter = Limiter(bucket)
        limiter_cache.instances[policy] = limiter
        return limiter


async def initialize_rate_limiting(app: Any) -> None:
    """Warm the app-local limiter instance cache once Redis is initialized."""
    redis_service = _app_redis_service(app)
    if not redis_service.is_available:
        return
    policies = _get_rate_limit_policies().__dict__.values()
    for policy in policies:
        await _get_or_create_limiter(policy, redis_service, app)


class _AppRateLimiter:
    """Thin FastAPI dependency wrapper around ``fastapi-limiter``."""

    def __init__(self, tier: RateLimitTier, policy: RateLimitPolicy) -> None:
        self._tier = tier
        self._policy = policy

    async def __call__(self, request: Request, response: Response) -> None:
        redis_service = _request_redis_service(request)
        requires_redis_backend = _requires_redis_backend(self._tier)
        if requires_redis_backend and not redis_service.is_available:
            if not await redis_service.ensure_started():
                logger.warning(
                    "rate_limit.unavailable",
                    path=request.url.path,
                    tier=self._tier,
                    limit=self._policy.limit,
                    window_seconds=self._policy.window_seconds,
                    reason="redis_unavailable",
                )
                raise _redis_backend_unavailable_error()

        limiter = await _get_or_create_limiter(self._policy, redis_service, request.app)
        if limiter is None:
            logger.warning(
                "rate_limit.unavailable",
                path=request.url.path,
                tier=self._tier,
                limit=self._policy.limit,
                window_seconds=self._policy.window_seconds,
                reason="limiter_unavailable",
            )
            if requires_redis_backend:
                raise _redis_backend_unavailable_error()
            return

        dependency = PackageRateLimiter(
            limiter=limiter,
            identifier=_resolve_rate_limit_identity,
            callback=lambda req, resp: _on_rate_limit_exceeded(req, resp, self._policy),
            blocking=False,
        )

        try:
            await dependency(request, response)
        except RateLimitedError:
            raise
        except Exception as exc:
            logger.warning(
                "rate_limit.unavailable",
                error=str(exc),
                path=request.url.path,
                tier=self._tier,
                limit=self._policy.limit,
                window_seconds=self._policy.window_seconds,
            )
            if requires_redis_backend:
                raise _redis_backend_unavailable_error() from exc


def rate_limit(tier: RateLimitTier) -> _AppRateLimiter:
    """Bind a named tier to a route or router dependency.

    Example:
        @router.post(
            "/transactions/recompute",
            dependencies=[Depends(rate_limit(RateLimitTier.EXPENSIVE))],
        )
        async def recompute(...):
            ...

    Example:
        auth_router = APIRouter(
            prefix="/auth",
            dependencies=[Depends(rate_limit(RateLimitTier.AUTH))],
        )

    Example:
        app.include_router(
            api_router,
            prefix="/api/v1",
            dependencies=[Depends(rate_limit(RateLimitTier.DEFAULT))],
        )
    """
    policy = _policy_for_tier(tier)
    if policy is None:
        raise ValueError("RateLimitTier.EXEMPT should use @skip_limiter, not rate_limit(...)")
    return _AppRateLimiter(tier, policy)


__all__ = [
    "RateLimitTier",
    "initialize_rate_limiting",
    "rate_limit",
    "skip_limiter",
]
