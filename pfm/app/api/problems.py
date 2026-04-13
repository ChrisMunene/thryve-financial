"""Problem type documentation endpoints."""

from fastapi import APIRouter, Request

from app.core.exceptions import ResourceNotFoundError
from app.core.idempotency import IdempotencyRoute
from app.core.problems import problem_definition_payload
from app.core.responses import Response, success_response
from app.schemas import ProblemDefinitionResponse

router = APIRouter(tags=["problems"], route_class=IdempotencyRoute)


@router.get(
    "/problems/{type_slug}",
    response_model=Response[ProblemDefinitionResponse],
)
async def problem_type_definition(
    request: Request,
    type_slug: str,
) -> Response[ProblemDefinitionResponse]:
    payload = problem_definition_payload(request, type_slug)
    if payload is None:
        raise ResourceNotFoundError.for_resource("problem type", type_slug)
    return success_response(payload)
