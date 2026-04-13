"""
Base Celery task with built-in retry, correlation ID, and structured logging.

All app tasks should inherit from BaseTask.
"""

import uuid

import structlog
from celery import Task
from opentelemetry.propagate import inject

from app.core.context import clear_correlation_id, set_correlation_id
from app.core.telemetry import get_metrics
from app.core.telemetry.tracing import operation_span

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
        )

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("task.completed", task_name=self.name, task_id=task_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "task.failed",
            task_name=self.name,
            task_id=task_id,
            error=str(exc),
            exception_type=type(exc).__name__,
            retry_count=self.request.retries,
            exc_info=(type(exc), exc, exc.__traceback__),
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


def _dispatch_log_context(
    *,
    task_name: str,
    task_id: str,
    apply_async_options: dict[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_name": task_name,
        "task_id": task_id,
    }
    for key in ("queue", "routing_key", "countdown", "eta"):
        value = apply_async_options.get(key)
        if value is not None:
            payload[key] = value
    return payload


def dispatch_task(task, *args, apply_async_options: dict[str, object] | None = None, **kwargs):
    """Dispatch a task with correlation ID from the current request context."""
    from app.core.context import get_correlation_id

    task_name = getattr(task, "name", "unknown")
    options = dict(apply_async_options or {})
    task_id = str(options.get("task_id") or uuid.uuid4())
    options["task_id"] = task_id

    correlation_id = get_correlation_id()
    headers = dict(options.pop("headers", {}))
    if correlation_id:
        headers["correlation_id"] = correlation_id
    inject(headers)
    log_context = _dispatch_log_context(
        task_name=task_name,
        task_id=task_id,
        apply_async_options=options,
    )

    with operation_span("task.enqueue", attributes=log_context):
        try:
            result = task.apply_async(args=args, kwargs=kwargs, headers=headers, **options)
        except Exception as exc:
            logger.error(
                "task.dispatch_failed",
                exception_type=type(exc).__name__,
                exc_info=(type(exc), exc, exc.__traceback__),
                **log_context,
            )
            raise

        logger.info("task.dispatched", **log_context)
        get_metrics().record_task_dispatch(task_name=task_name)
        return result
