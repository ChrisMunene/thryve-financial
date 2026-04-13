import atexit
import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    beat_embedded_init,
    beat_init,
    setup_logging,
    worker_process_init,
    worker_process_shutdown,
)
from kombu import Exchange, Queue

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import TelemetryProcessRole, bootstrap_worker_telemetry

settings = get_settings()


def _detect_process_role() -> TelemetryProcessRole:
    argv = {arg.lower() for arg in sys.argv[1:]}
    if "beat" in argv:
        return TelemetryProcessRole.BEAT
    return TelemetryProcessRole.WORKER


configure_logging(settings, _detect_process_role())

celery_app = Celery(
    "pfm",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=[
        "app.workers.categorization_tasks",
        "app.workers.aggregation_tasks",
        "app.workers.idempotency_tasks",
        "app.workers.recap_tasks",
        "app.workers.training_tasks",
    ],
)

# Priority queues
default_exchange = Exchange("default", type="direct")
celery_app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("high", default_exchange, routing_key="high"),
    Queue("low", default_exchange, routing_key="low"),
)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # DLQ: tasks that exhaust retries are acked (not requeued indefinitely)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Graceful shutdown
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=False,
)

celery_app.conf.beat_schedule = {
    "hourly-correction-aggregation": {
        "task": "app.workers.aggregation_tasks.aggregate_corrections",
        "schedule": crontab(minute=0),
    },
    "weekly-recap-generation": {
        "task": "app.workers.recap_tasks.generate_recaps",
        "schedule": crontab(hour=8, minute=0, day_of_week="monday"),
    },
    "weekly-training-export": {
        "task": "app.workers.training_tasks.export_training_data",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
    "daily-idempotency-cleanup": {
        "task": "app.workers.idempotency_tasks.cleanup_expired_idempotency_requests",
        "schedule": crontab(hour=3, minute=30),
    },
}

_telemetry_runtime = None


@setup_logging.connect(weak=False)
def _configure_celery_logging(*args, **kwargs) -> None:
    configure_logging(settings, _detect_process_role())


def _shutdown_telemetry(*args, **kwargs) -> None:
    global _telemetry_runtime
    if _telemetry_runtime is not None:
        _telemetry_runtime.shutdown()
        _telemetry_runtime = None


@worker_process_init.connect(weak=False)
def _bootstrap_worker_telemetry(*args, **kwargs) -> None:
    global _telemetry_runtime
    configure_logging(settings, TelemetryProcessRole.WORKER)
    _telemetry_runtime = bootstrap_worker_telemetry(TelemetryProcessRole.WORKER, settings)


@beat_init.connect(weak=False)
@beat_embedded_init.connect(weak=False)
def _bootstrap_beat_telemetry(*args, **kwargs) -> None:
    global _telemetry_runtime
    configure_logging(settings, TelemetryProcessRole.BEAT)
    _telemetry_runtime = bootstrap_worker_telemetry(TelemetryProcessRole.BEAT, settings)


@worker_process_shutdown.connect(weak=False)
def _shutdown_worker_telemetry(*args, **kwargs) -> None:
    _shutdown_telemetry()


atexit.register(_shutdown_telemetry)
