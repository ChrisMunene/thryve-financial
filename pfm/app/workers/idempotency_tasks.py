"""Maintenance tasks for idempotency records."""

from __future__ import annotations

import asyncio

import structlog

from app.core.idempotency import cleanup_expired_idempotency_requests
from app.core.telemetry import operation_span
from app.workers.base import BaseTask
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.workers.idempotency_tasks.cleanup_expired_idempotency_requests",
)
def cleanup_expired_idempotency_requests_task(self) -> int:
    """Prune expired idempotency rows and matching Redis cache entries."""
    with operation_span("idempotency.cleanup", attributes={"task_name": self.name}) as span:
        deleted = asyncio.run(cleanup_expired_idempotency_requests())
        if span.is_recording():
            span.set_attribute("deleted_count", deleted)
    logger.info("idempotency.cleanup_complete", deleted=deleted)
    return deleted
