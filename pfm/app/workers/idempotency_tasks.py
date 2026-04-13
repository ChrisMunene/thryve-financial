"""Maintenance tasks for idempotency records."""

from __future__ import annotations

import asyncio

import structlog

from app.core.idempotency import cleanup_expired_idempotency_requests
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
    deleted = asyncio.run(cleanup_expired_idempotency_requests())
    logger.info("idempotency.cleanup_complete", deleted=deleted)
    return deleted
