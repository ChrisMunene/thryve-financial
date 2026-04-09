"""
Health check endpoints.

GET /api/v1/health — shallow liveness (no dependency checks)
GET /api/v1/health/ready — deep readiness (DB, Redis, auth config)
"""

import asyncio

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi_limiter.decorators import skip_limiter
from sqlalchemy import text

from app.auth.service import AuthService
from app.db.redis import redis_client
from app.db.session import get_async_session_factory
from app.dependencies import _get_auth_delegate

logger = structlog.get_logger()
router = APIRouter(tags=["health"])


def _mark_dependency_healthy(dependencies: dict[str, str], name: str) -> None:
    dependencies[name] = "ok"


def _mark_dependency_unhealthy(
    dependencies: dict[str, str],
    name: str,
    exc: Exception,
) -> None:
    logger.warning("health.dependency_failed", dependency=name, error=str(exc))
    dependencies[name] = "error"


@router.get("/health")
@skip_limiter
async def liveness() -> dict:
    """Shallow liveness check. No dependency checks."""
    return {"status": "healthy"}


@router.get("/health/ready")
@skip_limiter
async def readiness(request: Request) -> dict:
    """Deep readiness check. Verifies DB, Redis, auth configuration, and reports status."""
    if request.app.state.shutting_down:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})

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

    status_code = 200 if healthy else 503
    result = {
        "status": "healthy" if healthy else "unhealthy",
        "dependencies": dependencies,
    }

    if not healthy:
        return JSONResponse(status_code=status_code, content=result)

    return result
