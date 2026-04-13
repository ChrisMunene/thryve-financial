"""
Health check endpoints.

GET /api/v1/health — shallow liveness (no dependency checks)
GET /api/v1/health/ready — deep readiness (DB, Redis, auth config)
"""

import asyncio

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
from app.schemas import LivenessResponseData, ReadinessResponseData

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


@router.get("/health", response_model=Response[LivenessResponseData])
@skip_limiter
async def liveness() -> Response[LivenessResponseData]:
    """Shallow liveness check. No dependency checks."""
    return success_response(LivenessResponseData())


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
