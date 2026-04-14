"""
Health check endpoints.

GET /api/v1/health — operational health snapshot (dependencies, version, uptime)
GET /api/v1/health/ready — deep readiness (DB, Redis, auth config)
"""

import asyncio
import time
import uuid

import structlog
from fastapi import APIRouter, Request
from fastapi_limiter.decorators import skip_limiter
from sqlalchemy import text

from app.auth.service import AuthService
from app.core.exceptions import DependencyUnavailableError
from app.core.idempotency import IdempotencyRoute
from app.core.responses import ProblemFieldError, Response, success_response
from app.db.redis import redis_client
from app.db.session import get_async_session_factory
from app.dependencies import _get_auth_delegate
from app.schemas import (
    AuthHealthCheck,
    CeleryHealthCheck,
    HealthChecks,
    HealthResponse,
    LatencyHealthCheck,
    ReadinessResponseData,
)

logger = structlog.get_logger()
router = APIRouter(tags=["health"], route_class=IdempotencyRoute)


def _mark_dependency_healthy(dependencies: dict[str, str], name: str) -> None:
    dependencies[name] = "ok"


def _mark_dependency_unhealthy(
    dependencies: dict[str, str],
    name: str,
    exc: Exception,
) -> None:
    logger.warning("health.dependency_failed", dependency=name, error=str(exc))
    dependencies[name] = "error"


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _log_health_check_failure(name: str, exc: Exception) -> None:
    logger.warning("health.check_failed", check=name, error=str(exc))


async def _database_health_check() -> LatencyHealthCheck:
    started = time.perf_counter()
    try:
        async_session_factory = get_async_session_factory()
        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
    except Exception as exc:
        _log_health_check_failure("database", exc)
        return LatencyHealthCheck(status="unhealthy")

    return LatencyHealthCheck(
        status="healthy",
        latency_ms=_elapsed_ms(started),
    )


async def _redis_health_check() -> LatencyHealthCheck:
    started = time.perf_counter()
    probe_key = f"healthcheck:{uuid.uuid4().hex}"
    try:
        redis = redis_client.redis
        await asyncio.wait_for(redis.set(probe_key, "ok", ex=5), timeout=2.0)
        value = await asyncio.wait_for(redis.get(probe_key), timeout=2.0)
        if value != "ok":
            raise RuntimeError("Redis round-trip probe returned an unexpected value.")
        await asyncio.wait_for(redis.delete(probe_key), timeout=2.0)
    except Exception as exc:
        _log_health_check_failure("redis", exc)
        return LatencyHealthCheck(status="unhealthy")

    return LatencyHealthCheck(
        status="healthy",
        latency_ms=_elapsed_ms(started),
    )


async def _auth_health_check() -> AuthHealthCheck:
    provider = None
    try:
        delegate = _get_auth_delegate()
        provider = type(delegate).__name__
        validator = getattr(delegate, "validate_configuration", None)
        if callable(validator):
            validator()
    except Exception as exc:
        _log_health_check_failure("auth", exc)
        return AuthHealthCheck(
            status="unhealthy",
            provider=provider,
        )

    return AuthHealthCheck(
        status="healthy",
        provider=provider,
    )


def _celery_worker_count() -> int:
    from app.workers.celery_app import celery_app

    inspector = celery_app.control.inspect(timeout=1.0)
    stats = inspector.stats()
    return len(stats or {})


async def _celery_queue_depths() -> dict[str, int]:
    from app.workers.celery_app import celery_app
    from kombu.transport.redis import Channel as RedisChannel

    queue_names = [queue.name for queue in celery_app.conf.task_queues]
    redis = redis_client.redis

    queue_depths: dict[str, int] = {}
    for queue_name in queue_names:
        pending_calls = []
        for priority in RedisChannel.priority_steps:
            key = queue_name if priority == 0 else f"{queue_name}{RedisChannel.sep}{priority}"
            pending_calls.append(redis.llen(key))
        pending_results = await asyncio.gather(*pending_calls)
        queue_depths[queue_name] = sum(int(value) for value in pending_results)

    return queue_depths


async def _celery_health_check() -> CeleryHealthCheck:
    try:
        workers, queue_depths = await asyncio.gather(
            asyncio.wait_for(asyncio.to_thread(_celery_worker_count), timeout=2.0),
            asyncio.wait_for(_celery_queue_depths(), timeout=2.0),
        )
    except Exception as exc:
        _log_health_check_failure("celery", exc)
        return CeleryHealthCheck(status="unhealthy")

    if workers <= 0:
        return CeleryHealthCheck(
            status="unhealthy",
            workers=workers,
            queues=queue_depths,
        )

    return CeleryHealthCheck(
        status="healthy",
        workers=workers,
        queues=queue_depths,
    )


async def _build_health_response(request: Request) -> HealthResponse:
    database, redis, auth, celery = await asyncio.gather(
        _database_health_check(),
        _redis_health_check(),
        _auth_health_check(),
        _celery_health_check(),
    )
    all_healthy = all(
        check.status == "healthy"
        for check in (database, redis, auth, celery)
    )
    started_at = getattr(request.app.state, "started_at_monotonic", time.monotonic())
    uptime_seconds = max(0, int(time.monotonic() - started_at))

    return HealthResponse(
        status="healthy" if all_healthy and not request.app.state.shutting_down else "unhealthy",
        checks=HealthChecks(
            database=database,
            redis=redis,
            auth=auth,
            celery=celery,
        ),
        version=request.app.version,
        uptime_seconds=uptime_seconds,
    )


def _readiness_problem(
    *,
    detail: str,
    dependency_names: list[str] | None = None,
) -> DependencyUnavailableError:
    errors = None
    if dependency_names:
        errors = [
            ProblemFieldError(
                source="unknown",
                field=name,
                code="dependency_unavailable",
                message="The dependency readiness check failed.",
            )
            for name in dependency_names
        ]

    return DependencyUnavailableError.default(
        detail=detail,
        errors=errors,
        log_level="warning",
    )


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
@skip_limiter
async def liveness(request: Request) -> HealthResponse:
    """Operational health snapshot with dependency checks."""
    return await _build_health_response(request)


@router.get("/health/ready", response_model=Response[ReadinessResponseData])
@skip_limiter
async def readiness(request: Request) -> Response[ReadinessResponseData]:
    """Deep readiness check. Verifies DB, Redis, auth configuration, and reports status."""
    if request.app.state.shutting_down:
        raise _readiness_problem(
            detail="The service is shutting down and is not ready to accept traffic.",
        )

    dependencies = {}
    healthy = True

    # Database check
    try:
        async_session_factory = get_async_session_factory()
        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        _mark_dependency_healthy(dependencies, "database")
    except Exception as e:
        _mark_dependency_unhealthy(dependencies, "database", e)
        healthy = False

    # Redis check
    try:
        await asyncio.wait_for(redis_client.redis.ping(), timeout=2.0)
        _mark_dependency_healthy(dependencies, "redis")
    except Exception as e:
        _mark_dependency_unhealthy(dependencies, "redis", e)
        healthy = False

    # Auth readiness check
    try:
        auth_service = AuthService(delegate=_get_auth_delegate())
        auth_service.validate_configuration()
        _mark_dependency_healthy(dependencies, "auth")
    except Exception as e:
        _mark_dependency_unhealthy(dependencies, "auth", e)
        healthy = False

    if not healthy:
        raise _readiness_problem(
            detail="One or more readiness checks failed.",
            dependency_names=[name for name, status in dependencies.items() if status != "ok"],
        )

    return success_response(
        ReadinessResponseData(
            dependencies=dependencies,
        )
    )
