"""Problem type documentation endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import ResourceNotFoundError
from app.core.idempotency import IdempotencyRoute
from app.core.problems import problem_definition_payload

router = APIRouter(tags=["problems"], route_class=IdempotencyRoute)


@router.get("/problems/{type_slug}")
async def problem_type_definition(request: Request, type_slug: str) -> JSONResponse:
    payload = problem_definition_payload(request, type_slug)
    if payload is None:
        raise ResourceNotFoundError.for_resource("problem type", type_slug)
    return JSONResponse(payload)
