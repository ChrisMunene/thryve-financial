"""Small helpers for application-level tracing spans."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind

_SENSITIVE_ATTRIBUTE_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "set_cookie",
    "set-cookie",
    "token",
    "x_api_key",
    "x_secret",
}
_SENSITIVE_ATTRIBUTE_PATTERN = re.compile(
    r"(password|secret|token|authorization|cookie|api[_-]?key)",
    re.IGNORECASE,
)


def _normalize_attribute_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _is_sensitive_attribute(key: str) -> bool:
    normalized = _normalize_attribute_key(key)
    return normalized in _SENSITIVE_ATTRIBUTE_NAMES or bool(
        _SENSITIVE_ATTRIBUTE_PATTERN.search(key)
    )


def _coerce_span_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, str | bool | int | float]:
    if not attributes:
        return {}

    safe_attributes: dict[str, str | bool | int | float] = {}
    for key, value in attributes.items():
        if value is None or _is_sensitive_attribute(key):
            continue
        if isinstance(value, bool):
            safe_attributes[key] = value
            continue
        if isinstance(value, (str, int, float)):
            safe_attributes[key] = value
    return safe_attributes


@contextmanager
def operation_span(
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    """Start a small app-owned span around a business or workflow step."""

    tracer = trace.get_tracer("pfm.app")
    with tracer.start_as_current_span(
        name,
        kind=kind,
        attributes=_coerce_span_attributes(attributes),
    ) as span:
        yield span
