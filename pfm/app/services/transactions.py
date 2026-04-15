"""Service-layer orchestration for transaction import workflows."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.clients.plaid import PlaidClient
from app.core.telemetry import operation_span
from app.workers.base import dispatch_task

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class TransactionImportResult:
    task_id: str
    imported_count: int
    next_cursor: str | None
    has_more: bool


class TransactionImportService:
    """Reference service showing the workflow-span pattern in practice."""

    def __init__(self, plaid_client: PlaidClient) -> None:
        self._plaid_client = plaid_client

    async def import_transactions(
        self,
        *,
        user_id: UUID,
        subject_id: str,
        access_token: str,
        cursor: str | None = None,
    ) -> TransactionImportResult:
        from app.workers.categorization_tasks import categorize_transactions_task

        with operation_span(
            "transactions.import",
            attributes={
                "user_id": str(user_id),
                "subject_id": subject_id,
                "provider": "plaid",
                "operation": "transactions.sync",
            },
        ) as span:
            sync_result = await self._plaid_client.sync_transactions(
                access_token=access_token,
                cursor=cursor,
            )
            imported_count = len(sync_result.added)
            if span.is_recording():
                span.set_attribute("imported_count", imported_count)
                span.set_attribute("has_more", sync_result.has_more)

            queued_task = dispatch_task(
                categorize_transactions_task,
                transactions=sync_result.added,
                source="plaid",
                apply_async_options={"queue": "default"},
            )

        logger.info(
            "transactions.import_accepted",
            user_id=str(user_id),
            subject_id=subject_id,
            provider="plaid",
            task_id=queued_task.id,
            imported_count=imported_count,
            has_more=sync_result.has_more,
        )

        return TransactionImportResult(
            task_id=queued_task.id,
            imported_count=imported_count,
            next_cursor=sync_result.next_cursor,
            has_more=sync_result.has_more,
        )
