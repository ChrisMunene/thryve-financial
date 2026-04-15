"""Transaction workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.auth_context import AuthContext
from app.core.idempotency import IdempotencyRoute
from app.core.responses import Response, success_response
from app.dependencies import get_transaction_import_service, require_scopes, require_user
from app.schemas import TransactionImportRequest, TransactionImportResponse
from app.services.transactions import TransactionImportService

router = APIRouter(tags=["transactions"], route_class=IdempotencyRoute)


@router.post(
    "/transactions/import",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Response[TransactionImportResponse],
    dependencies=[Depends(require_scopes("transactions:import"))],
)
async def import_transactions(
    payload: TransactionImportRequest,
    auth_context: AuthContext = Depends(require_user),
    service: TransactionImportService = Depends(get_transaction_import_service),
) -> Response[TransactionImportResponse]:
    """Fetch transactions from Plaid and enqueue downstream categorization."""

    result = await service.import_transactions(
        user_id=auth_context.user.id,
        subject_id=auth_context.principal.subject_id,
        access_token=payload.access_token.get_secret_value(),
        cursor=payload.cursor,
    )
    return success_response(
        TransactionImportResponse(
            task_id=result.task_id,
            imported_count=result.imported_count,
            next_cursor=result.next_cursor,
            has_more=result.has_more,
        )
    )
