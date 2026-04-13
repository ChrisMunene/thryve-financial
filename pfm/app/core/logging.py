"""
Unified application logging bootstrap.

Production and staging emit newline-delimited JSON to stdout. Development uses
the same event schema with a console renderer unless JSON is explicitly forced.

The logging pipeline is shared across:
- structlog application events
- stdlib/third-party loggers such as uvicorn, asyncio, sqlalchemy, and httpx
- Celery worker and beat processes
"""

from __future__ import annotations

import logging
import logging.config
import os
import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import structlog
from opentelemetry import trace

from app.config import LogFormat, Settings

_REDACTED = "[REDACTED]"
_MAX_REDACTION_DEPTH = 8
_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credit_card",
    "creditcard",
    "card_number",
    "password",
    "refresh_token",
    "secret",
    "set_cookie",
    "set-cookie",
    "ssn",
    "token",
    "x_api_key",
    "x_secret",
}
_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(password|secret|token|ssn|authorization|cookie|api[_-]?key|credit[_-]?card|card[_-]?number)",
    re.IGNORECASE,
)


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _should_redact_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_FIELD_NAMES or bool(_SENSITIVE_FIELD_PATTERN.search(key))


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_REDACTION_DEPTH:
        return value

    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, nested_value in value.items():
            if _should_redact_key(key):
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = _sanitize_value(nested_value, depth=depth + 1)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_value(item, depth=depth + 1) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_value(item, depth=depth + 1) for item in value)

    return value


def redact_sensitive_fields(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Recursively sanitize secret-bearing fields in structured logs."""
    return _sanitize_value(event_dict)


def _package_version() -> str:
    try:
        return version("pfm")
    except PackageNotFoundError:
        return "unknown"


def _process_role_value(process_role: Any) -> str:
    value = getattr(process_role, "value", process_role)
    return str(value)


def _service_name(settings: Settings, process_role: Any) -> str:
    return settings.observability.service_name_for_role(_process_role_value(process_role))


def add_static_context(settings: Settings, process_role: Any):
    """Attach stable process metadata to each event."""
    service_name = _service_name(settings, process_role)
    environment = settings.environment.value
    process_role_value = _process_role_value(process_role)
    app_version = _package_version()

    def processor(
        logger: Any,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        event_dict["service"] = service_name
        event_dict["environment"] = environment
        event_dict["version"] = app_version
        event_dict["process_role"] = process_role_value
        event_dict["process_id"] = os.getpid()
        return event_dict

    return processor


def add_request_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Attach request-scoped identifiers from contextvars when present."""
    from app.core.context import get_correlation_id

    request_id = get_correlation_id()
    if request_id:
        event_dict["request_id"] = request_id

    event_dict = add_current_user_id(logger, method_name, event_dict)
    event_dict = add_current_anonymous_id(logger, method_name, event_dict)
    return event_dict


def add_current_user_id(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Attach the authenticated user ID from request-local context."""
    from app.core.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        event_dict["user_id"] = user_id
    return event_dict


def add_current_anonymous_id(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Attach the anonymous request identifier from request-local context."""
    from app.core.context import get_current_anonymous_id

    anonymous_id = get_current_anonymous_id()
    if anonymous_id:
        event_dict["anonymous_id"] = anonymous_id

    return event_dict


def add_trace_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject the active trace/span IDs when a span is active."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def _use_json_renderer(settings: Settings) -> bool:
    log_format = settings.observability.log_format
    if log_format == LogFormat.JSON:
        return True
    if log_format == LogFormat.CONSOLE:
        return False
    return settings.environment.value != "development"


def _renderer(settings: Settings) -> Any:
    if _use_json_renderer(settings):
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer()


def _shared_processors(settings: Settings, process_role: Any) -> list[Any]:
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        add_static_context(settings, process_role),
        add_request_context,
        add_trace_context,
        redact_sensitive_fields,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if _use_json_renderer(settings):
        processors.append(structlog.processors.format_exc_info)
    return processors


def configure_logging(settings: Settings, process_role: Any) -> None:
    """Configure a shared, idempotent logging pipeline for the current process."""
    level_name = settings.observability.log_level.upper()
    shared_processors = _shared_processors(settings, process_role)
    renderer = _renderer(settings)

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.PositionalArgumentsFormatter(),
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "foreign_pre_chain": shared_processors,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        renderer,
                    ],
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "structured",
                    "stream": "ext://sys.stdout",
                },
                "null": {
                    "class": "logging.NullHandler",
                },
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["null"],
                    "level": "INFO",
                    "propagate": False,
                },
                "asyncio": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "sqlalchemy.engine": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpx": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "celery": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "celery.app.trace": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "kombu": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["default"],
                "level": level_name,
            },
        }
    )
