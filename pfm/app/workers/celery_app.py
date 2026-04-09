from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "pfm",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=[
        "app.workers.categorization_tasks",
        "app.workers.aggregation_tasks",
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
}
