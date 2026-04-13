import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.config import get_settings
from app.core.analytics import create_analytics_service
from app.core.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_STATUS_HEADER,
    IdempotencyRoute,
)
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimitTier, initialize_rate_limiting, rate_limit
from app.core.responses import ProblemFieldError, ProblemResponse, ProblemUpstream
from app.core.security import SecurityHeadersMiddleware
from app.core.telemetry import TelemetryProcessRole, bootstrap_api_telemetry
from app.middleware.correlation import (
    CorrelationIdMiddleware,
    generate_correlation_id,
    is_valid_request_id,
)
from app.middleware.error_handler import register_error_handlers
from app.middleware.operational import BodySizeLimitMiddleware, RequestTimeoutMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.request_id import ResponseRequestIdMiddleware
from app.middleware.user_context import UserContextMiddleware

logger = structlog.get_logger()


class ASGIAppWrapper:
    """Expose FastAPI's API surface while running through an outer ASGI wrapper."""

    def __init__(self, app: FastAPI, outer_app: Any) -> None:
        self._app = app
        self._outer_app = outer_app

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app, name)

    async def __call__(self, scope, receive, send) -> None:
        await self._outer_app(scope, receive, send)


async def _cleanup_resources() -> None:
    """Dispose of async resources during shutdown."""
    from app.clients.anthropic import close_client as close_anthropic
    from app.clients.plaid import close_client as close_plaid
    from app.db.redis import redis_client
    from app.db.session import get_engine

    await close_anthropic()
    await close_plaid()
    await get_engine().dispose()
    await redis_client.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()

    app.state.shutting_down = False
    app.state.telemetry_runtime = None
    app.state.analytics = create_analytics_service()

    app.state.telemetry_runtime = bootstrap_api_telemetry(app, settings)

    from app.db.redis import redis_client

    await redis_client.initialize()
    await initialize_rate_limiting()

    logger.info("app.started")

    yield

    logger.info("app.shutting_down")
    app.state.shutting_down = True

    try:
        await asyncio.wait_for(_cleanup_resources(), timeout=settings.shutdown_timeout)
    except TimeoutError:
        logger.warning("app.shutdown_timeout", timeout_seconds=settings.shutdown_timeout)

    analytics = getattr(app.state, "analytics", None)
    if analytics is not None:
        analytics.close()

    telemetry_runtime = getattr(app.state, "telemetry_runtime", None)
    if telemetry_runtime is not None:
        telemetry_runtime.shutdown()

    logger.info("app.shutdown_complete")


def _problem_response_component(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemResponse"}
            }
        },
    }


def _common_problem_responses() -> dict[int, dict[str, Any]]:
    return {
        400: {"model": ProblemResponse, "description": "Malformed Request"},
        401: {"model": ProblemResponse, "description": "Authentication Required"},
        403: {"model": ProblemResponse, "description": "Permission Denied"},
        404: {"model": ProblemResponse, "description": "Resource Not Found"},
        405: {"model": ProblemResponse, "description": "Method Not Allowed"},
        409: {"model": ProblemResponse, "description": "Conflict"},
        413: {"model": ProblemResponse, "description": "Request Too Large"},
        415: {"model": ProblemResponse, "description": "Unsupported Media Type"},
        422: {"model": ProblemResponse, "description": "Validation Failed"},
        428: {"model": ProblemResponse, "description": "Idempotency Key Required"},
        429: {"model": ProblemResponse, "description": "Rate Limited"},
        500: {"model": ProblemResponse, "description": "Internal Server Error"},
        503: {"model": ProblemResponse, "description": "Dependency Unavailable"},
        504: {"model": ProblemResponse, "description": "Upstream Timeout"},
    }


def _install_openapi_schema(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            description=app.description,
        )

        components = schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        schemas.setdefault(
            "ProblemFieldError",
            ProblemFieldError.model_json_schema(ref_template="#/components/schemas/{model}"),
        )
        schemas.setdefault(
            "ProblemUpstream",
            ProblemUpstream.model_json_schema(ref_template="#/components/schemas/{model}"),
        )
        schemas.setdefault(
            "ProblemResponse",
            ProblemResponse.model_json_schema(ref_template="#/components/schemas/{model}"),
        )

        responses = components.setdefault("responses", {})
        responses["Problem400"] = _problem_response_component("Malformed Request")
        responses["Problem401"] = _problem_response_component("Authentication Required")
        responses["Problem403"] = _problem_response_component("Permission Denied")
        responses["Problem404"] = _problem_response_component("Resource Not Found")
        responses["Problem405"] = _problem_response_component("Method Not Allowed")
        responses["Problem409"] = _problem_response_component("Conflict")
        responses["Problem413"] = _problem_response_component("Request Too Large")
        responses["Problem415"] = _problem_response_component("Unsupported Media Type")
        responses["Problem422"] = _problem_response_component("Validation Failed")
        responses["Problem428"] = _problem_response_component("Idempotency Key Required")
        responses["Problem429"] = _problem_response_component("Rate Limited")
        responses["Problem500"] = _problem_response_component("Internal Server Error")
        responses["Problem503"] = _problem_response_component("Dependency Unavailable")
        responses["Problem504"] = _problem_response_component("Upstream Timeout")

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


def create_app() -> ASGIAppWrapper:
    settings = get_settings()
    configure_logging(settings, TelemetryProcessRole.API)

    app = FastAPI(
        title="PFM API",
        version=version("pfm"),
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.shutting_down = False
    app.state.telemetry_runtime = None
    app.state.analytics = None
    app.router.route_class = IdempotencyRoute

    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=settings.request_timeout)
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=settings.request_max_body_size)
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)
    app.add_middleware(
        RequestLoggingMiddleware,
        enabled=settings.observability.log_requests,
        log_healthcheck_requests=settings.observability.log_healthcheck_requests,
        log_options_requests=settings.observability.log_options_requests,
    )
    app.add_middleware(UserContextMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name="X-Request-ID",
        update_request_header=True,
        generator=generate_correlation_id,
        validator=is_valid_request_id,
    )

    register_error_handlers(app, debug=settings.debug)

    from app.api.problems import router as problems_router
    from app.api.router import api_router

    app.include_router(problems_router)
    app.include_router(
        api_router,
        prefix="/api/v1",
        dependencies=[Depends(rate_limit(RateLimitTier.DEFAULT))],
        responses=_common_problem_responses(),
    )

    _install_openapi_schema(app)

    outer_app = CORSMiddleware(
        app=ResponseRequestIdMiddleware(app),
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            IDEMPOTENCY_KEY_HEADER,
            "X-Anonymous-ID",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID", IDEMPOTENCY_KEY_HEADER, IDEMPOTENCY_STATUS_HEADER],
    )
    return ASGIAppWrapper(app, outer_app)


app = create_app()
