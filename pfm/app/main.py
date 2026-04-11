import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimitTier, initialize_rate_limiting, rate_limit
from app.core.security import SecurityHeadersMiddleware
from app.core.telemetry import bootstrap_api_telemetry
from app.middleware.correlation import (
    CorrelationIdMiddleware,
    generate_correlation_id,
    is_valid_request_id,
)
from app.middleware.error_handler import register_error_handlers
from app.middleware.operational import BodySizeLimitMiddleware, RequestTimeoutMiddleware
from app.middleware.user_context import UserContextMiddleware

logger = structlog.get_logger()

async def _cleanup_resources() -> None:
    """Dispose of async resources during shutdown."""
    from app.clients.anthropic import close_client as close_anthropic
    from app.db.redis import redis_client
    from app.db.session import get_engine

    await close_anthropic()
    await get_engine().dispose()
    await redis_client.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()

    app.state.shutting_down = False
    app.state.telemetry_runtime = None

    # 1. Initialize structured logging
    configure_logging(settings.environment, settings.observability.log_level)

    # 2. Initialize OpenTelemetry
    app.state.telemetry_runtime = bootstrap_api_telemetry(app, settings)

    # 3. Initialize Redis
    from app.db.redis import redis_client

    await redis_client.initialize()
    await initialize_rate_limiting()

    # TODO: Load pattern rules into memory
    # TODO: Load few-shot pool into memory

    logger.info("app.started", environment=settings.environment.value)

    yield

    # --- Graceful shutdown ---
    logger.info("app.shutting_down")

    # 1. Signal health check to return 503
    app.state.shutting_down = True

    try:
        await asyncio.wait_for(_cleanup_resources(), timeout=settings.shutdown_timeout)
    except TimeoutError:
        logger.warning("app.shutdown_timeout", timeout_seconds=settings.shutdown_timeout)

    # Flush OTEL after async resources have been drained.
    telemetry_runtime = getattr(app.state, "telemetry_runtime", None)
    if telemetry_runtime is not None:
        telemetry_runtime.shutdown()

    logger.info("app.shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PFM API",
        version=version("pfm"),
        debug=settings.debug,
        lifespan=lifespan,
    )

    # --- Middleware ---
    # FastAPI makes later-added middleware outermost. Keep CORS outermost and
    # correlation/user context outside the operational middleware.
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=settings.request_timeout)
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=settings.request_max_body_size)
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)
    app.add_middleware(UserContextMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name="X-Request-ID",
        update_request_header=True,
        generator=generate_correlation_id,
        validator=is_valid_request_id,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    # --- Error handlers ---
    register_error_handlers(app, debug=settings.debug)

    # --- Routers ---
    from app.api.router import api_router
    app.include_router(
        api_router,
        prefix="/api/v1",
        dependencies=[Depends(rate_limit(RateLimitTier.DEFAULT))],
    )

    return app


app = create_app()
