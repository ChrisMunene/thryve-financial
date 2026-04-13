"""Background task helpers for transaction categorization workflows."""

from __future__ import annotations

import structlog

from app.core.telemetry import operation_span
from app.workers.base import BaseTask
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.workers.categorization_tasks.categorize_transactions",
)
def categorize_transactions_task(
    self,
    *,
    transactions: list[dict],
    source: str = "unknown",
) -> dict[str, int | str]:
    """Reference task for the import flow: categorize a batch of transactions."""

    transaction_count = len(transactions)
    with operation_span(
        "categorization.execute",
        attributes={
            "task_name": self.name,
            "source": source,
            "transaction_count": transaction_count,
        },
    ) as span:
        categorized_count = transaction_count
        if span.is_recording():
            span.set_attribute("categorized_count", categorized_count)

    logger.info(
        "categorization.completed",
        source=source,
        transaction_count=transaction_count,
        categorized_count=categorized_count,
    )
    return {
        "source": source,
        "received": transaction_count,
        "categorized": categorized_count,
    }
