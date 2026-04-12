"""
Problem-details helpers and docs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import Environment, get_settings
from app.core.context import get_correlation_id
from app.core.exceptions import PROBLEM_DEFINITIONS, ProblemException
from app.core.responses import PROBLEM_JSON_MEDIA_TYPE, ProblemResponse


def _normalized_base_url(request: Request) -> str:
    settings = get_settings()
    if settings.environment == Environment.DEVELOPMENT:
        return str(request.base_url).rstrip("/")

    configured = settings.public_base_url.rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def problem_type_url(request: Request, type_slug: str) -> str:
    return urljoin(f"{_normalized_base_url(request)}/", f"problems/{type_slug}")


def problem_instance_url(request: Request, request_id: str | None) -> str:
    base_url = _normalized_base_url(request)
    if request_id:
        return urljoin(f"{base_url}/", f"requests/{request_id}")
    return str(request.url)


def build_problem_document(request: Request, exc: ProblemException) -> ProblemResponse:
    request_id = get_correlation_id()
    return ProblemResponse(
        type=problem_type_url(request, exc.type_slug),
        title=exc.title,
        status=exc.status,
        detail=exc.detail,
        instance=problem_instance_url(request, request_id),
        code=exc.code,
        request_id=request_id,
        retryable=exc.retryable,
        errors=exc.errors,
        upstream=exc.upstream,
        user_action=exc.user_action,
    )


def problem_headers(exc: ProblemException) -> dict[str, str]:
    headers = {"Content-Type": PROBLEM_JSON_MEDIA_TYPE}
    headers.update(exc.headers)
    return headers


def problem_response(request: Request, exc: ProblemException) -> JSONResponse:
    document = build_problem_document(request, exc)
    return JSONResponse(
        status_code=exc.status,
        content=document.model_dump(exclude_none=True),
        headers=problem_headers(exc),
        media_type=PROBLEM_JSON_MEDIA_TYPE,
    )


def problem_definition_payload(request: Request, type_slug: str) -> dict[str, Any] | None:
    definition = PROBLEM_DEFINITIONS.get(type_slug)
    if definition is None:
        return None

    return {
        "type": problem_type_url(request, definition.type_slug),
        "title": definition.title,
        "status": definition.status,
        "code": definition.code,
        "description": definition.description,
        "default_detail": definition.default_detail,
        "retryable": definition.retryable,
        "user_action": definition.user_action,
    }
