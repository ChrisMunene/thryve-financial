"""Transaction workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.schemas import CurrentUser
from app.core.idempotency import IdempotencyRoute
from app.dependencies import get_current_user, get_transaction_import_service
from app.schemas import TransactionImportRequest, TransactionImportResponse
from app.services.transactions import TransactionImportService

router = APIRouter(tags=["transactions"], route_class=IdempotencyRoute)


@router.post(
    "/transactions/import",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TransactionImportResponse,
)
async def import_transactions(
    payload: TransactionImportRequest,
    _current_user: CurrentUser = Depends(get_current_user),
    service: TransactionImportService = Depends(get_transaction_import_service),
) -> TransactionImportResponse:
    """Fetch transactions from Plaid and enqueue downstream categorization."""

    _ = _current_user
    result = await service.import_transactions(
        access_token=payload.access_token.get_secret_value(),
        cursor=payload.cursor,
    )
    return TransactionImportResponse(
        task_id=result.task_id,
        imported_count=result.imported_count,
        next_cursor=result.next_cursor,
        has_more=result.has_more,
    )
