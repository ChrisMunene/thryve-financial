"""
Rate limiting adapters built on top of ``fastapi-limiter``.

The package provides the limiting mechanics; this module owns app policy:
identity selection, error envelopes, and fail-open behavior.

Public route API:
    `Depends(rate_limit(RateLimitTier.X))`

Everything else in this module is an internal implementation detail.
"""

import asyncio
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from inspect import isawaitable

import structlog
from fastapi import Request, Response
from fastapi_limiter.decorators import skip_limiter
from fastapi_limiter.depends import RateLimiter as PackageRateLimiter
from pyrate_limiter import Limiter, Rate, RedisBucket

from app.config import Settings, get_settings
from app.core.exceptions import RateLimitedError
from app.db.redis import redis_client

logger = structlog.get_logger()


@dataclass(frozen=True)
class RateLimitPolicy:
    """A requests-per-window rule applied to a route or router."""

    limit: int
    window_seconds: int

_LIMITER_INSTANCE_CACHE: dict[RateLimitPolicy, Limiter] = {}
_LIMITER_INIT_LOCKS: dict[RateLimitPolicy, asyncio.Lock] = {}


class RateLimitTier(StrEnum):
    DEFAULT = "default"
    WRITE = "write"
    EXPENSIVE = "expensive"
    AUTH = "auth"
    EXEMPT = "exempt"


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


async def _get_or_create_limiter(policy: RateLimitPolicy) -> Limiter | None:
    if policy.limit <= 0 or policy.window_seconds <= 0:
        raise ValueError("Rate limit policy values must be greater than 0")

    cached = _LIMITER_INSTANCE_CACHE.get(policy)
    if cached is not None:
        return cached

    lock = _LIMITER_INIT_LOCKS.setdefault(policy, asyncio.Lock())
    async with lock:
        cached = _LIMITER_INSTANCE_CACHE.get(policy)
        if cached is not None:
            return cached

        try:
            bucket = RedisBucket.init(
                [Rate(policy.limit, policy.window_seconds)],
                redis_client.redis,
                bucket_key=f"pfm-rate-limit:{policy.limit}:{policy.window_seconds}",
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
        _LIMITER_INSTANCE_CACHE[policy] = limiter
        return limiter


async def initialize_rate_limiting() -> None:
    """Warm the process-local limiter instance cache once Redis is initialized."""
    _LIMITER_INSTANCE_CACHE.clear()
    _LIMITER_INIT_LOCKS.clear()
    policies = _get_rate_limit_policies().__dict__.values()
    for policy in policies:
        await _get_or_create_limiter(policy)


class _AppRateLimiter:
    """Thin FastAPI dependency wrapper around ``fastapi-limiter``."""

    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy

    async def __call__(self, request: Request, response: Response) -> None:
        limiter = await _get_or_create_limiter(self._policy)
        if limiter is None:
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
                limit=self._policy.limit,
                window_seconds=self._policy.window_seconds,
            )


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
    return _AppRateLimiter(policy)


__all__ = [
    "RateLimitTier",
    "initialize_rate_limiting",
    "rate_limit",
    "skip_limiter",
]
