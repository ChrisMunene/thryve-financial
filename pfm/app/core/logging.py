"""
Structured JSON logging via structlog.

Features:
- JSON output with consistent fields: timestamp, level, message, correlation_id, service, environment
- Sensitive field redaction (passwords, tokens, API keys, SSNs, etc.)
- Log level configurable per environment
- Correlation ID automatically attached from contextvar
"""

import logging
import re
from typing import Any

import structlog

from app.config import Environment

# Fields whose VALUES should be redacted
SENSITIVE_PATTERNS = re.compile(
    r"(password|secret|token|ssn|api_key|authorization|credit_card|api.key)",
    re.IGNORECASE,
)


def redact_sensitive_fields(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor that redacts values of sensitive fields."""
    for key in list(event_dict.keys()):
        if isinstance(key, str) and SENSITIVE_PATTERNS.search(key):
            event_dict[key] = "[REDACTED]"
        elif isinstance(event_dict[key], dict):
            for nested_key in list(event_dict[key].keys()):
                if isinstance(nested_key, str) and SENSITIVE_PATTERNS.search(nested_key):
                    event_dict[key][nested_key] = "[REDACTED]"
    return event_dict


def add_service_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor that adds service name and environment."""
    event_dict["service"] = "pfm"
    return event_dict


def add_correlation_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor that adds correlation ID from contextvar."""
    from app.core.context import get_correlation_id

    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def configure_logging(environment: Environment, log_level: str) -> None:
    """Configure structlog for the given environment."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared processors
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_service_context,
        add_correlation_id,
        redact_sensitive_fields,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if environment == Environment.DEVELOPMENT:
        # Pretty console output in dev
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON in staging/production
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set stdlib logging level
    logging.basicConfig(level=level, format="%(message)s")
