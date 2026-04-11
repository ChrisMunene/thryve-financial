"""
Base Celery task with built-in retry, correlation ID, and structured logging.

All app tasks should inherit from BaseTask.
"""

import structlog
from celery import Task
from opentelemetry.propagate import inject

from app.core.context import clear_correlation_id, set_correlation_id
from app.core.telemetry import get_metrics

logger = structlog.get_logger()


class BaseTask(Task):
    """Base task class with retry, correlation ID injection, and logging."""

    autoretry_for = (Exception,)
    max_retries = 3
    retry_backoff = 60  # 60s, 120s, 240s with exponential backoff
    retry_backoff_max = 300
    retry_jitter = True

    def before_start(self, task_id, args, kwargs):
        # Inject correlation ID from task headers
        correlation_id = self.request.get("correlation_id")
        if correlation_id:
            set_correlation_id(correlation_id)

        get_metrics().adjust_in_flight_tasks(task_name=self.name, delta=1)

        logger.info(
            "task.started",
            task_name=self.name,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("task.completed", task_name=self.name, task_id=task_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "task.failed",
            task_name=self.name,
            task_id=task_id,
            error=str(exc),
            retry_count=self.request.retries,
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(
            "task.retrying",
            task_name=self.name,
            task_id=task_id,
            error=str(exc),
            retry_count=self.request.retries,
        )

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        get_metrics().adjust_in_flight_tasks(task_name=self.name, delta=-1)
        clear_correlation_id()


def dispatch_task(task, *args, **kwargs):
    """Dispatch a task with correlation ID from the current request context."""
    from app.core.context import get_correlation_id

    correlation_id = get_correlation_id()
    headers = {"correlation_id": correlation_id} if correlation_id else {}
    inject(headers)
    get_metrics().record_task_dispatch(task_name=getattr(task, "name", "unknown"))
    return task.apply_async(args=args, kwargs=kwargs, headers=headers)
